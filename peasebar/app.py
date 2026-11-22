#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PeaseBar 应用骨架：生命周期、单实例、权限引导、模块装配。

启动顺序（实测教训：状态项必须尽早建；模态弹窗会阻塞启动）：
1. 单实例检查（重复启动则唤醒已有实例后退出）
2. Accessory 应用 + 控制图标（图标显示不需要辅助功能权限，必须先建——
   否则错过系统「菜单栏 → 允许在菜单栏显示」的自动注册时机）
3. 辅助功能权限检查：非阻塞，缺失时仅日志提示（完整引导在菜单项/Phase 1 通知）
4. （Phase 1）盘点引擎 / 救援面板
"""
import socket
import sys

import ApplicationServices as AS
from AppKit import (
    NSApplication,
    NSAlert,
    NSApplicationActivationPolicyAccessory,
    NSStatusBar,
    NSWorkspace,
)
from Foundation import NSObject, NSURL

from peasebar import __version__
from peasebar.control_item import ControlItem

# 单实例哨兵端口（仅本机回环，无安全边界，只用于判重）
INSTANCE_PORT = 52877


def check_single_instance():
    """返回哨兵 socket（本进程是首个实例）或 None（已有实例，已通知其唤醒）。"""
    try:
        # 先尝试连接：能连上说明已有实例在跑
        probe = socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=0.3)
        probe.sendall(b"activate\n")
        probe.close()
        return None
    except OSError:
        pass
    # 连不上说明没人监听：本进程占坑
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", INSTANCE_PORT))
    srv.listen(2)
    srv.setblocking(False)
    return srv


def ensure_accessibility(interactive=False):
    """检查辅助功能权限；缺失且 interactive 时弹窗引导到系统设置。返回是否已授权。"""
    if AS.AXIsProcessTrusted():
        return True
    if interactive:
        alert = NSAlert.alloc().init()
        alert.setMessageText_("需要辅助功能权限")
        alert.setInformativeText_(
            "PeaseBar 需要读取菜单栏图标（辅助功能权限）才能工作。\n"
            "请在「系统设置 → 隐私与安全性 → 辅助功能」中允许 PeaseBar（或运行它的终端），\n"
            "然后重新启动 PeaseBar。"
        )
        alert.addButtonWithTitle_("打开系统设置")
        alert.addButtonWithTitle_("稍后再说")
        choice = alert.runModal()
        if choice == 1000:  # 第一个按钮
            url = NSURL.URLWithString_(
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
            NSWorkspace.sharedWorkspace().openURL_(url)
    return False


def _alert(title, text):
    """弹一个简单提示框。"""
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(text)
    alert.runModal()


class AppDelegate(NSObject):
    """应用委托：装配控制图标与后续功能栈。"""

    def applicationDidFinishLaunching_(self, notification):
        print(f"[PeaseBar {__version__}] 启动")
        self.control = ControlItem.alloc().initWithCallbacks_(self.on_left_click)
        self.control.build()
        # 单实例唤醒监听（收到 connect 即把控制图标闪烁提示一下；Phase 1 改为弹出面板）
        self.instance_socket = getattr(AppDelegate, "_sentinel", None)
        print("[PeaseBar] 控制图标就绪（左键面板将在 Phase 1 接入）")

    def on_left_click(self):
        """左键：Phase 1 由救援面板接管。"""
        print("[PeaseBar] 左键点击（面板占位）")

    def applicationShouldTerminate_(self, sender):
        # 退出前归还状态项
        item = getattr(self.control, "item", None)
        if item is not None:
            NSStatusBar.systemStatusBar().removeStatusItem_(item)
        return 1  # NSTerminateNow


def main():
    # 1) 单实例
    sentinel = check_single_instance()
    if sentinel is None:
        print("[PeaseBar] 已有实例在运行，已通知其唤醒")
        sys.exit(0)
    AppDelegate._sentinel = sentinel

    # 2) Accessory 应用（状态项在 applicationDidFinishLaunching 里创建，
    #    必须在事件循环前就绪；图标显示不依赖辅助功能权限）
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)

    # 3) 权限检查：非阻塞。缺失不弹窗（模态弹窗会阻塞事件循环、状态项无法创建），
    #    授权引导由菜单「检查辅助功能权限」承担
    if not AS.AXIsProcessTrusted():
        print("[PeaseBar] 警告：缺少辅助功能权限（盘点功能受限），可在菜单中引导授权")

    # 4) 事件循环
    print("[PeaseBar] 事件循环开始")
    app.run()


if __name__ == "__main__":
    main()
