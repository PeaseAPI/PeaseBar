#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图标触发（F3「找回并触发」的执行端）。

macOS 27.2.1 实测（T65/T66 逐图标图谱，25 项全跑）：**两条通道各管一半，谁都不是万能**。

    AXPress 开窗 17/25 —— Qoder/欧路词典/ToDesk/EdgeShelf/Alcove/TextInputMenuAgent/
                          CleanMyMac/AlDente/控制中心/Synology…
    合成右键开窗 8/25 —— 钉钉/QQ/PeaseClash/TG Pro/One Switch/Wi‑Fi/LaunchOS/Little Snitch
    只有合成点击有效：LaunchOS、Little Snitch Agent（后者根本不给 AX 元素）
    被系统收纳的 9 项：合成点击 0/9 有效——它的 frame 不是画出来的位置，点击落在邻居槽位

所以 T7/T17 时代的「合成右键万能」和上一轮 T59/T60 的「合成点击彻底失效」都是过度概括：
真相是按 App 家族分裂（同 Thaw 的 isElectronItem 判定——Electron 系忽略合成点击，必须 AX press）。

阶梯（判据永远是「有没有出现新窗口」，不是错误码）：
1. AXPress（托管元素只 advertise 这一个动作）；
2. 没看到反应且元素支持 AXShowMenu → 补一次 AXShowMenu；
3. 仍没反应、且图标没被收纳（坐标可信）→ 补一次合成右键；
4. 拿不到 AX 元素（如 Little Snitch Agent）→ 直接合成右键。

实测 err=-25204（cannotComplete）照样弹菜单（钉钉/TG Pro/One Switch），
err=0 也可能只是执行了一个不开窗的默认动作（OneDrive 刷新、Snapzy 剪切）。

合成点击的字段工法（照 Thaw menuBarItemEvent/postClickEvents，但按其踩坑取舍）：
投 **session tap**（不是 HID tap）、打 kCGEventTargetUnixProcessID、
down 的 clickState=1 / up=0、mouseUp 连发两次（对端偶尔漏 release 会卡在按下态）。
**绝不能塞 windowID 与「指针下窗口」字段**：Thaw 那里是合成哈希，我们照着塞假值后
钉钉的菜单就不弹了（T65 配方 D），PostToPid 投递同样归零（配方 E）。
"""
import threading
import time

import Quartz

from peasebar import axutil

# 同一时刻只跑一条阶梯：连点多个格子时后面的排队，不并发往不同 App 投事件
# （并发合成点击会互相把对方的弹层顶掉，观察结果也就不可信了）
_ladder = threading.Semaphore(1)

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


def _synth_right_click(item, settle=SETTLE):
    """合成右键（Thaw 配方）：session tap + 目标 pid + clickState，up 发两次。

    只对坐标可信的图标有用（T66：8/25 开窗，被收纳的 9 项 0/25 全落空）。
    返回 (说明, 是否看到新窗口)。

    已按用户要求停用（2026-11-24）：这一步会先把光标 warp 到菜单栏坐标，
    而用户零容忍任何鼠标被控制——触发阶梯只剩纯 AX 两档（AXPress/AXShowMenu）。
    """
    return "合成点击已停用（不控制鼠标）", False
    fx, fy, fw, fh = item.frame
    cx, cy = fx + fw / 2.0, fy + fh / 2.0
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    Quartz.CGWarpMouseCursorPosition((cx, cy))
    time.sleep(0.05)          # 等 Window Server 把 warp 吃掉，否则事件按旧位置路由
    base = _snapshot()
    phases = (Quartz.kCGEventRightMouseDown, 1), \
             (Quartz.kCGEventRightMouseUp, 0), \
             (Quartz.kCGEventRightMouseUp, 0)   # 对端偶尔漏第一次 release，补发（Thaw 同做法）
    for etype, click_state in phases:
        e = Quartz.CGEventCreateMouseEvent(src, etype, (cx, cy), Quartz.kCGMouseButtonRight)
        if e is None:
            return f"合成右键@({cx:.0f},{cy:.0f}) 事件造不出来", False
        Quartz.CGEventSetFlags(e, 0)            # 合成点击不带用户正按着的修饰键
        Quartz.CGEventSetIntegerValueField(e, Quartz.kCGMouseEventClickState, click_state)
        Quartz.CGEventSetIntegerValueField(e, Quartz.kCGEventTargetUnixProcessID, item.owner_pid)
        Quartz.CGEventPost(Quartz.kCGSessionEventTap, e)
        time.sleep(0.08)
    got = _wait_open(base, item.owner_pid, settle)
    return f"合成右键@({cx:.0f},{cy:.0f})，{len(got)} 个新窗口", bool(got)


def open_item(item):
    """触发一个盘点项。返回 (说明, 是否看到了窗口反应)。"""
    el = getattr(item, "el", None)
    if el is None:
        if item.frame is None:
            return "无 AX 元素也无坐标，触发不了", False
        return _synth_right_click(item)

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
        err, how = err2, "AXPress+AXShowMenu"
    else:
        how = "AXPress"

    # 阶梯最后一档：坐标可信（没被收纳）时补一次合成右键——LaunchOS 这类只答点击（T66）
    if item.frame and not getattr(item, "stashed", False):
        msg, seen = _synth_right_click(item)
        if seen:
            return f"{how}(err={err}) 无窗口 → {msg}", True
        return f"{how}(err={err}) 与 {msg} 都没看到窗口", False

    # 没弹窗口不等于没生效：很多图标的左键语义本来就不开窗（刷新、开主窗已有等）
    # 被收纳的图标不试合成点击：frame 不是画出来的位置，点了只会打到邻居（T66）
    tail = "（被收纳，不试坐标点击）" if getattr(item, "stashed", False) else ""
    return f"{how} 已投递（err={err}），未看到新窗口{tail}", False


def open_item_async(item, on_done=None):
    """后台线程跑 open_item。

    阶梯最坏是 AXPress(1s) + AXShowMenu(1s) + 合成右键(1s) 的纯等待，全在 App 主线程里跑
    会冻住面板与热键，所以一律丢后台。on_done(说明, 是否看到窗口) 在子线程回调，
    只能写日志，不得碰 UI（要刷界面请回主线程）。
    """
    def run():
        with _ladder:
            result = open_item(item)
        if on_done is not None:
            on_done(*result)

    threading.Thread(target=run, daemon=True).start()
