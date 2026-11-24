#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ControlCenter 按 App 显隐通道（macOS 27「系统设置 > 菜单栏」的存储直写）。

隐藏机制的真相（真机实证 2026-11-23，Thaw native 模式同源）：
- `~/Library/Group Containers/group.com.apple.controlcenter/.../group.com.apple.controlcenter.plist`
  里的 `trackedApplications[]` 每条记录带 `isAllowed`（该 App 菜单栏图标是否允许显示）；
- 外部写 `isAllowed=false` 后 **killall MenuBarAgent**（渲染宿主重读）→ 图标从菜单栏
  消失而 App 进程照常运行；`isAllowed=true` 同法 → 图标回来。双向可逆；
- **不受系统收纳条容量限制**（这是系统级开关，不是溢出区），因此「想藏几枚藏几枚」；
- 图标隐藏后从 AX 树消失，点击弹窗格子需「先临时显示 → AXPress 弹菜单 → 再收回」。

为何不 killing ControlCenter：只杀 cfprefsd（清偏好缓存）+ MenuBarAgent（渲染宿主）
即可生效；ControlCenter 不参与判定。为何外部写 plist 是安全的：写完立即 killall
cfprefsd，launchd 拉起新实例从磁盘重读，旧缓存不会回写覆盖。
"""
import os
import plistlib
import subprocess
import threading
import time

from peasebar import sections

# 记录文件路径（TCC 只保护目录列举，按完整路径读写不受限——实证可读写）
CC_PLIST = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.controlcenter/"
    "Library/Preferences/group.com.apple.controlcenter.plist")

# 永不允许隐藏的 bundle id：PeaseBar 自己的控制图标必须常显，否则面板叫不出来
PROTECTED = {"com.pease.peasebar"}


def is_protected(bid):
    """true = 这个 bundle id 不适用本通道：PeaseBar 自己，或 Apple 自家（含 agent）。"""
    if not bid:
        return True
    return bid in PROTECTED or bid.startswith("com.apple.")


# 侧车状态文件：记下 PeaseBar 上轮藏了谁（与用户手动在系统设置里关的区分开，
# 启动同步只翻转自己藏过的，不动用户的手动选择）
def state_path():
    return sections.config_path() + ".cc"


def record_hidden(bids):
    """把本轮 PeaseBar 藏的 bundle id 落盘（去重保序）。"""
    import json
    try:
        with open(state_path(), "r", encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        prev = []
    merged = [b for b in prev if b not in bids] + sorted(bids)
    try:
        with open(state_path(), "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False)
    except Exception:
        pass
    return merged


def last_hidden():
    """上轮 PeaseBar 藏的 bundle id 列表（无记录返回空表）。"""
    import json
    try:
        with open(state_path(), "r", encoding="utf-8") as f:
            return [b for b in json.load(f) if not is_protected(b)]
    except Exception:
        return []


def is_writable():
    """记录文件可读可写则通道可用（系统升级可能变动，失败时上层回退拖拽）。"""
    try:
        with open(CC_PLIST, "rb") as f:
            plistlib.load(f)
        return os.access(CC_PLIST, os.W_OK)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 不可控名单：写入 isAllowed=false 并 apply 后图标仍在线的 bid——系统不托管
# 这类 App 的状态项显隐（它们不走 trackedApplications 开关）。记入名单后
# 自检/周期核对不再对其重试，彻底消灭「每分钟闪断」循环。
# 名单持久化到 .cc_unmanageable，App 重启后自动出名单重试一次（系统行为可能变）。
# ---------------------------------------------------------------------------
_unmanageable = set()  # 进程内缓存
_unmanageable_loaded = False


def _unmanageable_path():
    return sections.config_path() + ".cc_unmanageable"


def load_unmanageable():
    """启动时调用：从磁盘读入不可控名单。"""
    global _unmanageable, _unmanageable_loaded
    import json
    _unmanageable_loaded = True
    try:
        with open(_unmanageable_path(), "r", encoding="utf-8") as f:
            _unmanageable = set(json.load(f))
    except Exception:
        _unmanageable = set()


def is_unmanageable(bid):
    """bid 是否已确认「系统不托管其显隐」——自检/周期据此免检免重试。"""
    if not _unmanageable_loaded:
        load_unmanageable()
    return bid in _unmanageable


def mark_unmanageable(bids):
    """把写后仍在线的 bid 加入不可控名单并落盘。"""
    global _unmanageable
    if not _unmanageable_loaded:
        load_unmanageable()
    new = {b for b in bids if b not in _unmanageable and not is_protected(b)}
    if not new:
        return
    _unmanageable |= new
    import json
    try:
        with open(_unmanageable_path(), "w", encoding="utf-8") as f:
            json.dump(sorted(_unmanageable), f, ensure_ascii=False)
    except Exception:
        pass
    print(f"[PeaseBar] CC 不可控名单新增 {len(new)} 项（系统不托管其显隐，"
          f"后续不再重试）：{', '.join(sorted(new)[:5])}")


def unmanageable_set():
    """当前不可控名单快照（调用方据此过滤）。"""
    if not _unmanageable_loaded:
        load_unmanageable()
    return set(_unmanageable)


def clear_unmanageable():
    """启动时重置名单：让所有 bid 获得一次重试机会（系统行为可能已变）。"""
    global _unmanageable, _unmanageable_loaded
    _unmanageable = set()
    _unmanageable_loaded = True


def _unwrap_recs(raw):
    """层层解开 trackedApplications 的各种历史形态，返回 dict 数组；解不出返回 None。

    系统原生格式是 data（内嵌 bplist 数组，取证 layout_table_full.json 铁证）。
    2026-11-24 事故中出现过三种形态：① bytes（原生 data）②裸 dict 数组
    （一度实验直写）③ int 数组（一份 bplist 的字节流被逐字节拆开的事故中间态）。
    ①②③只要内容能解出 dict 数组都能救；解不出返回 None 由调用方清空重建。"""
    if isinstance(raw, bytes):
        try:
            raw = plistlib.loads(raw)
        except Exception:
            return None
    if (isinstance(raw, list) and raw
            and all(isinstance(x, int) and 0 <= x <= 255 for x in raw)):
        try:  # int 数组：拼回字节流再解一层
            raw = plistlib.loads(bytes(raw))
        except Exception:
            return None
    if isinstance(raw, list) and all(isinstance(r, dict) for r in raw):
        return raw
    return None


def _load():
    """读文件，返回 (外层 dict, trackedApplications 记录列表)。"""
    with open(CC_PLIST, "rb") as f:
        outer = plistlib.load(f)
    recs = _unwrap_recs(outer.get("trackedApplications"))
    if recs is None:
        # 内容彻底解不开（连 int 拼回都救不回）：清空重建，启动同步马上会把
        # 配置里的目标态补写回来；系统对其余 App 会在它们建状态项时重新记录
        print("[PeaseBar] CC 记录内容解不开，清空重建（配置目标态随后补写）")
        recs = []
    return outer, recs


def record_bid(rec):
    """取记录的 bundle id：完整记录在 location.bundle._0，简单记录在 bundle._0。"""
    loc = rec.get("location") or rec
    b = loc.get("bundle") if isinstance(loc, dict) else None
    return (b or {}).get("_0")


def hidden_bids_now():
    """当前系统里 isAllowed=false 的 bundle id 集合（诊断用）。"""
    try:
        _, recs = _load()
    except Exception:
        return set()
    return {record_bid(r) for r in recs
            if r.get("isAllowed") is False and record_bid(r)}


def is_app_hidden(bid):
    """查一个 App 此刻的 CC 显隐状态（含前缀匹配）。

    True = 已藏；False = 有记录且显示；None = 管不了（无完整记录，
    例如 Apple 系统项或从未被系统跟踪过的 App），调用方据此回退拖拽。
    """
    try:
        _, recs = _load()
    except Exception:
        return None
    by_bid = {}
    for rec in recs:
        if "isAllowed" not in rec:
            continue
        b = record_bid(rec)
        if b:
            by_bid[b] = rec
    rec = by_bid.get(match_bid(bid, set(by_bid)))
    if rec is None:
        return None
    return rec["isAllowed"] is False


def match_bid(bid, known):
    """在已知 bid 集合里找 bid 的落点：精确优先，退化为包名前缀。

    盘点给的 bundle id 有时带子路径（CleanMyMac 的菜单宿主是
    com.macpaw.CleanMyMac5.Menu，而系统记录挂在 com.macpaw.CleanMyMac5），
    按「前缀 + 分段边界」匹配（com.a.b 不得匹配 com.a.bc）；多个命中取最短
    （最贴近盘点 bid 的安装主体）。无命中返回 None。
    """
    if bid in known:
        return bid
    hits = [k for k in known
            if k.startswith(bid + ".") or bid.startswith(k + ".")]
    if not hits:
        return None
    return min(hits, key=len)


def set_apps_allowed(bids, allowed, hard=True):
    """把 bids 里各 App 的 isAllowed 改成 allowed，返回实际改动的 bundle id 集合。

    只动已有完整记录（带 isAllowed 键）的第三方；PeaseBar 自己与 com.apple.*
    永不触碰。盘点 bid 与系统记录 bid 允许前缀差异（match_bid）。返回的是
    调用方传入的 bid（与配置/侧车同一口径），不是系统记录的落点 bid。

    hard=True（默认）：改完整套 apply_now 立即重画——菜单栏会空一下约 0.3s
    （MenuBarAgent 是整条菜单栏的渲染宿主，重启即闪断）。
    hard=False：只写盘 + 清 cfprefsd 缓存（零闪断），**改动不会立刻反映到栏上**，
    等下一次 hard apply（其它点击/周期核对/schedule_hard_apply 兜底）才生效——
    用于「点完图标后的收回」：用户注意力已离开菜单栏，闪断合并到不看的时刻。
    """
    want = {b for b in bids if not is_protected(b)}
    if not want:
        return set()
    outer, recs = _load()
    # 格式守卫：系统原生格式是 data（嵌套 bplist 数组）。裸数组/字节拆解数组
    # 系统解不开（读不出 isAllowed → 全部失效 → 图标回栏），哪怕内容能救、
    # 目标态一致也要重写一次把磁盘格式统一回原生 data 形态。
    needs_format_fix = not isinstance(outer.get("trackedApplications"), bytes)
    if needs_format_fix:
        print("[PeaseBar] CC 格式守卫：trackedApplications 不是原生 data 形态，"
              "本次写入统一修回")
    by_bid = {}
    for rec in recs:
        if "isAllowed" not in rec:
            continue
        b = record_bid(rec)
        if b:
            by_bid[b] = rec
    changed = set()
    for w in want:
        rec = by_bid.get(match_bid(w, set(by_bid)))
        if rec is not None and rec["isAllowed"] != allowed:
            rec["isAllowed"] = allowed
            changed.add(w)
    if not changed and not needs_format_fix:
        return set()
    # 本键以系统原生 data 格式（嵌套 bplist 数组）写回，整个 plist 由下面统一
    # dumps——裸数组系统解不开，绝不能直接塞
    outer["trackedApplications"] = plistlib.dumps(recs, fmt=plistlib.FMT_BINARY)
    # 原子写：先临时文件再 replace，避免被系统读到半截
    tmp = CC_PLIST + ".peasebar.tmp"
    with open(tmp, "wb") as f:
        f.write(plistlib.dumps(outer, fmt=plistlib.FMT_BINARY))
    os.replace(tmp, CC_PLIST)
    # 写后校验：重读必须能解回 dict 数组，否则如实上报不假装成功
    try:
        with open(CC_PLIST, "rb") as f:
            ok = _unwrap_recs(plistlib.load(f).get("trackedApplications")) is not None
        if not ok:
            print("[PeaseBar] CC 写后校验失败：重读 trackedApplications 解不出 dict 数组")
    except Exception as exc:  # noqa: BLE001
        print(f"[PeaseBar] CC 写后校验异常：{exc}")
    if hard:
        apply_now()
    else:
        # 软生效：只清偏好缓存（不重启 MenuBarAgent，零闪断）；标记待重画，
        # 等下一次 hard apply 或 schedule_hard_apply 兜底把它抹平。
        subprocess.run(["killall", "cfprefsd"], capture_output=True)
        global _pending_soft
        _pending_soft = True
        with _soft_lock:
            for b in changed:
                _soft_targets[b] = allowed
    return changed


# 软写后待重画标记：True=盘上状态与栏上实况可能不一致，需要一次 hard apply
_pending_soft = False
_soft_timer = None
# 软写自标清单 {bid: allowed}：兜底到期先补写盘（防系统回写旧值）再重画；
# 周期核对/实效自检据此免检「收回还挂在栏上」的正常中间态（2026-11-24
# 用户报障#5：刚点完应用就被自检当成漂移强制收回，菜单栏又闪一下）。
_soft_targets = {}
_soft_lock = threading.Lock()


def soft_pending_bids():
    """处于「已写盘、等重画」软生效中间的 bid 集合（调用方据此免检）。"""
    with _soft_lock:
        return set(_soft_targets)


def apply_now():
    """让改动生效：清 cfprefsd 缓存（launchd 秒拉起）+ 重启 MenuBarAgent 重画。

    注意：MenuBarAgent 是整条菜单栏（含 Apple 菜单/应用菜单/右侧图标）的渲染
    宿主，重启期间全栏清空约 0.3s——这就是用户看到的「菜单栏消失一下」。
    仅在必须立即反映实况时走这里；可延迟的场景用 set_apps_allowed(hard=False)。
    """
    global _pending_soft, _soft_timer
    with _soft_lock:
        if _soft_timer is not None:
            _soft_timer.cancel()
            _soft_timer = None
        _pending_soft = False
        _soft_targets.clear()
    for proc in ("cfprefsd", "MenuBarAgent"):
        subprocess.run(["killall", proc], capture_output=True)
    # 给 launchd 拉起与首帧重画一点时间
    time.sleep(0.6)


def schedule_hard_apply(delay=15.0):
    """软写后兜底：delay 秒内若没被别的 hard apply 合并掉，就自己重画一次。

    去抖：多次 schedule 只留最后一个；期间任何 apply_now 会取消定时器（它已
    把软写一并生效）。到期时若 _pending_soft 已被抹平则零动作，不自找闪断。"""
    global _soft_timer
    with _soft_lock:
        if _soft_timer is not None:
            _soft_timer.cancel()

        def _fire():
            global _soft_timer
            with _soft_lock:
                _soft_timer = None
                targets = dict(_soft_targets)
            if not _pending_soft:
                return
            print("[PeaseBar] CC 软写兜底：后台重画一次，抹平待生效的显隐改动")
            # 先把软写目标补写盘一次：软写窗口里系统可能把旧值回写覆盖，
            # 不补写就只是把旧态重画回去，图标会「赖在栏上不收」
            for allowed in (True, False):
                bids = {b for b, a in targets.items() if a == allowed}
                if bids:
                    set_apps_allowed(bids, allowed, hard=False)
            apply_now()

        _soft_timer = threading.Timer(delay, _fire)
        _soft_timer.daemon = True
        _soft_timer.start()


# ---------------------------------------------------------------------------
# 输入法菜单通道（搜狗等输入法的菜单栏图标宿主是 com.apple.TextInputMenuAgent）
# ---------------------------------------------------------------------------
# 真机实证（2026-11-23）：TextInputMenuAgent 是 Apple 进程——CC 按 App 开关不管它
# （trackedApplications 不跟踪），⌘-拖也拖不动（movable 拒绝一切 com.apple.*），
# 但它的显隐由 com.apple.TextInputMenu 域的 visible 键控制，正是系统设置里
# 「在菜单栏中显示输入法菜单」开关的落盘位置：
# - 写 0 + killall TextInputMenuAgent → 图标从菜单栏消失，输入法照常可用；
# - 写 1 + killall TextInputMenuAgent → 图标回来。双向可逆、值不被系统改写。
# 对比死路：TextInputMenuAgent 域里的 NSStatusItem VisibleCC 键是运行时状态
# （进程每次启动把当前可见性写回去），killall 后自动回 1，控制不了。

INPUT_MENU_DOMAIN = "com.apple.TextInputMenu"
INPUT_MENU_AGENT = "com.apple.TextInputMenuAgent"


def input_menu_plist_path():
    return os.path.expanduser(
        "~/Library/Preferences/%s.plist" % INPUT_MENU_DOMAIN)


def input_menu_visible():
    """输入法菜单此刻是否显示（键不存在/读不到按系统默认的「显示」处理）。"""
    try:
        with open(input_menu_plist_path(), "rb") as f:
            return plistlib.load(f).get("visible", 1) == 1
    except Exception:
        return True


def set_input_menu_visible(show):
    """把输入法菜单设为显示（True）或隐藏（False），返回是否实际改动。

    值已一致时不写盘不重启（幂等——60s 周期核对反复调用时零打扰）。改动走
    defaults 写（经 cfprefsd 同步缓存，与系统设置开关同一落盘位置）+ killall
    TextInputMenuAgent（进程重启后按新值决定是否创建状态项）。
    """
    if input_menu_visible() == show:
        return False
    subprocess.run(
        ["defaults", "write", INPUT_MENU_DOMAIN, "visible",
         "-int", "1" if show else "0"], capture_output=True)
    subprocess.run(["killall", INPUT_MENU_AGENT], capture_output=True)
    # 给 launchd 拉起一点时间（图标消失/重现都不是瞬时的）
    time.sleep(0.6)
    return True
