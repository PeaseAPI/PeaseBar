#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局快捷键（F6）：⌥⌘B 切换救援面板。

方案取舍（实测，见 docs/DEVELOPMENT.md §5）：
- Carbon.HIToolbox 不可用（PyObjC 不带 Carbon 绑定，ModuleNotFoundError）；
- NSEvent 全局键盘监听需要「输入监控」新授权（不想再让用户授权一项）；
- CGEventTap 只依赖辅助功能权限（T16 已授权），listen-only 模式不拦截/修改事件，
  ⌥⌘B 照常送达前台 App；kCGSessionEventTap 级别对本用户会话全键盘生效。

回调由挂到主 runloop 的 CFRunLoopSource 驱动，与 UI 同线程；但回调里绝不能干重活：
toggle 要盘点 AX + 截图重建（约 2s），同期 WindowServer 还在等这条 tap 链的返回值，
整个事件管道会被堵住（实测：之后鼠标点击送不到任何 App 的状态项）。
因此回调只做判定，真正的 toggle 用 0 间隔 NSTimer 投递到下一个 runloop 迭代执行。
"""
import objc
import Quartz
from Foundation import NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer


KEY_B = 11  # kVK_ANSI_B
KEY_S = 1   # kVK_ANSI_S（⌥⌘S → 设置窗口）
_HOTKEY_FLAGS = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskAlternate


class _Dispatcher(NSObject):
    """延后执行器：fire: 里才跑真正的重活（保持强引用，防止被回收）。"""

    def init(self):
        self = objc.super(_Dispatcher, self).init()
        if self is None:
            return None
        self.pending = []
        return self

    def defer_(self, fn):
        self.pending.append(fn)
        timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            0.0, self, "fire:", None, False)
        NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)

    def fire_(self, sender):
        if not self.pending:
            return
        fn = self.pending.pop(0)
        try:
            fn()
        except Exception:
            import traceback

            traceback.print_exc()


_dispatcher = None


def install(toggle, on_settings=None):
    """注册 ⌥⌘B / ⌥⌘S 监听，返回卸载函数；tap 创建失败时返回 no-op 并打日志。"""
    global _dispatcher
    mask = 1 << Quartz.kCGEventKeyDown
    if _dispatcher is None:
        _dispatcher = _Dispatcher.alloc().init()

    def _cb(_proxy, _etype, event, _refcon):
        try:
            # 按住 ⌥⌘ 且无其他修饰键干扰时精确匹配（包含 cmd+opt 即可，宽松处理）
            if (Quartz.CGEventGetFlags(event) & _HOTKEY_FLAGS) == _HOTKEY_FLAGS:
                keycode = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode)
                if keycode == KEY_B:
                    print("[PeaseBar] 快捷键 ⌥⌘B 触发")
                    _dispatcher.defer_(toggle)  # 只投递，不在 tap 回调里干活
                elif keycode == KEY_S and on_settings is not None:
                    print("[PeaseBar] 快捷键 ⌥⌘S 触发")
                    _dispatcher.defer_(on_settings)
        except Exception:
            import traceback

            traceback.print_exc()
        return event  # listen-only：原样放行

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        mask,
        _cb,
        None,
    )
    if tap is None:
        print("[PeaseBar] 警告：CGEventTap 创建失败，⌥⌘B 快捷键不可用")
        return lambda: None

    from CoreFoundation import (  # noqa: PLC0415  # PyObjC Cocoa 框架自带
        CFRunLoopAddSource,
        CFRunLoopGetCurrent,
        kCFRunLoopCommonModes,
    )

    src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    print("[PeaseBar] 全局快捷键 ⌥⌘B（切换面板）/ ⌥⌘S（设置）已注册")

    def uninstall():
        Quartz.CGEventTapEnable(tap, False)

    return uninstall
