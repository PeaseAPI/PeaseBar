#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""救援面板（F3）：PeaseBar 的核心 UI。

交互（验收标准见 docs/DEVELOPMENT.md F3）：
- 左键控制图标 → 面板出现在控制图标正下方（居中锚定）；
- 网格展示全部可见图标：名称 + 归属 + 刘海遮挡徽标「▨」；
- 单击面板内图标 → 对真实图标合成右键（弹出其原生状态菜单，T17），面板随即收起；
- 「展开/收起收纳区」按钮联动原生收纳按钮（F12 提前接入，核心场景：
  被刘海遮挡/被收纳的图标从这里找回——展开后再点图标即可弹出菜单）；
- 失焦自动收回（windowDidResignKey）。

实现要点：
- borderless NSPanel 默认不能成为 key 窗口，用 KeyPanel 子类放开 canBecomeKey；
- 失焦收回依赖面板成为 key（Nonactivating 样式收不到 resign，故不用）；
- 坐标转换：控制图标 frame 是全局 CG 坐标（左上原点），面板定位前转 AppKit。
"""
from AppKit import (
    NSApp,
    NSButton,
    NSColor,
    NSEvent,
    NSEventMaskLeftMouseDown,
    NSFont,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSTextField,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialPopover,
    NSVisualEffectView,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSObject, NSMakePoint
import objc
import Quartz

from peasebar import inventory

# 面板几何
PANEL_WIDTH = 468
GRID_COLS = 4
CELL_W, CELL_H = 110, 42
CELL_GAP = 6
EDGE = 8
HEADER_H = 26
FOOTER_H = 36

# 刘海遮挡徽标（置于名称前）
NOTCH_BADGE = "\u25a8 "  # ▨


class KeyPanel(NSPanel):
    """允许成为 key 的无边框面板（否则收不到失焦事件）。"""

    def canBecomeKey(self):
        return True


def _truncate(text, limit=12):
    return text if len(text) <= limit else text[: limit - 1] + "…"


class RescuePanel(NSObject):
    """救援面板控制器：持有 NSPanel，负责构建网格、弹出与收回。"""

    def initWithAnchor_(self, anchor_provider):
        """anchor_provider：返回控制图标按钮的屏幕坐标 AppKit frame (x, y, w, h)。"""
        # PyObjC 13.0：super().init()/super(C, self).init() 均抛 AttributeError，必须用 objc.super
        self = objc.super(RescuePanel, self).init()
        if self is None:
            return None
        self.anchor_provider = anchor_provider
        self.items = []
        self.panel = None
        self._monitor = None  # 全局鼠标按下监听（失焦收回，不依赖 key 状态）
        return self

    # ---------- 对外接口 ----------

    def toggle(self):
        """左键入口：面板开着就关，关着就开。"""
        if self.panel is not None and self.panel.isVisible():
            print("[PeaseBar] toggle: 面板开着 → 关闭")
            self.close()
        else:
            print("[PeaseBar] toggle: 面板关着 → 打开")
            self.show()

    def show(self):
        """盘点 → 建网格 → 定位在控制图标正下方 → 显示。"""
        print("[PeaseBar] 面板 show 开始")
        try:
            self._rebuild()
            print(f"[PeaseBar] 网格完成，frame={self.panel.frame()}")
            self.panel.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            # 失焦收回（F5）：合成事件场景 App 激活是半吊子状态（isActive=False，
            # key 永远 False），resignKey 路线不可靠；改用全局鼠标按下监听：
            # 点击面板外即收回。本 app 自身的事件（状态图标 toggle、面板内点击）
            # 不会进 global monitor，由各自逻辑处理，互不干扰
            if self._monitor is None:
                self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    NSEventMaskLeftMouseDown, self._outsideClick_)
            print(f"[PeaseBar] 面板已显示：visible={self.panel.isVisible()}，"
                  f"key={self.panel.isKeyWindow()}，active={NSApp.isActive()}")
        except Exception:
            import traceback
            traceback.print_exc()

    def close(self):
        print("[PeaseBar] close 调用")
        if self._monitor is not None:
            NSEvent.removeMonitor_(self._monitor)
            self._monitor = None
        if self.panel is not None:
            self.panel.orderOut_(None)

    # ---------- 内部：面板与网格 ----------

    def _ensure_panel(self, height):
        """懒创建面板（高度随内容变化时重建 frame）。"""
        if self.panel is None:
            panel = KeyPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, PANEL_WIDTH, height),
                NSWindowStyleMaskBorderless,
                2,  # backing buffered
                False,
            )
            panel.setLevel_(25)  # 与菜单栏同层（statusBar level），弹在其下方
            # NSPanel 的 hidesOnDeactivate 默认 YES：App 失活时系统会把面板藏起，
            # 但不翻转 isVisible()、不触发 resignKey，使 toggle 状态机错乱。
            # 关掉它，失焦收回完全交给 windowDidResignKey（F5）
            panel.setHidesOnDeactivate_(False)
            panel.setOpaque_(False)
            panel.setBackgroundColor_(NSColor.clearColor())
            panel.setHasShadow_(True)
            panel.setReleasedWhenClosed_(False)
            panel.setDelegate_(self)
            self.panel = panel
        else:
            # 复用已存在的面板（NSWindow 没有 setFrame: 选择子，只有 setFrame:display:，
            # PyObjC 对应 setFrame_display_；直接调 setFrame_ 会 AttributeError）
            f = self.panel.frame()
            self.panel.setFrame_display_(
                NSMakeRect(f.origin.x, f.origin.y, PANEL_WIDTH, height), True)
        return self.panel

    def _rebuild(self):
        """盘点并重建面板内容（每次弹出/刷新调用）。"""
        # 收纳按钮不在网格重复出现（底部有专用按钮）；其余全量展示
        all_items, _ = inventory.list_items()
        self.items = [m for m in all_items if not m.is_stash_button]
        notched = sum(1 for m in self.items if m.notched)
        print(f"[PeaseBar] 盘点完成：总 {len(all_items)} 项，网格 {len(self.items)} 项，刘海 {notched} 项")

        rows = (len(self.items) + GRID_COLS - 1) // GRID_COLS
        height = EDGE + HEADER_H + rows * (CELL_H + CELL_GAP) + FOOTER_H + EDGE

        panel = self._ensure_panel(height)

        # 内容视图：毛玻璃背景 + 手动布局
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_WIDTH, height))
        blur = NSVisualEffectView.alloc().initWithFrame_(content.frame())
        blur.setMaterial_(NSVisualEffectMaterialPopover)
        blur.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        blur.setState_(1)  # active
        blur.setWantsLayer_(True)
        blur.layer().setCornerRadius_(12)
        content.addSubview_(blur)

        # 头部标题
        header = NSTextField.labelWithString_(
            f"菜单栏救援 · 共 {len(self.items)} 项 · 刘海遮挡 {notched} 项"
        )
        header.setFont_(NSFont.boldSystemFontOfSize_(12))
        header.setFrame_(NSMakeRect(EDGE, height - HEADER_H, PANEL_WIDTH - 2 * EDGE, HEADER_H))
        content.addSubview_(header)

        # 图标网格（从顶部往下排；AppKit y 轴向上，先算每行顶部 y）
        grid_top = height - HEADER_H
        for idx, item in enumerate(self.items):
            row, col = divmod(idx, GRID_COLS)
            x = EDGE + col * (CELL_W + CELL_GAP)
            y = grid_top - HEADER_H - CELL_H - row * (CELL_H + CELL_GAP)
            badge = NOTCH_BADGE if item.notched else ""
            owner = "系统" if item.owner_app == "系统" else item.owner_app
            title = f"{badge}{_truncate(item.label)}\n{_truncate(owner, 16)}"
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, CELL_W, CELL_H))
            btn.setTitle_(title)
            btn.setBezelStyle_(0)  # rounded
            btn.setUsesSingleLineMode_(False)
            btn.setImagePosition_(2)  # NSNoImage：只显示文字（标题含两行）
            btn.setFont_(NSFont.systemFontOfSize_(10))
            btn.setTag_(idx)
            btn.setToolTip_(f"{owner}（{item.owner_bundle_id}）\n点击弹出该图标的原生菜单")
            btn.setTarget_(self)
            btn.setAction_("onIconClick:")
            content.addSubview_(btn)

        # 底部操作行
        footer_y = EDGE
        stash_open = inventory.stash_revealed()
        stash_label = "收起收纳区" if stash_open else "展开收纳区"
        self.btn_stash = NSButton.alloc().initWithFrame_(
            NSMakeRect(EDGE, footer_y, 130, 24))
        self.btn_stash.setTitle_(stash_label)
        self.btn_stash.setBezelStyle_(0)
        self.btn_stash.setFont_(NSFont.systemFontOfSize_(11))
        self.btn_stash.setTarget_(self)
        self.btn_stash.setAction_("onStashClick:")
        content.addSubview_(self.btn_stash)

        btn_refresh = NSButton.alloc().initWithFrame_(
            NSMakeRect(EDGE + 138, footer_y, 76, 24))
        btn_refresh.setTitle_("刷新")
        btn_refresh.setBezelStyle_(0)
        btn_refresh.setFont_(NSFont.systemFontOfSize_(11))
        btn_refresh.setTarget_(self)
        btn_refresh.setAction_("onRefreshClick:")
        content.addSubview_(btn_refresh)

        hint = NSTextField.labelWithString_("点击图标 = 弹出它的原生菜单")
        hint.setFont_(NSFont.systemFontOfSize_(10))
        hint.setTextColor_(NSColor.secondaryLabelColor())
        hint.setAlignment_(2)  # 右对齐
        hint.setFrame_(NSMakeRect(PANEL_WIDTH - 240, footer_y + 4, 232, 18))
        content.addSubview_(hint)

        panel.setContentView_(content)
        self._position_panel(height)

    def _position_panel(self, height):
        """面板定位：控制图标 AppKit frame，水平居中锚定在图标正下方 4pt。"""
        anchor = self.anchor_provider() if self.anchor_provider else None
        print(f"[PeaseBar] 面板定位：anchor={anchor}，height={height}")
        screen = NSScreen.mainScreen()
        if anchor is None or screen is None:
            self.panel.center()
            return
        ax, ay, aw, ah = anchor  # AppKit 屏幕坐标（左下原点）；菜单栏在屏幕顶部，ay 即按钮底边/菜单栏下缘
        x = ax + aw / 2 - PANEL_WIDTH / 2
        sframe = screen.frame()
        x = max(sframe.origin.x + 8,
                min(x, sframe.origin.x + sframe.size.width - PANEL_WIDTH - 8))
        y = ay - height - 4  # 面板顶边贴按钮底边下方 4pt（AppKit y 向上，origin 是左下角）
        self.panel.setFrameOrigin_(NSMakePoint(x, y))

    # ---------- 动作 ----------

    def onIconClick_(self, sender):
        """点击面板内图标：对真实图标合成右键（弹其状态菜单），面板收起。

        实测（T7，macOS 27）：AXPress 只会激活 App 不弹菜单（QQ 左键语义=开主窗口）；
        合成左键也触发不了标准 NSStatusItem 菜单追踪；**右键是最通用的菜单触发**
        （QQ/微信实测弹状态菜单）。frame 是全局 CG 坐标，CGEvent 同坐标系直用。
        """
        idx = sender.tag()
        if 0 <= idx < len(self.items):
            item = self.items[idx]
            if item.frame is not None:
                fx, fy, fw, fh = item.frame
                cx, cy = fx + fw / 2, fy + fh / 2
                move = Quartz.CGEventCreateMouseEvent(
                    None, Quartz.kCGEventMouseMoved, (cx, cy), Quartz.kCGMouseButtonRight)
                down = Quartz.CGEventCreateMouseEvent(
                    None, Quartz.kCGEventRightMouseDown, (cx, cy), Quartz.kCGMouseButtonRight)
                up = Quartz.CGEventCreateMouseEvent(
                    None, Quartz.kCGEventRightMouseUp, (cx, cy), Quartz.kCGMouseButtonRight)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, move)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
        self.close()

    def onStashClick_(self, sender):
        """展开/收起系统收纳区，然后刷新网格。"""
        inventory.set_stash_revealed(not inventory.stash_revealed())
        self._rebuild()
        self.panel.makeKeyAndOrderFront_(None)

    def onRefreshClick_(self, sender):
        """手动刷新盘点。"""
        self._rebuild()
        self.panel.makeKeyAndOrderFront_(None)

    # ---------- 失焦收回（F5） ----------

    def _outsideClick_(self, event):
        """全局监听回调：面板外左键按下 → 收回。NSEvent.mouseLocation 是屏幕
        AppKit 坐标（左下原点），与 panel.frame() 同坐标系可直接比较。"""
        if self.panel is None or not self.panel.isVisible():
            return
        loc = NSEvent.mouseLocation()
        f = self.panel.frame()
        if (f.origin.x <= loc.x <= f.origin.x + f.size.width
                and f.origin.y <= loc.y <= f.origin.y + f.size.height):
            return  # 面板内点击：交给面板自身控件
        # 控制图标点击：交给 toggle 处理。实测 App 未激活时 global monitor
        # 也会收到状态图标的点击（它不在「本 app 事件」流里），不忽略会与
        # toggle 双火（刚开就被收回，状态机错乱）
        if self.anchor_provider is not None:
            anchor = self.anchor_provider()
            if anchor is not None:
                ax, ay, aw, ah = anchor
                if (ax - 2 <= loc.x <= ax + aw + 2
                        and ay - 2 <= loc.y <= ay + ah + 2):
                    return
        print(f"[PeaseBar] 全局监听：面板外点击 ({loc.x:.0f},{loc.y:.0f}) → 收回")
        self.close()

    def windowDidResignKey_(self, notification):
        print("[PeaseBar] windowDidResignKey → 收回面板")
        self.close()
