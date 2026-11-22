#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""控制图标（Control Item）：PeaseBar 在菜单栏上的常驻图标。

职责：
- 常驻 NSStatusItem，SF Symbol 图标自动适配深浅色（template）；
- 左键 → 回调 on_left（Phase 1 接救援面板）；
- 右键 → 弹出主菜单（挂临时菜单的经典方案，避免左键也弹菜单）；
- 用户可以用系统手势拖动它改变位置，PeaseBar 不干预。
"""
from AppKit import (
    NSStatusBar,
    NSVariableStatusItemLength,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSApp,
    NSAlert,
)
from Foundation import NSObject, NSMakeRect
import objc
import peasebar
from peasebar import sections

# 点击分发需要按下即触发（而非抬起），沿用 NSCell 的 sendActionOn_
try:
    from AppKit import NSEventMaskLeftMouseDown, NSEventMaskRightMouseDown
    CLICK_MASKS = NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown
except ImportError:  # 旧版常量名兜底
    CLICK_MASKS = (1 << 1) | (1 << 3)

from AppKit import (
    NSEventTypeLeftMouseDown,
    NSEventTypeRightMouseDown,
)

# 控制图标默认符号（预设表见 sections.CONTROL_ICONS，用户可在设置→通用页换）；
# 找不到符号时退化为文字「···」
SYMBOL_NAME = sections.CONTROL_ICONS[0][0]
FALLBACK_TITLE = "···"


class ControlItem(NSObject):
    """封装 NSStatusItem 与左右键分发。"""

    def initWithCallbacks_(self, on_left):
        """on_left：左键回调（无参，Phase 1 由救援面板提供）。"""
        # PyObjC 13.0：super().init()/super(C, self).init() 均抛 AttributeError，必须用 objc.super
        self = objc.super(ControlItem, self).init()
        if self is None:
            return None
        self.on_left = on_left
        self.on_settings = None  # 打开设置窗口的回调（app.py 接线，F14）
        self.on_stash = None  # 展开/收起收纳区的回调（app.py 接线，F12；面板瘦身后来到的位置）
        self.menu = None
        return self

    def build(self):
        """创建状态图标与主菜单（中文优先）。"""
        bar = NSStatusBar.systemStatusBar()
        self.item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        button = self.item.button()
        self.refresh_icon()  # 按配置画触发图标（图标/文字分支在 refresh_icon 里统一）
        button.setToolTip_("PeaseBar：查看全部菜单栏图标")

        # 主菜单（右键用；左键行为由回调接管）
        self.menu = NSMenu.alloc().initWithTitle_("PeaseBar")
        mi_settings = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "设置…", "openSettings:", "")
        # 收纳区开关：救援面板瘦身（照 Thaw 只留纯网格）后，按钮移到这里
        mi_stash = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "展开收纳区", "toggleStash:", "")
        mi_about = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "关于 PeaseBar", "showAbout:", "")
        mi_perms = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "检查辅助功能权限", "checkPermission:", "")
        mi_quit = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "退出 PeaseBar", "terminate:", "q")
        for mi in (mi_settings, mi_stash, mi_about, mi_perms, mi_quit):
            # 必须 setTarget_：nil-targeted action 沿响应链查找，而 ControlItem
            # 不在响应链里，点击菜单项后 action 会落空（实测 T14 首败根因）
            mi.setTarget_(self)
            self.menu.addItem_(mi)
        self.menu.insertItem_atIndex_(NSMenuItem.separatorItem(), 2)
        self.mi_stash = mi_stash  # 右键弹前按实时状态刷新标题，留强引用

        # 按下即回调（左右键都进 on_click，再按事件类型分发）
        button.setTarget_(self)
        button.setAction_("onStatusClick:")
        button.sendActionOn_(CLICK_MASKS)
        return self

    def refresh_icon(self):
        """按配置重画触发图标（设置页改预设后即时生效，无需重启）。

        accessibilityDescription 会成为状态项的 AXDescription（盘点 label 的来源）：
        传 None 时回落 SF Symbol 系统默认描述（实测是「更多」），面板里自己的图标
        会显示成「更多」，用户看不懂；必须显式给出（P22 实测教训）。
        """
        symbol = sections.load_config().get("control_icon", SYMBOL_NAME)
        button = self.item.button()
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, "PeaseBar")
        if image is not None:
            image.setTemplate_(True)  # 随系统深浅色自动反色
            button.setImage_(image)
            button.setTitle_("")
        else:
            # 预设符号加载失败（系统没有该符号）：退回到文字三点，不留空白钮
            button.setImage_(None)
            button.setTitle_(FALLBACK_TITLE)
        return self

    def button_anchor(self):
        """控制图标按钮的屏幕坐标 AppKit frame (x, y, w, h)（救援面板锚点）。"""
        button = self.item.button()
        win = button.window()
        if win is None:
            return None
        # 按钮自身坐标系 → 窗口坐标系 → 屏幕坐标系（AppKit，左下原点）
        # PyObjC：NSView 的 convertRect:fromView: 是双参方法 convertRect_fromView_
        rect_in_win = button.convertRect_fromView_(button.bounds(), button)
        rect_in_screen = win.convertRectToScreen_(rect_in_win)
        return (rect_in_screen.origin.x, rect_in_screen.origin.y,
                rect_in_screen.size.width, rect_in_screen.size.height)

    def onStatusClick_(self, sender):
        """状态图标点击入口：按事件类型分发左右键。

        currentEvent 为 None 说明这次 action 不是鼠标点出来的，而是 AX 触发的
        （T54：救援面板对 MenuBarAgent 的托管按钮执行 AXPress，MenuBarAgent 经
        `addTarget:action:forControlEvents:` 转发「语义主点击」，路径上不带鼠标事件，
        也不转发右键）。这种必须当主点击处理，否则面板/设置都点不开。
        """
        event = NSApp.currentEvent()
        etype = event.type() if event is not None else None
        print(f"[PeaseBar] onStatusClick 触发，"
              f"currentEvent={'无（AX 触发）' if event is None else etype}，"
              f"on_left={'已接线' if self.on_left else '空'}")
        if etype == NSEventTypeRightMouseDown:
            self._popup_menu()
            return
        if self.on_left is not None:
            self.on_left()
        else:
            print("[PeaseBar] 警告：主点击回调未接线")

    def _popup_menu(self):
        """右键弹菜单：临时挂 NSMenu 到状态项，借 performClick 触发弹层。

        弹前按实时状态刷新「展开/收起收纳区」标题（一次 AX 往返，只在右键时发生）。"""
        from peasebar import inventory
        if getattr(self, "mi_stash", None) is not None:
            self.mi_stash.setTitle_(
                "收起收纳区" if inventory.stash_revealed() else "展开收纳区")
        self.item.setMenu_(self.menu)
        try:
            self.item.button().performClick_(None)
        finally:
            self.item.setMenu_(None)

    def openSettings_(self, sender):
        """菜单「设置…」：打开设置窗口（分区编辑在这里做，不在救援面板）。"""
        print("[PeaseBar] 菜单动作 openSettings 触发")
        if self.on_settings is not None:
            self.on_settings()
        else:
            print("[PeaseBar] 警告：on_settings 未接线")

    def toggleStash_(self, sender):
        """菜单「展开/收起收纳区」：联动原生收纳按钮（F12，面板瘦身后的入口）。"""
        print("[PeaseBar] 菜单动作 toggleStash 触发")
        if self.on_stash is not None:
            self.on_stash()
        else:
            print("[PeaseBar] 警告：on_stash 未接线")

    def showAbout_(self, sender):
        """关于窗口。"""
        from AppKit import NSAlert
        alert = NSAlert.alloc().init()
        alert.setMessageText_("PeaseBar")
        alert.setInformativeText_(
            "macOS 菜单栏图标管理器\n"
            "被刘海遮挡、被系统收纳的图标，都能从这里一键找回。\n"
            f"版本 {peasebar.__version__}（开发态）"
        )
        alert.runModal()

    def checkPermission_(self, sender):
        """手动触发权限检查并提示结果。"""
        print("[PeaseBar] 菜单动作 checkPermission 触发")
        from peasebar.app import ensure_accessibility, _alert
        if ensure_accessibility(interactive=True):
            _alert("PeaseBar 权限正常", "辅助功能权限已授予，功能完整可用。")

    def terminate_(self, sender):
        """退出应用（交给 NSApp 处理）。"""
        NSApp.terminate_(None)
