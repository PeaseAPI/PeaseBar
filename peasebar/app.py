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
from Foundation import (NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer, NSURL)

from peasebar import __version__, hotkeys, sections
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
    """检查辅助功能权限；缺失时用带提示的 API 让系统按**当前签名**重新登记并弹授权框。

    为什么要用 AXIsProcessTrustedWithOptions(kAXTrustedCheckOptionPrompt) 而不是光 AXIsProcessTrusted：
    ad-hoc 包反复重建/重装后，系统「辅助功能」列表里那条绿色开关常绑到旧的 cdhash，
    普通检查会一直假阴（开关是绿的但读不到菜单栏）。带提示的调用会按当前二进制重新登记一条
    干净条目并弹系统授权框，勾上后才对得上。返回是否已授权。
    """
    if AS.AXIsProcessTrusted():
        return True
    # 关键：让系统按当前 cdhash 重新登记条目并弹「允许控制此电脑」授权框（幂等，已授权不再弹）
    try:
        prompt = getattr(AS, "kAXTrustedCheckOptionPrompt", None)
        if prompt is not None:
            AS.AXIsProcessTrustedWithOptions({prompt: True})
    except Exception as exc:  # noqa: BLE001 — 提示失败不致命，仍走下面的引导
        print(f"[PeaseBar] 触发辅助功能授权提示失败：{exc}")
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


def install_mouse_debug():
    """诊断开关：存在 ~/Library/Application Support/PeaseBar/debug_mouse 时，
    把本会话所有鼠标按下事件打进日志（含目标窗口号）。

    用途：判断“点击状态项无反应”到底是事件没进本进程，还是进了但没命中按钮。
    取证脚本创建/删除该文件即可开关，不需要改代码重构建。"""
    import os

    flag = os.path.expanduser("~/Library/Application Support/PeaseBar/debug_mouse")
    if not os.path.exists(flag):
        return False
    from AppKit import NSEvent

    # 事件类型→掩码用位移（NSEvent.typeMaskForEvent: 在 PyObjC 暴露中不存在，
    # 误用会抛 AttributeError 直接掉断 didFinishLaunching）：1=leftDown 3=rightDown
    masks = (1 << 1) | (1 << 3)

    def _log(tag, event):
        win = event.window()
        num = getattr(win, "windowNumber", lambda: -1)() if win is not None else None
        print(f"[PeaseBar][mouse] {tag} type={event.type()} loc={event.locationInWindow()} "
              f"screen={NSEvent.mouseLocation()} win#{num} class="
              f"{type(win).__name__ if win is not None else 'None'}")

    NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
        masks, lambda event: (_log("本地", event), event)[1])
    NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
        masks, lambda event: _log("全局", event))
    print("[PeaseBar][mouse] 鼠标诊断已开启（debug_mouse 标记文件存在）")
    return True


