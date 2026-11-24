#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实菜单栏操作：合成 ⌘-拖（Phase 10 核心）。

用户三条批评指向同一个缺口——我们过去只维护一份「逻辑顺序」，从没动过系统
菜单栏本身，所以：设成弹窗显示图标还在菜单栏上、拖半天顺序也不变。

Thaw 的做法（读源码 docs/ARCHITECTURE.md §152-166）：
- 排序：优先写「Menu Bar Layout」位置文件，写不动才退到合成 ⌘-拖；
- 隐藏：私有组件 PlatformRuntimeKit 让 MenuBarAgent 按 App 隐藏，或 Native
  走系统设置里每家 App 的开关。Apple 系统图标对合成拖有抵抗（源码
  MenuBarItemTag.isNonConcealableSystemItem 明说），我们一律跳过。

本模块只做真机实测走得通、且可安全复刻的那条路——**合成 ⌘-拖**：
按住 ⌘ 在菜单栏上拖动一个状态项 = macOS 原生「移动/收纳」它（不是拖进它
自己的 App）。三个动作全部实测通过（tmp/t_p10_drag.py 及本机截图）：

    reorder(src, dst_x)  把 src 拖到 dst_x → 真实菜单栏换序
    hide(item)           把 item ⌘-拖进刘海 → 系统把它收进溢出区（stashed）
    reveal(item)         先展开溢出区，再把 item 拖回可见段 → 取消 stashed

