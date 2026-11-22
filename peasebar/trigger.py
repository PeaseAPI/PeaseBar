#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图标触发（F3「找回并触发」的执行端）。

macOS 27.2.1 实测（T59/T60）：**合成 HID 点击已经打不开任何菜单栏项目**——
左键/右键打到控制中心、时钟、微信的槽位上，指针确实移过去了，窗口一个没多。
所以 T7/T17 时代「合成右键是最通用的菜单触发」这条经验在新系统上作废了。
反过来，对托管元素执行 AXPress 是有效的（T61 逐图标取证）：

    控制中心 / Wi‑Fi → 面板真的展开（layer 101）
    ToDesk / EdgeShelf / Alcove / 钉钉 / PeaseClash / TG Pro / One Switch → 弹出原生菜单
    微信 / QQ / Synology → 弹出各自的 App 窗口（左键语义）

因此这里改成 Thaw 的打法（ConcealedItemOpenMethod：每家 App 只答某几种方式，
按阶梯试、看结果学）：
1. AXPress（托管元素只 advertise 这一个动作，系统模块多一个 AXShowMenu）；
2. 没看到反应且元素支持 AXShowMenu → 补一次 AXShowMenu；
3. 拿不到 AX 元素（少数 App 不进托管树，如 Little Snitch Agent）→ 退回合成右键。

**判据是「有没有出现新窗口」，不是错误码**（同 Thaw press() 的复核）：
实测 err=-25204（cannotComplete）照样弹菜单（钉钉/TG Pro/One Switch），
err=0 也可能只是执行了一个不开窗的默认动作（OneDrive 刷新、Snapzy 剪切）。
"""
import time

import Quartz

from peasebar import axutil

# 等弹窗落定的总时长与轮询步长（窗口出现即提前返回，不白等）
SETTLE = 1.0
POLL = 0.15


def _snapshot():
    """当前屏幕上的窗口集合：{窗口号: (归属 pid, 层, (x,y,w,h))}。"""
    out = {}
    for w in Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        b = dict(w.get("kCGWindowBounds"))
        num = w.get("kCGWindowNumber")
        if num is None or b.get("Height", 0) <= 40:
            continue  # 菜单栏本体/光标阴影这类细条不算弹窗
        out[num] = (w.get("kCGWindowOwnerPID"), w.get("kCGWindowLayer"),
                    (b["X"], b["Y"], b["Width"], b["Height"]))
    return out


def _opened_since(base, pid):
    """base 之后新出现的窗口（优先归属 pid，但也接受菜单层的外来窗口）。"""
    return [v for k, v in _snapshot().items()
            if k not in base and (v[0] == pid or v[1] == 101)]


def _wait_open(base, pid, settle=SETTLE):
    """轮询等新窗口，出现就返回，最多等 settle 秒。"""
    end = time.time() + settle
    while time.time() < end:
        got = _opened_since(base, pid)
        if got:
            return got
        time.sleep(POLL)
    return []


def _synth_right_click(item):
    """旧通道：按 frame 合成右键（27 上多半无效，仅在拿不到 AX 元素时试一次）。"""
    fx, fy, fw, fh = item.frame
    cx, cy = fx + fw / 2, fy + fh / 2
    for etype in (Quartz.kCGEventMouseMoved,
                  Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp):
        Quartz.CGEventPost(
            Quartz.kCGHIDEventTap,
            Quartz.CGEventCreateMouseEvent(None, etype, (cx, cy), Quartz.kCGMouseButtonRight))
        time.sleep(0.1)
    return cx, cy


def open_item(item):
    """触发一个盘点项。返回 (说明, 是否看到了窗口反应)。"""
    el = getattr(item, "el", None)
    if el is None:
        if item.frame is None:
            return "无 AX 元素也无坐标，触发不了", False
        cx, cy = _synth_right_click(item)
        base = _snapshot()
        time.sleep(SETTLE)
        got = _opened_since(base, item.owner_pid)
        return f"无元素 → 合成右键@({cx:.0f},{cy:.0f})，反应={len(got)} 个新窗口", bool(got)

    axutil.set_messaging_timeout(el, 0.5)  # 触发要跨进程，比盘点放宽一点
    base = _snapshot()
    err = axutil.perform_action(el, "AXPress")
    got = _wait_open(base, item.owner_pid)
    if got:
        return f"AXPress 生效（err={err}，{len(got)} 个新窗口）", True

    if "AXShowMenu" in axutil.element_actions(el):
        base = _snapshot()
        err2 = axutil.perform_action(el, "AXShowMenu")
        got = _wait_open(base, item.owner_pid)
        if got:
            return f"AXPress 无反应 → AXShowMenu 生效（err={err2}）", True
        return f"AXPress(err={err})/AXShowMenu(err={err2}) 都没看到窗口", False

    # 没弹窗口不等于没生效：很多图标的左键语义本来就不开窗（刷新、开主窗已有等）
    return f"AXPress 已投递（err={err}），未看到新窗口", False
