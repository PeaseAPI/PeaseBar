#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图标盘点引擎（F1）。

数据源（docs/DEVELOPMENT.md §5 T2/T3/T46）——按「托管优先、自有通道兜底」两级：
1. **托管通道（主，照 Thaw 的 MenuBarAgentWindow）**：macOS 27 把整条菜单栏的图标
   都装进 MenuBarAgent 自己的窗口里画：
       MenuBarAgent → AXWindows → AXWindow(AXDialog) → 每个图标一个 AXGroup（槽位 frame）
       槽位里再套一个「跨进程引用」元素（AXApplication / AXButton / AXMenuBarItem），
       用 AXUIElementGetPid 取它的归属进程 pid——**读一个进程就看清整条菜单栏**，
       不用问任何一家 App，也不用管它是否已经把图标交给宿主；
   实测本机（T46/T53）：92 个进程的 AXExtrasMenuBar 全部报 -25212（kAXErrorNoValue，
   「这个属性没值」），旧通道因此只盘点到 4 个系统图标；托管通道一次拿回 25 项。
2. **自有通道（兜底）**：各 App 进程自己的 AXExtrasMenuBar + MenuBarAgent 的
   AXExtrasMenuBar（系统模块与原生收纳按钮），托管树拿不到时才用。

已知约束：
- -25212 是 kAXErrorNoValue（Thaw 视为「这个 App 没有图标」），不能当「图标被收纳」的证据；
  「被收纳」改由收纳按钮（chevron）的横坐标判定：槽位中心在按钮左侧 = 藏起来了（stashed）；
- 坐标一律全局 CG 坐标（左上原点），刘海遮挡判定 = 图标矩形与刘海横向区间相交；
- AX 往返一律设 0.25s 超时（Thaw defaultMessagingTimeout），某个 App 卡死不拖慢整轮。