坐标都是全局 CG 坐标（左上原点），与 inventory 报的 frame 同一套。
"""
import time

import Quartz

from peasebar import inventory
from peasebar.axutil import notch_region

_CMD_KEYCODE = 0x37  # 55：左 Command
_HID = Quartz.kCGHIDEventTap

# 用户定调（2026-11-24）：任何时候都不允许控制鼠标——合成 ⌘-拖会让光标自己
# 飘到菜单栏来回拖，体验上像中毒。总闸关掉后 command_drag/movable 直接短路，
# 上层（显隐/换序/放出收纳区）自动退化为只做 CC 静默同步。
# 显隐本来就有无鼠标的 CC 通道；真实菜单栏的「顺序」需要拖拽才能改，
# 停用后面板/设置页顺序仍正确，只是栏上物理顺序不再被代劳。
SYNTH_DRAG_ENABLED = False


def _post_mouse(kind, pt, flags, click=None):
    e = Quartz.CGEventCreateMouseEvent(None, kind, pt, Quartz.kCGMouseButtonLeft)
    if flags is not None:
        Quartz.CGEventSetFlags(e, flags)
    if click is not None:
        Quartz.CGEventSetIntegerValueField(e, Quartz.kCGMouseEventClickState, click)
    Quartz.CGEventPost(_HID, e)


def command_drag(src, dst, steps=16, hold=0.02):
    """⌘ 按住，从 src=(x,y) 直线拖到 dst=(x,y) 再松手。

    总闸 SYNTH_DRAG_ENABLED 关掉时直接返回（不碰鼠标），下面真实拖拽仅作历史保留。"""
    if not SYNTH_DRAG_ENABLED:
        return
    CMD = Quartz.kCGEventFlagMaskCommand
    Quartz.CGWarpMouseCursorPosition(src)
    # 交还光标与硬件的关联，避免 warp 后事件坐标与实际指针不一致
    try:
        Quartz.CGAssociateMouseAndMouseCursorPosition(True)
    except Exception:  # noqa: BLE001 — 老签名没有就直接跳过
        pass
    time.sleep(0.12)
    Quartz.CGEventPost(_HID, Quartz.CGEventCreateKeyboardEvent(None, _CMD_KEYCODE, True))
    time.sleep(0.06)
    _post_mouse(Quartz.kCGEventLeftMouseDown, src, CMD, click=1)
    time.sleep(0.18)  # 抓取停留：让系统进入拖拽态
    # 起手抖动：先小步移动两三下，触发拖拽识别
    for jx in (3, 6, 3):
        _post_mouse(Quartz.kCGEventLeftMouseDragged, (src[0] + jx, src[1]), CMD)
        time.sleep(0.05)
    sx, sy = src
    dx, dy = dst
    for i in range(1, steps + 1):
        t = i / steps
        _post_mouse(Quartz.kCGEventLeftMouseDragged, (sx + (dx - sx) * t,
                     sy + (dy - sy) * t), CMD)
        time.sleep(hold)
    _post_mouse(Quartz.kCGEventLeftMouseUp, dst, CMD, click=1)
    Quartz.CGEventPost(_HID, Quartz.CGEventCreateKeyboardEvent(None, _CMD_KEYCODE, False))
    # 拖完把光标交回原处附近，避免停在菜单栏上碍事
    Quartz.CGWarpMouseCursorPosition((dx, min(dy + 40, 900)))


def _center(frame):
    x, y, w, h = frame
    return (x + w / 2.0, y + h / 2.0)


def movable(item):
    """能不能被真实拖动：必须是可点的第三方图标（Apple 系统项与收纳按钮拒绝合成拖）。
    字段一律 getattr 容错：桩对象/缺属性的项直接判不可拖，不抛。
    总闸关掉时一律判不可拖：所有调用方（换序/隐藏/放出）据此立刻短路，不碰鼠标。"""
    if not SYNTH_DRAG_ENABLED:
        return False
    if item is None:
        return False
    if getattr(item, "frame", None) is None or getattr(item, "el", None) is None:
        return False
    if getattr(item, "is_stash_button", False):
        return False
    bid = getattr(item, "owner_bundle_id", None) or ""
    if bid in ("?", "") or bid == "com.apple.MenuBarAgent":
        return False
    # Apple 自家（含 com.apple.xxx.agent 之类）对 ⌘-拖有抵抗，跳过（同 Thaw）
    return not bid.startswith("com.apple.")


def _notch_mid_x():
    from AppKit import NSScreen
    n = notch_region(NSScreen.mainScreen())
    return (n[0] + n[1]) / 2.0 if n else None


def _stash_drop_x():
    """逐枚隐藏的落点 x：拖到系统「溢出/收纳」区即可被隐藏。

    真机取证：本机有刘海，被收纳项堆在**刘海左侧**（x 小于刘海左缘），
    拖到刘海中点（死区）反而不生效。所以优先级：
    1. 已有隐藏簇 → 拖到最左那枚被收纳项的中心（最稳，直接归堆）；
    2. 无隐藏簇但有刘海 → 拖到刘海左缘外一点（新开辟隐藏位）；
    3. 无刘海但有收纳按钮 → 拖到收纳按钮左侧。
    都拿不到返回 None（这枚没法逐枚隐藏）。
    """
    try:
        items, _ = inventory.list_items()
    except Exception:  # noqa: BLE001
        items = []
    # 1. 已有隐藏簇：拖到最左那枚被收纳项附近，最稳
    stashed = [m.frame for m in items
               if getattr(m, "stashed", False) and not m.is_stash_button and m.frame]
    if stashed:
        return min(f[0] + f[2] / 2.0 for f in stashed)
    # 2. 没隐藏簇：有刘海就拖到刘海左侧外
    from AppKit import NSScreen
    n = notch_region(NSScreen.mainScreen())
    if n:
        return n[0] - 60.0
    # 3. 无刘海：拖到收纳按钮左侧
    for m in items:
        if getattr(m, "is_stash_button", False) and m.frame:
            return m.frame[0] - 40.0
    return None


def reorder(src_item, dst_item, after=True):
    """把 src_item 在真实菜单栏上拖到 dst_item 的前/后，达成目标顺序。"""
    ok = movable(src_item) and src_item.frame and dst_item and dst_item.frame
    if not ok:
        print(f"[PeaseBar][拖] reorder 跳过：movable={movable(src_item)} "
              f"src有帧={bool(src_item and src_item.frame)} dst有帧={bool(dst_item and dst_item.frame)}")
        return False
    df = dst_item.frame
    # after：落到 dst 右边界外一点；否则落到 dst 左边界内一点
    tx = df[0] + df[2] + 6 if after else max(2.0, df[0] - 6)
    y = _center(src_item.frame)[1]
    print(f"[PeaseBar][拖] reorder {getattr(src_item,'owner_bundle_id','?')} "
          f"src={_center(src_item.frame)} -> dst_x={round(tx,1)} after={after}")
    command_drag(_center(src_item.frame), (tx, y))
    return True


def hide(item):
    """把 item ⌘-拖进系统收纳区，直到真机确认它已 stashed（失败重试）。

    有刘海拖进刘海左侧；无刘海拖到收纳按钮左侧的隐藏段。拖完不盲返 True，
    而是重新盘点轮询它的 stashed 是否变 True，没变就重算落点再拖，最多 tries 次。
    返回是否真的隐藏成功。
    """
    if not (movable(item) and item.frame):
        print(f"[PeaseBar][拖] hide 跳过：movable={movable(item)} 有帧={bool(item and item.frame)}")
        return False
    tries = 3
    for _attempt in range(tries):
        cur = _find(item) or item
        if cur is None or not getattr(cur, "frame", None):
            break
        if getattr(cur, "stashed", False):
            return True  # 已在收纳区，视为成功
        mx = _stash_drop_x()
        if mx is None:
            print("[PeaseBar][拖] hide 跳过：未找到收纳落点（无刘海且无收纳按钮）")
            return False
        y = _center(cur.frame)[1]
        print(f"[PeaseBar][拖] hide {getattr(cur,'owner_bundle_id','?')} "
              f"src={_center(cur.frame)} -> 收纳落点 x={round(mx,1)}（第{_attempt+1}次）")
        command_drag(_center(cur.frame), (mx, y))
        if _wait_state(item, want_stashed=True, timeout=1.6):
            return True
    ok = bool(getattr(_find(item) or item, "stashed", False))
    if not ok:
        print(f"[PeaseBar][拖] hide 未生效（{getattr(item,'owner_bundle_id','?')}）：溢出区可能已满或该项不可拖")
    return ok


def reveal(item):
    """把被收纳的 item 拖回可见段，直到真机确认它已不再 stashed（失败重试）。

    先展开溢出区拿到它的真实坐标，再拖到可见区最右；拖完轮询 stashed 是否转 False。
    返回是否真的显示成功。
    """
    if not SYNTH_DRAG_ENABLED:
        return False
    if item is None or getattr(item, "el", None) is None:
        return False
    if getattr(item, "is_stash_button", False):
        return False
    bid = getattr(item, "owner_bundle_id", None) or ""
    if not bid or bid == "com.apple.MenuBarAgent" or bid.startswith("com.apple."):
        return False
    if not inventory.set_stash_revealed(True):
        return False
    try:
        for _attempt in range(3):
            fresh = _find(item)
            if fresh is None or fresh.frame is None:
                break
            if not getattr(fresh, "stashed", False):
                return True  # 已在可见段
            items, _ = inventory.list_items()
            vis = [m.frame[0] + m.frame[2] for m in items
                   if m.frame and not m.stashed and not m.is_stash_button
                   and m.owner_bundle_id != "com.apple.MenuBarAgent"]
            right = max(vis, default=fresh.frame[0] + 200)
            y = _center(fresh.frame)[1]
            print(f"[PeaseBar][拖] reveal {getattr(fresh,'owner_bundle_id','?')} "
                  f"src={_center(fresh.frame)} -> 可见最右 x={round(right-8,1)}（第{_attempt+1}次）")
            command_drag(_center(fresh.frame), (right - 8, y))
            if _wait_state(item, want_stashed=False, timeout=1.6):
                return True
        return not bool(getattr(_find(item) or item, "stashed", False))
    finally:
        inventory.set_stash_revealed(False)


def _wait_state(item, want_stashed, timeout=1.6, poll=0.2) -> bool:
    """拖拽后轮询盘点，直到该图标的 stashed 达到期望值或超时。"""
    end = time.time() + timeout
    while time.time() < end:
        m = _find(item)
        if m is not None and bool(getattr(m, "stashed", False)) == want_stashed:
            return True
        time.sleep(poll)
    m = _find(item)
    return bool(m is not None and getattr(m, "stashed", False) == want_stashed)


def _find(item):
    """按 (bundle_id, 稳定名) 在最新一轮盘点里找回同一枚图标（帧坐标会变）。"""
    items, _ = inventory.list_items()
    want = (item.owner_bundle_id, item.key_part or item.label)
    for m in items:
        if (m.owner_bundle_id, m.key_part or m.label) == want:
            return m
    return None
