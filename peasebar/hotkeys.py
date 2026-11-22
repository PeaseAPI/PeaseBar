#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局快捷键（F6）：⌥⌘B 切换救援面板。

方案取舍（实测，见 docs/DEVELOPMENT.md §5）：
- Carbon.HIToolbox 不可用（PyObjC 不带 Carbon 绑定，ModuleNotFoundError）；
- NSEvent 全局键盘监听需要「输入监控」新授权（不想再让用户授权一项）；
- CGEventTap 只依赖辅助功能权限（T16 已授权），listen-only 模式不拦截/修改事件，
  ⌥⌘B 照常送达前台 App；kCGSessionEventTap 级别对本用户会话全键盘生效。

回调由挂到主 runloop 的 CFRunLoopSource 驱动，与 UI 同线程，直接调 toggle 安全。
"""
import Quartz


KEY_B = 11  # kVK_ANSI_B
_HOTKEY_FLAGS = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskAlternate


def install(toggle):
    """注册 ⌥⌘B 监听，返回卸载函数；tap 创建失败时返回 no-op 并打日志。"""
    mask = 1 << Quartz.kCGEventKeyDown

    def _cb(_proxy, _etype, event, _refcon):
        try:
            # 按住 ⌥⌘ 且无其他修饰键干扰时精确匹配（包含 cmd+opt 即可，宽松处理）
            if (Quartz.CGEventGetFlags(event) & _HOTKEY_FLAGS) == _HOTKEY_FLAGS:
                keycode = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode)
                if keycode == KEY_B:
                    print("[PeaseBar] 快捷键 ⌥⌘B 触发")
                    toggle()
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
    print("[PeaseBar] 全局快捷键 ⌥⌘B 已注册（切换救援面板）")

    def uninstall():
        Quartz.CGEventTapEnable(tap, False)

    return uninstall