终端自检：`python3 -m peasebar.inventory` 直接打印盘点表（需辅助功能权限）。
"""
from dataclasses import dataclass, field
import re

import ApplicationServices as AS
from AppKit import NSWorkspace

from peasebar.axutil import (
    app_element_for_pid,
    copy_children,
    element_actions,
    element_frame,
    element_pid,
    element_role,
    element_string,
    notch_region,
    rect_intersects,
    set_messaging_timeout,
)

# 图标不可见（被收纳）时 owner 进程 AXExtrasMenuBar 的错误码（T13；
# 实为 kAXErrorNoValue：Thaw 用它区分「没有图标」与「读超时/被拒」）
AX_ERR_NOT_IMPLEMENTED = -25212

_MENU_BAR_AGENT_BID = "com.apple.MenuBarAgent"

# AX 往返超时（秒），照 Thaw AXPrimitives.defaultMessagingTimeout
AX_MESSAGING_TIMEOUT = 0.25


@dataclass
class MenuItem:
    """菜单栏图标盘点项。"""

    owner_app: str            # 归属应用显示名
    owner_bundle_id: str      # 归属应用 bundle id
    owner_pid: int            # 归属进程 pid（系统模块与收纳按钮 = MenuBarAgent 的 pid）
    label: str                # 图标名（AXDescription 优先，回退 AXTitle）
    role: str                 # AXMenuBarItem / AXButton 等
    frame: tuple = None       # (x, y, w, h)，全局 CG 坐标
    notched: bool = False     # 是否被刘海遮挡
    is_stash_button: bool = False  # 是否为系统原生收纳/展开按钮
    stashed: bool = False     # 是否被系统收进收纳区（当前没画在菜单栏可见段上）
    key_part: str = ""        # 配置键里代替 label 的稳定部（为空则用 label）
    el: object = field(repr=False, default=None)  # AX 元素引用（触发 AXPress 用）


def _pid_table():
    """建 pid → (应用名, bundleId) 映射表。"""
    table = {}
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        table[app.processIdentifier()] = (
            app.localizedName() or "?",
            app.bundleIdentifier() or "?",
        )
    return table


def _screen_notch():
    """取主屏刘海区 (x0, x1)；无刘海返回 None。"""
    from AppKit import NSScreen

    main = NSScreen.mainScreen()
    if main is None:
        return None
    return notch_region(main)


def _make_item(el, owner_app, owner_bid, owner_pid, notch):
    """把一个 AX 元素转成 MenuItem（读名称/角色/坐标/遮挡）。"""
    label = element_string(el, "AXDescription") or element_string(el, "AXTitle") or "(未命名)"
    label = " ".join(label.split())  # 清理换行/多空白（如 OneDrive 描述自带换行）
    role = element_role(el) or "?"
    frame = element_frame(el)
    return MenuItem(
        owner_app=owner_app,
        owner_bundle_id=owner_bid,
        owner_pid=owner_pid,
        label=label,
        role=role,
        frame=frame,
        notched=rect_intersects(frame, *notch) if notch else False,
        is_stash_button=(role == "AXButton"),
        key_part=_stable_key_part(el, owner_app),
        el=el,
    )


def _stash_button_state(agent_el):
    """读原生收纳按钮当前状态：返回 (button_el, revealed)；无按钮返回 (None, False)。

    依据 E1/T2：描述含「隐藏」且不含「显示」= 已展开态（按钮描述此时为「隐藏菜单栏项目」）。
    """
    err, tops = _agent_top_items(agent_el)
    for it in tops:
        if element_role(it) == "AXButton":
            desc = element_string(it, "AXDescription") or ""
            revealed = ("隐藏" in desc) and ("显示" not in desc)
            return it, revealed
    return None, False


def _agent_top_items(agent_el):
    """MenuBarAgent AXExtrasMenuBar 的直接子元素列表（自动下钻单容器）。"""
    return copy_children(agent_el, "AXExtrasMenuBar")


def stash_revealed():
    """读原生收纳区当前是否展开。无收纳按钮时返回 False。"""
    agent = _agent_element()
    if agent is None:
        return False
    _, revealed = _stash_button_state(agent)
    return revealed


def set_stash_revealed(want_revealed):
    """把系统收纳区切到期望状态（True=展开 / False=收起）。返回是否成功。"""
    agent = _agent_element()
    if agent is None:
        return False
    btn, revealed = _stash_button_state(agent)
    if btn is None or revealed == want_revealed:
        return btn is not None
    from peasebar.axutil import perform_press

    ok = perform_press(btn)
    if not ok:
        return False
    import time

    # 等状态落定：轮询收纳按钮描述翻到期望值（同 Thaw 的 settled 思路）。
    # 以前这里固定睡 0.6s 再走「预热遍历」拖慢 0.5s，托管通道下没必要：
    # 一轮盘点只读 MenuBarAgent 一个进程（实测 0.05s），动画停了结果就对了。
    agent = _agent_element()
    deadline = time.time() + 1.5
    while time.time() < deadline:
        time.sleep(0.1)
        _, now = _stash_button_state(agent)
        if now == want_revealed:
            break
    return True


def _agent_element():
    """取 MenuBarAgent 的 AX 应用元素；找不到返回 None。"""
    return _agent_element_and_pid()[0]


def _agent_element_and_pid():
    """取 MenuBarAgent 的 (AX 应用元素, pid)；找不到返回 (None, None)。"""
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if (app.bundleIdentifier() or "") == _MENU_BAR_AGENT_BID:
            pid = app.processIdentifier()
            return app_element_for_pid(pid), pid
    return None, None


def _collect_agent_items(agent, notch):
    """收集系统图标（MenuBarAgent 树），带懒加载唤醒重试。

    实测：MenuBarAgent 的 AX 子树（AXMenuBarItem）是懒加载的，闲置后可能返回空
    Group，反复查询会唤醒；故空结果时小睡重查，直到拿到 Item 或重试耗尽。
    """
    import time

    best = []
    for _attempt in range(3):
        err, tops = _agent_top_items(agent)
        batch = []
        for it in tops or []:
            role = element_role(it)
            if role == "AXGroup":
                _, inner = copy_children(it, "AXChildren")
                for sub in inner or []:
                    batch.append(_make_item(sub, "系统", _MENU_BAR_AGENT_BID, -1, notch))
            elif role != "AXMenuBar":  # 顶层容器本身不是图标
                batch.append(_make_item(it, "系统", _MENU_BAR_AGENT_BID, -1, notch))
        if any(b.role == "AXMenuBarItem" for b in batch):
            return batch  # Item 到手，树已唤醒
        if len(batch) > len(best):
            best = batch
        time.sleep(0.7)  # 等待懒加载注入
    return best


def _hosted_label(el, owner_app):
    """托管图标的名字：描述 / 提示 / 标题里挑一个能看懂的。

    纯数字（QQ 未读数「5」）与空串不算名字，退回应名（否则图标名会随消息数变化）。
    """
    for attr in ("AXDescription", "AXHelp", "AXTitle"):
        raw = element_string(el, attr)
        if not raw:
            continue
        first = " ".join(raw.split("\n")[0].split())  # tooltip 常是多行，只取首行
        if not first or first.isdigit():
            continue
        return first
    return owner_app or "(未命名)"


# 稳定的 AXIdentifier 长得像反向域名（com.apple.menuextra.clock），系统模块都有；
# 第三方给往往是状态文本（实测 OneDrive 的 identifier 就是「OneDrive\n已备份和同步」），不当稳定值
_STABLE_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(\.[A-Za-z0-9_-]+){1,}$")


def _stable_key_part(el, owner_app):
    """配置键的稳定部：优先 AXIdentifier（反向域名形状），否则用应名。

    实测教训（T55）：label 常常是“会变的活文本”——TG Pro 是温度、PeaseClash 是刚刚
    复制的命令、Snapzy 是剪切内容——拿它当分区/缓存键会使图标每次盘点都不是同一个。
    """
    ident = element_string(el, "AXIdentifier") or ""
    if _STABLE_IDENT_RE.match(ident):
        return ident
    return owner_app or ""


def _slot_inspect(slot, agent_pid):
    """看一个托管槽位，返回 (归属 pid, 可点元素, 字形 frame)。

    只钻容器层，三条铁律（T53/T54 实测）：
    - AXApplication 只认身份不下钻：它里面是 App 自己的窗口与主菜单（File/Edit 那些），
      钻进去会拿到一堆不相干的 AXMenuBarItem；
    - AXButton / AXMenuBarItem 就是图标本体，拿到就停，同样不再下钻；
    - 可点条件是 advertise 了 AXPress（托管按钮只有这一个动作，没有 AXShowMenu）。
    """
    owner = agent_pid
    press_el, glyph = None, None
    queue = [(c, 0) for c in copy_children(slot, "AXChildren")[1] or []]
    while queue:
        cur, depth = queue.pop(0)
        role = element_role(cur)
        pid = element_pid(cur)
        if pid is not None and pid != agent_pid:
            owner = pid
        if role in ("AXButton", "AXMenuBarItem"):
            if press_el is None and "AXPress" in element_actions(cur):
                press_el, glyph = cur, element_frame(cur)
            continue
        if role == "AXApplication":
            continue
        if depth < 3:
            queue.extend((c, depth + 1) for c in copy_children(cur, "AXChildren")[1] or [])
    return owner, press_el, glyph


def _agent_windows(agent):
    """MenuBarAgent 的菜单栏窗口（AXWindows 优先，拿不到时从 AXChildren 里筛窗口）。"""
    set_messaging_timeout(agent, AX_MESSAGING_TIMEOUT)
    err, wins = copy_children(agent, "AXWindows")
    if wins:
        return wins
    _, kids = copy_children(agent, "AXChildren")
    return [k for k in kids or [] if element_role(k) == "AXWindow"]


def _collect_hosted_items(agent, agent_pid, notch, pids):
    """托管通道：一次读 MenuBarAgent 的窗口树拿回整条菜单栏图标（主数据源）。

    两个窗口是同一批槽位的两张面：一张里套的是归属 App 的 AXApplication（只给身份），
    另一张里是真正可点的 AXButton（实测 pid 就是归属 App，T53）。
    故按「(归属 pid, 槽位 x, 槽位宽)」归并：同一图标在两张面里自然合到一条，
    可点元素取 AXButton/AXMenuBarItem，坐标优先用元素自己的字形矩形（截像素更准）。

    收纳区展开后，旧位上的身份槽会残留成“只有身份、无可点元素”的重复项（实测 T55）；
    同一 pid 已经有人拿得到可点元素时，这种空壳直接丢。
    """
    slots = {}  # (pid, x, w) -> dict
    for win in _agent_windows(agent):
        set_messaging_timeout(win, AX_MESSAGING_TIMEOUT)
        for slot in copy_children(win, "AXChildren")[1] or []:
            if element_role(slot) != "AXGroup":
                continue
            slot_frame = element_frame(slot)
            if not slot_frame or slot_frame[2] <= 0:
                continue  # 零宽 = 正在变动的空槽（Thaw settled 判定），本轮不信
            inner = copy_children(slot, "AXChildren")[1] or []
            if not inner:
                continue  # 收纳按钮的空组（chevron 走 extras 通道拿）
            owner, click_el, click_frame = _slot_inspect(slot, agent_pid)
            if owner is None:
                continue
            key = (owner, round(slot_frame[0] * 4), round(slot_frame[2] * 4))
            rec = slots.setdefault(key, {"slot": slot_frame, "el": None, "glyph": None,
                                         "owner": owner})
            if click_el is not None and rec["el"] is None:
                rec["el"] = click_el
                rec["glyph"] = click_frame
    entries = list(slots.values())
    pressable_owners = {e["owner"] for e in entries if e["el"] is not None}
    entries = [e for e in entries
               if e["el"] is not None or e["owner"] not in pressable_owners]
    items = []
    for rec in entries:
        owner = rec["owner"]
        name, bid = pids.get(owner, ("?", "?"))
        if owner == agent_pid:
            name, bid = "系统", _MENU_BAR_AGENT_BID
        el = rec["el"] or rec["slot"]
        frame = rec["glyph"] or rec["slot"]
        label = _hosted_label(el, name)
        items.append(MenuItem(
            owner_app=name,
            owner_bundle_id=bid,
            owner_pid=owner,
            label=label,
            role=element_role(el) or "?",
            frame=frame,
            notched=rect_intersects(frame, *notch) if notch else False,
            key_part=_stable_key_part(el, name),
            el=rec["el"],
        ))
    return items


def list_items():
    """全量盘点菜单栏图标。返回 (items, ax_unavailable_apps)。

    items：菜单栏上的图标（含系统模块与原生收纳按钮），已标出刘海遮挡/被收纳；
    ax_unavailable_apps：只在「托管通道不可用、退回自有通道」时才填，
    为自有通道报 -25212/超时的非后台进程 (应用名, bundleId) 列表。
    """
    # 无辅助功能权限时快速失败：逐进程 AX 查询会长时间阻塞（每个超时数秒），
    # 面板会因此卡死；直接返回空清单，原因放进 ax_unavailable 供 UI 中文提示
    if not AS.AXIsProcessTrusted():
        return [], [("（未授权）", "需要辅助功能权限：系统设置 → 隐私与安全性 → 辅助功能")]

    notch = _screen_notch()
    pids = _pid_table()
    agent, agent_pid = _agent_element_and_pid()

    # 1) 主：托管通道（一次读一个进程就看清整条菜单栏）
    items = _collect_hosted_items(agent, agent_pid, notch, pids) if agent else []
    unavailable = []
    if not items:
        # 2) 兜底：旧的双自有通道（MenuBarAgent extras + 各家 App extras）
        #    T46：新系统上这条路只能给出系统图标，故仅当托管树空时才走
        if agent is not None:
            items.extend(_collect_agent_items(agent, notch))
        items.extend(_collect_owner_items(notch, pids))

    # 收纳按钮：从 extras 通道拿（它是裸 AXButton，托管树里是空组），既当分区基准又供联动
    stash_btn = None
    if agent is not None:
        stash_btn, _ = _stash_button_state(agent)
    if stash_btn is not None:
        st = element_frame(stash_btn)
        items = [m for m in items if not (st and m.frame
                                         and abs(m.frame[0] - st[0]) < 2 and abs(m.frame[2] - st[2]) < 2)]
        desc = element_string(stash_btn, "AXDescription") or "显示隐藏菜单栏项目"
        items.append(MenuItem(
            owner_app="系统", owner_bundle_id=_MENU_BAR_AGENT_BID, owner_pid=agent_pid,
            label=" ".join(desc.split()), role="AXButton", frame=st,
            is_stash_button=True, el=stash_btn))

    # 被收纳判定：槽位中心在收纳按钮左边 = 藏起来了（收起时挤在按钮口，展开时排到更左边）
    if stash_btn is not None and element_frame(stash_btn):
        sx, sw = element_frame(stash_btn)[0], element_frame(stash_btn)[2]
        chevron_mid = sx + sw / 2
        for m in items:
            if m.frame and not m.is_stash_button:
                m.stashed = (m.frame[0] + m.frame[2] / 2) < chevron_mid

    items.sort(key=lambda m: (m.frame[0] if m.frame else 1e9))
    _dedup_keys(items)
    return items, unavailable


def _dedup_keys(items):
    """同 App 多图标时给配置键加序号，避免两格撞同一键。

    实测（T55）：一个 App 可以挂两枚状态项，而托管树里它们的身份完全一样
    （同 pid、同应名、同 AXIdentifier），不分序号则分区设置与位图缓存只能记住第一枚。
    序号按横坐标从左到右，同一轮会话内稳定（图标换位则序号跟着换，可接受）。
    """
    seen = {}
    for m in items:
        if m.is_stash_button:
            continue
        base = (m.owner_bundle_id, m.key_part or m.label)
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            m.key_part = f"{base[1]}#{seen[base]}"


def _collect_owner_items(notch, pids):
    """自有通道（兜底）：并行枚举各进程 AXExtrasMenuBar（T3）。返回 (items, unavailable)。"""
    from concurrent.futures import ThreadPoolExecutor

    apps = []
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.processIdentifier() <= 0:
            continue
        if app.activationPolicy() == 2:  # .prohibited：后台守护不参与枚举
            continue
        name, bid = app.localizedName() or "?", app.bundleIdentifier() or "?"
        if bid == _MENU_BAR_AGENT_BID:
            continue
        apps.append((app.processIdentifier(), name, bid))

    def _probe(pid):
        el = app_element_for_pid(pid)
        set_messaging_timeout(el, AX_MESSAGING_TIMEOUT)
        return copy_children(el, "AXExtrasMenuBar")

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_probe, [a[0] for a in apps]))

    items = []
    for (pid, name, bid), (err, extras) in zip(apps, results):
        for it in extras or []:
            items.append(_make_item(it, name, bid, pid, notch))
    return items


def main():
    """终端自检入口：打印盘点表。"""
    if not AS.AXIsProcessTrusted():
        print("缺少辅助功能权限，无法盘点（系统设置 → 隐私与安全性 → 辅助功能）")
        return
    items, ax_unavailable = list_items()
    sys_items = [m for m in items if m.owner_bundle_id == _MENU_BAR_AGENT_BID]
    third = [m for m in items if m.owner_bundle_id != _MENU_BAR_AGENT_BID]
    print(f"== 总 {len(items)} 项（系统 {len(sys_items)} / 第三方 {len(third)}）==")
    for m in items:
        tags = []
        if m.is_stash_button:
            tags.append("收纳按钮")
        if m.stashed:
            tags.append("被收纳")
        if m.notched:
            tags.append("刘海遮挡")
        tag = f" [{'/'.join(tags)}]" if tags else ""
        pos = f"({m.frame[0]:.0f},{m.frame[1]:.0f},{m.frame[2]:.0f},{m.frame[3]:.0f})" if m.frame else "无坐标"
        press = "可AX点" if m.el is not None else "无元素"
        print(f"  [{m.owner_app} / {m.owner_bundle_id}] {m.label}  {m.role}  {pos}  {press}{tag}")
    if ax_unavailable:
        print(f"== 自有通道 AX 不可用进程 {len(ax_unavailable)} 个（仅兜底路径会报） ==")
        for name, bid in ax_unavailable:
            print(f"  {name} / {bid}")


if __name__ == "__main__":
    main()
