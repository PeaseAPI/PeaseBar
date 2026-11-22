#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图标盘点引擎（F1）。

数据源（docs/DEVELOPMENT.md §5 T2/T3）：
- 系统图标：MenuBarAgent（com.apple.MenuBarAgent）的 AXExtrasMenuBar，
  结构为若干 AXGroup（各包 1 个 AXMenuBarItem）+ 1 个原生收纳按钮（AXButton）；
- 第三方图标：各运行 App 进程自己的 AXExtrasMenuBar（直接是 AXMenuBarItem 数组）。

已知约束：
- 图标不可见时 owner 进程 AXExtrasMenuBar 报 -25212（T13/T14），但该错误码无法区分
  「无状态项 / 被收纳 / 菜单栏被全屏隐藏」，因此本引擎不做精确“被收纳”判定，
  只列出 AX 通道不可用的候选进程（ax_unavailable），真收纳清单由 F12 展开舞步 diff 得出；
- 后台守护（activationPolicy == 2 .prohibited）直接跳过，不参与枚举；
- 坐标一律全局 CG 坐标（左上原点），刘海遮挡判定 = 图标矩形与刘海横向区间相交。

终端自检：`python3 -m peasebar.inventory` 直接打印盘点表（需辅助功能权限）。
"""
from dataclasses import dataclass, field

import ApplicationServices as AS
from AppKit import NSWorkspace

from peasebar.axutil import (
    app_element_for_pid,
    copy_children,
    element_frame,
    element_role,
    element_string,
    notch_region,
    rect_intersects,
)

# 图标不可见（被收纳）时 AXExtrasMenuBar 的错误码（T13）
AX_ERR_NOT_IMPLEMENTED = -25212

_MENU_BAR_AGENT_BID = "com.apple.MenuBarAgent"


@dataclass
class MenuItem:
    """菜单栏图标盘点项。"""

    owner_app: str            # 归属应用显示名
    owner_bundle_id: str      # 归属应用 bundle id
    owner_pid: int            # 归属进程 pid
    label: str                # 图标名（AXDescription 优先，回退 AXTitle）
    role: str                 # AXMenuBarItem / AXButton 等
    frame: tuple = None       # (x, y, w, h)，全局 CG 坐标
    notched: bool = False     # 是否被刘海遮挡
    is_stash_button: bool = False  # 是否为系统原生收纳/展开按钮
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
    if ok:
        import time

        time.sleep(0.5)  # 展开动画
    return ok


def _agent_element():
    """取 MenuBarAgent 的 AX 应用元素；找不到返回 None。"""
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if (app.bundleIdentifier() or "") == _MENU_BAR_AGENT_BID:
            return app_element_for_pid(app.processIdentifier())
    return None


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


def list_items():
    """全量盘点菜单栏图标。返回 (items, ax_unavailable_apps)。

    items：可见图标列表（含系统图标与原生收纳按钮）；
    ax_unavailable_apps：AXExtrasMenuBar 报 -25212 的非后台进程 (应用名, bundleId) 列表——
    可能是「无状态项 / 被收纳 / 菜单栏被全屏隐藏」，不做精确判定（见模块注释）。
    """
    notch = _screen_notch()
    pids = _pid_table()
    items = []
    ax_unavailable = []

    # 1) 系统侧：MenuBarAgent（T2，带懒加载唤醒）
    agent = _agent_element()
    if agent is not None:
        items.extend(_collect_agent_items(agent, notch))

    # 2) 第三方侧：逐进程 AXExtrasMenuBar（T3）；-25212 只计候选不做判定（T13/T14）
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.processIdentifier() <= 0:
            continue
        if app.activationPolicy() == 2:  # .prohibited：后台守护不参与枚举
            continue
        name, bid = app.localizedName() or "?", app.bundleIdentifier() or "?"
        if bid == _MENU_BAR_AGENT_BID:
            continue
        el = app_element_for_pid(app.processIdentifier())
        err, extras = copy_children(el, "AXExtrasMenuBar")
        if err == AX_ERR_NOT_IMPLEMENTED or not extras:
            if err == AX_ERR_NOT_IMPLEMENTED:
                ax_unavailable.append((name, bid))
            continue
        for it in extras:
            items.append(_make_item(it, name, bid, app.processIdentifier(), notch))

    items.sort(key=lambda m: (m.frame[0] if m.frame else 1e9))
    return items, ax_unavailable


def main():
    """终端自检入口：打印盘点表。"""
    if not AS.AXIsProcessTrusted():
        print("缺少辅助功能权限，无法盘点（系统设置 → 隐私与安全性 → 辅助功能）")
        return
    items, ax_unavailable = list_items()
    sys_items = [m for m in items if m.owner_bundle_id == _MENU_BAR_AGENT_BID]
    third = [m for m in items if m.owner_bundle_id != _MENU_BAR_AGENT_BID]
    print(f"== 系统图标（MenuBarAgent）{len(sys_items)} 项 ==")
    for m in sys_items:
        tag = "[收纳按钮]" if m.is_stash_button else ""
        print(f"  {tag}{m.label}  frame={m.frame}  刘海遮挡={m.notched}")
    print(f"== 第三方图标 {len(third)} 项 ==")
    for m in third:
        pos = f"({m.frame[0]:.0f},{m.frame[1]:.0f},{m.frame[2]:.0f},{m.frame[3]:.0f})" if m.frame else "无坐标"
        print(f"  [{m.owner_app} / {m.owner_bundle_id}] {m.label}  {pos}  刘海遮挡={m.notched}")
    print(f"== AX 通道不可用进程 {len(ax_unavailable)} 个（无状态项/被收纳/菜单栏隐藏，不作判定） ==")
    for name, bid in ax_unavailable:
        print(f"  {name} / {bid}")
    notched = [m for m in items if m.notched]
    print(f"== 刘海遮挡 {len(notched)} 项 ==")
    for m in notched:
        print(f"  [{m.owner_app}] {m.label}")


if __name__ == "__main__":
    main()