class AppDelegate(NSObject):
    """应用委托：装配控制图标与后续功能栈。"""

    def applicationDidFinishLaunching_(self, notification):
        print(f"[PeaseBar {__version__}] 启动")
        # 装配整段护身：PyObjC 建类失败（如 BadPrototypeError）只会在 os_log 里响，
        # 日志里只看到「启动」后一片空白，极难定位；这里统一接住并打到日志文件
        try:
            self._wire_up()
        except Exception:
            import traceback

            print("[PeaseBar] 启动装配失败（面板/快捷键/设置均不可用）：")
            traceback.print_exc()
            # print 进 launchd 不可见，落盘一份才能离线定位（与 reconcile 同做法）
            try:
                import os
                with open(os.path.expanduser(
                        "~/Project/PeaseBar/tmp/wireup_error.txt"),
                        "w", encoding="utf-8") as f:
                    traceback.print_exc(file=f)
            except Exception:  # noqa: BLE001
                pass

    def _wire_up(self):
        """真正的装配：控制图标 → 救援面板 → 设置窗口 → 快捷键 → 单实例监听。"""
        self.control = ControlItem.alloc().initWithCallbacks_(lambda: None)
        # 注：状态项必须尽早创建（错过系统自动注册时机图标不显示），
        #     因此先建图标再接线面板/设置（build 在下文）
        # 救援面板（F3）：左键控制图标弹出；锚点 = 控制图标按钮屏幕坐标
        from peasebar.panel import RescuePanel

        self.rescue = RescuePanel.alloc().initWithAnchor_(self.control.button_anchor)
        self.control.on_left = self.rescue.toggle
        self.control.on_stash = self.rescue.toggle_stash  # 收纳开关：面板瘦身后进右键菜单
        # 设置窗口（分区编辑的唯一入口，参照 Thaw：编辑在设置里而非弹窗里）
        from peasebar.settings import SettingsController

        self.settings = SettingsController.alloc().init()
        self.settings.on_changed = self._refresh_panel_if_open
        self.settings.on_control_icon_changed = self.control.refresh_icon  # 触发图标预设即时重画
        self.control.on_settings = self.settings.show
        self.control.build()
        try:
            install_mouse_debug()
        except Exception:
            import traceback

            traceback.print_exc()  # 诊断代码绝不能再次掉断启动
        # 全局快捷键（F6）：⌥⌘B 切换面板，⌥⌘S 开设置（CGEventTap，只需辅助功能权限，T23）
        # 诊断：标记文件 debug_no_hotkey 存在时不装 tap（T38：排除 tap 干扰点击投递）
        import os

        if os.path.exists(os.path.expanduser(
                "~/Library/Application Support/PeaseBar/debug_no_hotkey")):
            print("[PeaseBar][诊断] 已跳过快捷键 tap（debug_no_hotkey）")
            self._uninstall_hotkey = lambda: None
        else:
            self._uninstall_hotkey = hotkeys.install(self.rescue.toggle, self.settings.show)
        # 单实例唤醒（F10）：哨兵 socket 收到二次启动的 connect → 弹出救援面板。
        # 非阻塞轮询（0.5s NSTimer），accept 空转开销可忽略，主线程安全
        self.instance_socket = getattr(AppDelegate, "_sentinel", None)
        if self.instance_socket is not None:
            timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                0.5, self, "pollInstanceSocket:", None, True)
            NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
            print("[PeaseBar] 单实例唤醒监听就绪（哨兵端口 52877，0.5s 轮询）")
        print("[PeaseBar] 控制图标与救援面板就绪（左键图标/⌥⌘B 弹出，点击图标可弹其原生菜单）")
        # 预热快照（T98）：后台采一次，第一次点开面板也能秒出
        self.rescue.prewarm()
        # 启动同步（用户痛点「设为弹窗显示的图标还在菜单栏」）：把上次保存的分区
        # 一次性镜像回真实菜单栏（后台线程、稍延，等状态项摆稳且有辅助功能权限）。
        self.settings.reconcile_real_bar_async()
        # 周期核对（60s）：App 断线重连重建图标/系统重写记录会让隐藏悄悄失效
        # （真机实证：Synology Drive Client 隐藏后重现）。无漂移时幂等零动作
        # （不写盘、不重启 Agent、菜单栏不闪），有漂移才在后台收回来。
        # 显隐规则页的「每分钟自动核对显隐」开关控制它（关掉则不挂，设置窗里
        # 再开时由 _apply_cc_tick 重挂并写回 self.settings.tick_timer）。
        if sections.get_pref(sections.load_config(), "cc_tick_enabled") is False:
            print("[PeaseBar] CC 自动核对：已按配置停用（显隐规则页可重新开启）")
        else:
            tick = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                60.0, self.settings, "syncCCTick:", None, True)
            NSRunLoop.mainRunLoop().addTimer_forMode_(tick, NSRunLoopCommonModes)
            self.settings.tick_timer = tick
            print("[PeaseBar] CC 周期核对已挂（60s，无漂移零动作）")

    def _refresh_panel_if_open(self):
        """设置变更后：作废位图缓存并刷新面板（重活在后台，不卡设置窗）。"""
        self.rescue.refresh_now()

    def pollInstanceSocket_(self, timer):
        """哨兵 socket 轮询：收到二次启动的 connect 即弹出救援面板（F10）。"""
        srv = self.instance_socket
        if srv is None:
            return
        try:
            conn, _ = srv.accept()
        except (BlockingIOError, OSError):
            return
        try:
            conn.recv(64)  # 内容不关心，读掉即可
        except OSError:
            pass
        finally:
            conn.close()
        print("[PeaseBar] 收到二次启动唤醒 → 弹出救援面板")
        self.rescue.show()

    def applicationShouldTerminate_(self, sender):
        # 退出前归还状态项 + 摘除快捷键 tap
        if getattr(self, "_uninstall_hotkey", None) is not None:
            self._uninstall_hotkey()
        item = getattr(self.control, "item", None)
        if item is not None:
            NSStatusBar.systemStatusBar().removeStatusItem_(item)
        return 1  # NSTerminateNow


def main():
    # 0) 日志落盘：open/LaunchServices 启动时 stdout/stderr 不可见（/dev/null），
    #    排障必须先把异常引导到文件（~/Library/Logs/PeaseBar.log，追加、行缓冲）。
    #    encoding 必须显式 UTF-8：open 环境无 LANG/LC_*，默认 locale 编码是 ASCII，
    #    写中文日志直接 UnicodeEncodeError（且崩在 app.run() 之前，状态项永远不出现）
    import os
    logf = open(os.path.expanduser("~/Library/Logs/PeaseBar.log"), "a",
                buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = logf
    sys.stderr = logf

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

    # 3) 权限检查：非阻塞。缺失时调 ensure_accessibility(interactive=False)——它只走
    #    系统自带的授权提示（AXIsProcessTrustedWithOptions，异步、不阻塞事件循环），
    #    不弹我们自己的模态 NSAlert（模态会卡住 didFinishLaunching、状态项建不出来）。
    if not AS.AXIsProcessTrusted():
        ensure_accessibility(interactive=False)
        print("[PeaseBar] 警告：缺少辅助功能权限（盘点功能受限），按提示勾选后重启一次")

    # 4) 事件循环
    print("[PeaseBar] 事件循环开始")
    app.run()


if __name__ == "__main__":
    main()
