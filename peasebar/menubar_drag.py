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


def _post_mouse(kind, pt, flags, click=None):
    e = Quartz.CGEventCreateMouseEvent(None, kind, pt, Quartz.kCGMouseButtonLeft)
    if flags is not None:
        Quartz.CGEventSetFlags(e, flags)
    if click is not None:
        Quartz.CGEventSetIntegerValueField(e, Quartz.kCGMouseEventClickState, click)
    Quartz.CGEventPost(_HID, e)


def command_drag(src, dst, steps=16, hold=0.02):
    """⌘ 按住，从 src=(x,y) 直线拖到 dst=(x,y) 再松手。

    菜单栏状态项的 ⌘-拖有个坑：按下后得先短暂停留并小幅移动，系统才把它识别成
    「拖拽抓取」；按下即高速平移会被当成一次点击，拖不动。所以这里：warp 后交还
    光标→按下→原地抖两下起手→再匀速拖到 dst。"""
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
    字段一律 getattr 容错：桩对象/缺属性的项直接判不可拖，不抛。"""
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
    """把 item ⌘-拖进刘海：macOS 把它收进溢出区（下一次盘点 stashed=True）。"""
    if not (movable(item) and item.frame):
        print(f"[PeaseBar][拖] hide 跳过：movable={movable(item)} 有帧={bool(item and item.frame)}")
        return False
    mx = _notch_mid_x()
    if mx is None:
        print("[PeaseBar][拖] hide 跳过：未检测到刘海（_notch_mid_x=None）")
        return False  # 无刘海屏，这条路不适用（老屏用溢出按钮，另议）
    y = _center(item.frame)[1]
    print(f"[PeaseBar][拖] hide {getattr(item,'owner_bundle_id','?')} "
          f"src={_center(item.frame)} -> 刘海中点 x={round(mx,1)}")
    command_drag(_center(item.frame), (mx, y))
    return True


def reveal(item):
    """把被收纳的 item 拖回可见段：先展开溢出区拿到它的真实坐标，再拖到可见区最右。"""
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
        time.sleep(0.25)
        fresh = _find(item)
        if fresh is None or fresh.frame is None:
            return False
        items, _ = inventory.list_items()
        vis = [m.frame[0] + m.frame[2] for m in items
               if m.frame and not m.stashed and not m.is_stash_button
               and m.owner_bundle_id != "com.apple.MenuBarAgent"]
        right = max(vis, default=fresh.frame[0] + 200)
        y = _center(fresh.frame)[1]
        command_drag(_center(fresh.frame), (right - 8, y))
        return True
    finally:
        inventory.set_stash_revealed(False)


def _find(item):
    """按 (bundle_id, 稳定名) 在最新一轮盘点里找回同一枚图标（帧坐标会变）。"""
    items, _ = inventory.list_items()
    want = (item.owner_bundle_id, item.key_part or item.label)
    for m in items:
        if (m.owner_bundle_id, m.key_part or m.label) == want:
            return m
    return None
