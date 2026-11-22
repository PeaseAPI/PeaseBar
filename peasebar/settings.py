#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置窗口（F11/F14 提前落地；Phase 4e 起为侧栏多页：布局/通用/快捷键/疑难解答/关于）。

参照 thaw@beta 3.0.0-beta.7 的分工：编辑放在**设置 → 布局页**（⌥方向键移动选中项、
⌘Z 撤销、每区按名称排序、重置布局，格子只有图标），救援面板只负责临时找回图标。
窗口是 NavigationSplitView 式侧栏 + 右侧页内容；通用页管开机自启（SMAppService，
写后回读系统状态为准）与面板超时；疑难解答页管权限/重抓/日志；关于页给版本与源码。

    控制图标右键 →「设置…」（或 ⌥⌘S）→ 侧栏选页（**图标只显示图标，名字进悬停提示**）

    单击图标 = 选中 → 底部按钮移区 / 前移后移改顺序；右键图标 = 移区菜单
    ⌥←/⌥→ = 同区内前后移一格（写 order）  ⌥↑/⌥↓ = 移到上/下一个区
    ←/→/↑/↓  = 只移动选中焦点            ⌘1/2/3 = 移到对应区   ⌘Z = 撤销

为什么两条路都留：实测本 App 里手动 `NSMenu.popUpContextMenu` 的菜单跟踪不可靠
（T41：action 进去了、菜单却没出现在屏幕上），而按钮路径 100% 可控可测；
右键菜单改用 `setMenu:`（T27：NSView 带菜单时系统自己弹），不再手写跟踪循环。

拖拽跨区（Thaw 的 LayoutBar 本体）暂缺：那是另一套 NSDraggingDestination 工程，
且与 Phase 3「把顺序写回真实菜单栏」的拖拽同源，等那边一起做。

另含维持性设置：面板自动收回秒数（F5，通用页）、图标位图重抓与权限入口（疑难解答页）。
"""
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSEventModifierFlagCommand,
    NSEventModifierFlagOption,
    NSFont,
    NSImageOnly,
    NSImageScaleProportionallyDown,
    NSLineBreakByTruncatingTail,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPasteboard,
    NSProcessInfo,
    NSPopUpButton,
    NSSwitch,
    NSText,
    NSTextField,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialSidebar,
    NSVisualEffectMaterialWindowBackground,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import NSObject, NSMakePoint, NSMakeSize, NSURL
from AppKit import NSApplication
import os
import platform

import objc
import Quartz
from ApplicationServices import AXIsProcessTrusted

import ServiceManagement as SM

from peasebar import capture, inventory, sections

# 方向键的 keyCode（AppKit 的 NS*ArrowFunctionKey 取值，写数字谁也看不懂）
KEY_LEFT, KEY_RIGHT, KEY_DOWN, KEY_UP = 123, 124, 125, 126

SIDEBAR_W = 150
CONTENT_W = 610
WIN_WIDTH = SIDEBAR_W + CONTENT_W
STATIC_H = 300
TILE_W, TILE_H = 44, 38
TILE_GAP = 4
EDGE = 16
ROW_H = 24
SECTION_H = 20
HEADER_H = 34
GAP = 12
# 布局页底部固定行数：选中提示 + 移区按钮 + 顺序按钮 + 重置行
BOTTOM_ROWS = 4
# 撤销栈深度（一次编辑只存两个小列表，50 步足够找回手滑，也不会吃掉多少内存）
UNDO_LIMIT = 50

# 区 → 移区菜单/按钮文案（三区语义对齐 Thaw：菜单栏显示 / 弹窗显示 / 永久隐藏）
_MOVE_TITLES = {
    sections.SECTION_VISIBLE: "回到菜单栏显示",
    sections.SECTION_HIDDEN: "移到弹窗显示",
    sections.SECTION_ALWAYS_HIDDEN: "移到永久隐藏",
}
_SECTION_ORDER = sections.SECTION_ORDER
_TAG_SECTIONS = {0: sections.SECTION_VISIBLE, 1: sections.SECTION_HIDDEN,
                 2: sections.SECTION_ALWAYS_HIDDEN}

# 侧栏页签（key, 显示名, 副标题）；key 也写进侧栏按钮的 AXIdentifier 供取证认页
PAGES = (("layout", "布局", "图标分区与顺序"),
         ("general", "通用", "开机自启与面板行为"),
         ("shortcuts", "快捷键", "全局快捷键"),
         ("troubleshoot", "疑难解答", "权限、图标抓取与诊断"),
         ("about", "关于", "版本与源码"))

LOG_PATH = os.path.expanduser("~/Library/Logs/PeaseBar.log")
REPO_URL = "https://github.com/PeaseAPI/PeaseBar"

# SMAppService 状态码 → (开关是否显示为已开, 给用户的说明)
_LOGIN_STATUS = {
    int(SM.SMAppServiceStatusNotRegistered): (False, "未开启：登录后不会自动启动"),
    int(SM.SMAppServiceStatusEnabled): (True, "已开启：登录时自动启动（系统已登记）"),
    int(SM.SMAppServiceStatusRequiresApproval): (
        True, "已登记，但需在「系统设置 → 通用 → 登录项」中允许"),
    int(SM.SMAppServiceStatusNotFound): (
        False, "系统未登记本 App 的启动服务（以开发方式运行时属正常现象）"),
}


class GridView(NSView):
    """布局页的页视图：只多干一件事 —— 接住键盘，把编辑动作交给控制器。

    Thaw 的布局编辑器靠 SwiftUI 的键盘命令，我们这里用 AppKit 最直接的路：
    内容视图做 firstResponder，`keyDown:` 里判修饰键。**没有选中项或控制器不认
    这根键时一律交回 super**（系统该响铃响铃、该走焦点环走焦点环），
    绝不吞键 —— 否则输入框、快捷键回退都会莫名其妙失效。
    """

    def acceptsFirstResponder(self):
        return True

    def keyDown_(self, event):
        ctrl = getattr(self, "settings_ctrl", None)
        if ctrl is None or not ctrl.handleKey_(event):
            objc.super(GridView, self).keyDown_(event)


class SettingsController(NSObject):
    """设置窗口的创建/刷新/单例持有。app.py 持有本对象强引用。"""

    def init(self):
        # PyObjC 13.0：NSObject 子类必须用 objc.super，普通 super().init() 会报 AttributeError
        self = objc.super(SettingsController, self).init()
        if self is None:
            return None
        self.window = None
        self.page = "layout"   # 当前设置页（侧栏切换；取证靠 AXIdentifier "page-<key>"）
        self.items = []
        self.images = {}
        self.stashed_count = 0    # 被系统收纳项数（提示行用，与盘点同源不二次枚举）
        self.notched_count = 0    # 被刘海遮挡项数
        self.stats = dict(capture.last_stats)  # 最近一次取图构成（真实像素/兜底）
        self.tiles = {}       # 配置键 → 格子按钮（选中态/反查用）
        self.selected_key = None  # 当前选中的图标（编辑动作的作用对象）
        self.buckets = {}     # 最近一次 _rebuild 的分桶结果（键盘编辑读它，不二次盘点）
        self._undo = []       # 撤销栈：每格是 {sections, order} 快照
        self.on_changed = None  # 分区/超时变更后回调（app 用来刷新面板）
        self.on_control_icon_changed = None  # 触发图标预设变更后回调（app 接 ControlItem.refresh_icon）
        return self

    # ---------- 打开与刷新 ----------

    def show(self):
        """打开或前置设置窗口，并重新盘点刷新内容。"""
        self._reload_items()
        if self.window is None:
            self._build_window()
        if not self.window.isVisible():
            # 关掉再打开时一律从布局页起步：分区编辑才是设置窗的主用途，
            # 也让回归探针「开窗就有格子」的假设不依赖上一次停在哪页
            self.page = "layout"
        self._rebuild()
        self.window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def close(self):
        if self.window is not None:
            self._save_timeout()
            self.window.orderOut_(None)

    def _reload_items(self):
        """盘点 + 取图（只读当前菜单栏状态，不再强制展开系统收纳区）。

        取证教训（T41/T43）：这里原先先 `set_stash_revealed(True)` 再盘点，
        展开收纳区会把第三方图标挤出 AXExtrasMenuBar（实测只剩 3～4 个系统图标），
        设置窗口因此突然「空掉」。现在保持现状盘点，收纳区交给面板按钮联动。
        """
        all_items, unavailable = inventory.list_items()
        self.items = [m for m in all_items if not m.is_stash_button]
        self.images, self.no_permission = capture.capture_icons(self.items)
        # 选中项可能已消失（App 退出），丢掉悬空引用
        if self.selected_key not in self.images:
            self.selected_key = None
        stashed = sum(1 for m in self.items if m.stashed)
        self.stashed_count = stashed
        self.notched_count = sum(1 for m in self.items if m.notched and not m.is_stash_button)
        self.stats = dict(capture.last_stats)
        print(f"[PeaseBar] 设置盘点：图标 {len(self.items)} 项（被系统收纳 {stashed} 项，"
              f"AX 不可用进程 {len(unavailable)} 个），图标位图 {len(self.images)} 张，"
              f"屏幕录制权限={'有' if not self.no_permission else '无（用兜底图标）'}")

    def _hints(self):
        """「挤不下 / 够不着」提示行（照 Thaw：这类信息放设置页，不在格子上打角标，T72）。

        只给计数与操作指引，不列名字——用户定调「UI 只显示图标」；名字仅在
        「已选：」行出现（那是用户主动选中后才有的上下文）。
        本机刘海是死区（T72），notched 通常为 0，该行因此不出现，但逻辑要支持。
        """
        hints = []
        if self.stashed_count:
            hints.append(f"有 {self.stashed_count} 项被系统收纳：菜单栏挤不下，"
                         f"可在面板「展开收纳区」找回，或选中后改为弹窗显示。")
        if self.notched_count:
            hints.append(f"有 {self.notched_count} 项被刘海遮挡：够不着，可改为弹窗显示腾位置。")
        # 有权限却一张真像素都没截到 = 菜单栏此刻没画出来（全屏 App 遮住）。
        # 不说清楚的话，用户只会看到一屏「不像本人」的 App 图标又找不到原因（T76）。
        if not self.stats["cropped"] and self.stats["permission"] and not self.stats["bar_drawn"]:
            hints.append("菜单栏当前没画出图标（多半被全屏应用遮住）：格子暂用 App 图标/系统符号，"
                         "退出全屏后点「重新抓取图标」恢复真实像素。")
        return hints

    # ---------- 窗口骨架 ----------

    def _build_window(self):
        rect = NSMakeRect(0, 0, WIN_WIDTH, 420)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable,
            NSBackingStoreBuffered,
            False)
        win.setTitle_("PeaseBar 设置 · 布局")  # 标题前缀不变，取证按「PeaseBar 设置」找窗
        win.setReleasedWhenClosed_(False)  # 关闭后仍复用（否则二次打开野指针）
        win.setDelegate_(self)  # 点红叉关闭时也把超时输入落盘
        win.center()
        self.window = win

    def windowWillClose_(self, notification):
        self._save_timeout()

    def _page_height(self, page, buckets):
        """各页内容高度：布局页随分桶行数变，静态页定高。"""
        if page != "layout":
            return STATIC_H
        cols = max(1, int((CONTENT_W - 2 * EDGE) // (TILE_W + TILE_GAP)))
        h = EDGE + HEADER_H
        for sec in _SECTION_ORDER:
            n = len(buckets[sec])
            if not n:
                continue
            rows = (n + cols - 1) // cols
            h += SECTION_H + rows * (TILE_H + TILE_GAP) + GAP
        h += (BOTTOM_ROWS + len(self._hints())) * (ROW_H + 8) + EDGE
        return int(h)

    def _rebuild(self):
        """整窗重建：侧栏 + 当前页内容。

        每页内容都是手排视图（与 4d 同源），切页/编辑都整窗重画一遍，
        不留旧控件残影，也就不需要页间显隐管理。
        """
        cfg = sections.load_config()
        buckets = sections.plan_sections(self.items, cfg)
        self.buckets = buckets  # 键盘编辑（⌥方向键/前移后移）就在这份分桶上动手
        self.tiles = {}
        self.move_buttons = []
        self.order_buttons = []
        self.field_timeout = None  # 切页即失效，_save_timeout 的空判据此生效
        self.popup_icon = None     # 同上：触发图标下拉也随旧内容丢弃
        page = getattr(self, "page", "layout")
        height = self._page_height(page, buckets)

        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WIN_WIDTH, height))
        blur = NSVisualEffectView.alloc().initWithFrame_(container.frame())
        blur.setMaterial_(NSVisualEffectMaterialWindowBackground)
        blur.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        blur.setState_(1)
        container.addSubview_(blur)
        self._build_sidebar(container, height, page)

        if page == "layout":
            page_view = self._build_layout_page(buckets, height)
        else:
            page_view = self._build_static_page(page, height)
        page_view.setFrameOrigin_(NSMakePoint(SIDEBAR_W, 0))
        container.addSubview_(page_view)

        label = next(l for k, l, _ in PAGES if k == page)
        self.window.setTitle_(f"PeaseBar 设置 · {label}")  # 前缀「PeaseBar 设置」不变，找窗判据不动
        self.window.setContentSize_(NSMakeSize(WIN_WIDTH, height))
        self.window.setContentView_(container)
        # 重建后旧 firstResponder 随内容视图丢弃：布局页要把焦点抢回页视图，方向键才不落空
        self.window.makeFirstResponder_(page_view if page == "layout" else container)
        self._sync_selection()

    def _build_sidebar(self, container, height, page):
        """左侧页签列：纯按钮 + 选中垫底（Thaw NavigationSplitView 的同款观感）。"""
        side = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, SIDEBAR_W, height))
        side.setMaterial_(NSVisualEffectMaterialSidebar)
        side.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        side.setState_(1)
        container.addSubview_(side)
        y = height - 12 - 30
        for key, name, _sub in PAGES:
            # 左缩进 14pt：文本贴边不好看（用户反馈），macOS 侧栏惯例约 16pt，
            # 选中垫底与文本同起点，视觉上是整块内缩
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(14, y, SIDEBAR_W - 28, 28))
            btn.setTitle_(name)
            btn.setBordered_(False)
            btn.setAlignment_(3)  # 左对齐（默认居中会像按钮组不像页签列）
            btn.setFont_(NSFont.boldSystemFontOfSize_(13) if key == page
                         else NSFont.systemFontOfSize_(13))
            # 故意不用 PushOnPushOff：那会把页签报成 AXCheckBox（T63），既挡住
            # 「按 AXButton 找页签」的取证，又和图标格子撞判据；选中态靠加粗+垫底表达
            btn.setWantsLayer_(True)
            btn.layer().setCornerRadius_(6.0)
            bg = (Quartz.CGColorCreateGenericRGB(1.0, 1.0, 1.0, 0.16) if key == page
                  else Quartz.CGColorCreateGenericRGB(0.0, 0.0, 0.0, 0.0))
            btn.layer().setBackgroundColor_(bg)
            btn.setTarget_(self)
            btn.setAction_("onPickPage:")
            btn.setRepresentedObject_(key)
            # 取证靠标识认页，不靠标题猜（标题日后可能本地化）
            btn.setAccessibilityIdentifier_("page-" + key)
            side.addSubview_(btn)
            y -= 32

    def _build_static_page(self, page, height):
        """非布局页：页名 + 副标题 + 各页 builder 排内容。"""
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, CONTENT_W, height))
        label, sub = next((l, s) for k, l, s in PAGES if k == page)
        t = NSTextField.labelWithString_(label)
        t.setFont_(NSFont.boldSystemFontOfSize_(15))
        t.setFrame_(NSMakeRect(EDGE, height - 34, CONTENT_W - 2 * EDGE, 24))
        view.addSubview_(t)
        s2 = NSTextField.labelWithString_(sub)
        s2.setFont_(NSFont.systemFontOfSize_(11))
        s2.setTextColor_(NSColor.secondaryLabelColor())
        s2.setFrame_(NSMakeRect(EDGE, height - 54, CONTENT_W - 2 * EDGE, 18))
        view.addSubview_(s2)
        getattr(self, "_page_" + page)(view, height - 54 - 24)
        return view

    # ---------- 布局页（4d 编辑本体原样搬入，宽度改为 CONTENT_W） ----------

    def _build_layout_page(self, buckets, height):
        # 页视图用 GridView：它是窗口的 firstResponder，方向键才能进到我们手里
        content = GridView.alloc().initWithFrame_(NSMakeRect(0, 0, CONTENT_W, height))
        content.settings_ctrl = self  # 方向键转发给控制器（不起 controller 这个名字，避开与 AppKit 同名属性撞车）
        cols = max(1, int((CONTENT_W - 2 * EDGE) // (TILE_W + TILE_GAP)))

        title = NSTextField.labelWithString_(
            "菜单栏布局 · 单击选中，⌥←/→ 改顺序，⌥↑/↓ 换区")
        title.setFont_(NSFont.boldSystemFontOfSize_(13))
        title.setFrame_(NSMakeRect(EDGE, height - HEADER_H, CONTENT_W - 2 * EDGE, ROW_H))
        content.addSubview_(title)
        top = height - HEADER_H

        for sec in _SECTION_ORDER:
            group = buckets[sec]
            if not group:
                continue
            label = NSTextField.labelWithString_(
                f"{sections.SECTION_LABELS[sec]} · {len(group)} 项")
            label.setFont_(NSFont.boldSystemFontOfSize_(11))
            label.setTextColor_(NSColor.secondaryLabelColor())
            label.setFrame_(NSMakeRect(EDGE, top - SECTION_H,
                                       CONTENT_W - 2 * EDGE - 100, SECTION_H))
            content.addSubview_(label)
            if len(group) > 1:
                # Thaw 每区的「Sort by Name」：点一下把该区按名字典序写进 order（⌘Z 可撤）
                sb = NSButton.alloc().initWithFrame_(
                    NSMakeRect(CONTENT_W - EDGE - 92, top - SECTION_H + 1, 92, 20))
                sb.setTitle_("按名称排序")
                sb.setBezelStyle_(0)
                sb.setFont_(NSFont.systemFontOfSize_(10))
                sb.setTarget_(self)
                sb.setAction_("onSortSection:")
                sb.setRepresentedObject_(sec)
                content.addSubview_(sb)
            top -= SECTION_H
            for idx, item in enumerate(group):
                row, col = divmod(idx, cols)
                x = EDGE + col * (TILE_W + TILE_GAP)
                y = top - TILE_H - row * (TILE_H + TILE_GAP)
                content.addSubview_(self._make_tile(item, sec, x, y))
            top -= ((len(group) + cols - 1) // cols) * (TILE_H + TILE_GAP) + GAP

        # ---------- 底部（自上而下）：提示行 / 选中提示 / 移区按钮 / 顺序按钮 / 重置 ----------
        # 权限提醒与重抓、超时都搬到对应页（疑难解答/通用），这页只留编辑相关

        # 挤不下/够不着提示（Thaw OutOfRoomWarning/.outOfReach 的位置选择，T72）
        for text in self._hints():
            hint = NSTextField.labelWithString_(text)
            hint.setFont_(NSFont.systemFontOfSize_(11))
            hint.setTextColor_(NSColor.systemOrangeColor())
            hint.setFrame_(NSMakeRect(EDGE, top - ROW_H, CONTENT_W - 2 * EDGE, ROW_H))
            hint.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)   # 窄窗口截尾不折行（枚举用命名常量，T70）
            content.addSubview_(hint)
            top -= ROW_H + 8

        # 选中提示（名字只在这里出现，格子上永远只有图标）
        self.lbl_selection = NSTextField.labelWithString_("")
        self.lbl_selection.setFont_(NSFont.systemFontOfSize_(11))
        self.lbl_selection.setTextColor_(NSColor.secondaryLabelColor())
        self.lbl_selection.setFrame_(NSMakeRect(EDGE, top - ROW_H, CONTENT_W - 2 * EDGE, ROW_H))
        content.addSubview_(self.lbl_selection)
        top -= ROW_H + 8

        # 移区动作：作用于当前选中项（主路径，不依赖菜单跟踪）
        x = EDGE
        for idx, sec in enumerate(_SECTION_ORDER):
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, top - ROW_H, 116, ROW_H))
            btn.setTitle_(_MOVE_TITLES[sec])
            btn.setBezelStyle_(0)
            btn.setFont_(NSFont.systemFontOfSize_(11))
            btn.setEnabled_(False)
            btn.setTag_(idx)
            btn.setTarget_(self)
            btn.setAction_("onMoveButton:")
            content.addSubview_(btn)
            self.move_buttons.append(btn)
            x += 120
        top -= ROW_H + 8

        # 顺序动作（同区内）+ 撤销：与上面的移区行同构，鼠标也能完成键盘那套
        x = EDGE
        for label, delta in (("← 前移", -1), ("后移 →", 1)):
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, top - ROW_H, 90, ROW_H))
            btn.setTitle_(label)
            btn.setBezelStyle_(0)
            btn.setFont_(NSFont.systemFontOfSize_(11))
            btn.setEnabled_(False)
            btn.setTag_(delta)  # tag 直接携带位移量（-1/1），不用反查数组下标
            btn.setTarget_(self)
            btn.setAction_("onReorderButton:")
            content.addSubview_(btn)
            self.order_buttons.append(btn)
            x += 96
        btn_undo = NSButton.alloc().initWithFrame_(NSMakeRect(x, top - ROW_H, 76, ROW_H))
        btn_undo.setTitle_("撤销")
        btn_undo.setBezelStyle_(0)
        btn_undo.setFont_(NSFont.systemFontOfSize_(11))
        btn_undo.setEnabled_(bool(self._undo))
        btn_undo.setTarget_(self)
        btn_undo.setAction_("onUndo")  # onUndo 是零参方法，选择子不带冒号
        content.addSubview_(btn_undo)
        btn_undo.setToolTip_("回上一步分区/顺序改动（⌘Z）")
        self.btn_undo = btn_undo
        kb = NSTextField.labelWithString_("⌥←/→ 改顺序 · ⌥↑/↓ 换区 · ⌘1/2/3 移区 · ⌘Z 撤销")
        kb.setFont_(NSFont.systemFontOfSize_(10))
        kb.setTextColor_(NSColor.tertiaryLabelColor())
        kb.setAlignment_(2)  # 右对齐
        kb.setFrame_(NSMakeRect(x + 84, top - ROW_H, CONTENT_W - EDGE - x - 84, ROW_H))
        kb.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
        content.addSubview_(kb)
        top -= ROW_H + 8

        # 重置布局（Thaw Reset Layout）：确认后才动，动完留一步可撤销
        btn_reset = NSButton.alloc().initWithFrame_(
            NSMakeRect(EDGE, top - ROW_H, 96, ROW_H))
        btn_reset.setTitle_("重置布局")
        btn_reset.setBezelStyle_(0)
        btn_reset.setFont_(NSFont.systemFontOfSize_(11))
        btn_reset.setTarget_(self)
        btn_reset.setAction_("onResetLayout:")
        btn_reset.setToolTip_("把弹窗显示/永久隐藏的图标全部带回菜单栏，并清空自定义顺序")
        content.addSubview_(btn_reset)
        return content

    def _make_tile(self, item, sec, x, y):
        """一个图标格子：**只有图标**（截取像素缺失时用兜底图标，绝不显示名字）。

        单击 = 选中（按钮切换态高亮）；右键 = 系统自动弹 setMenu: 挂的移区菜单（T27）。
        """
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, TILE_W, TILE_H))
        key = sections.item_key(item)
        img = self.images.get(key) or capture.fallback_image_for_item(item)
        if img is not None:
            btn.setImage_(img)
        btn.setTitle_("")
        btn.setImagePosition_(NSImageOnly)   # 只有图且居中（5 是 NSImageAbove，会把图顶到上沿）
        btn.setImageScaling_(NSImageScaleProportionallyDown)  # 兜底：宽度收口在 capture.fit_box
        # 同面板（P42）：不画 rounded 胶囊底色，只给选中那一项自己垫一层淡底，
        # 余下格子就是干净的图标（选中态仍由 state 承载，AX 仍报 AXCheckBox，T63）
        btn.setBordered_(False)
        btn.setButtonType_(1)  # PushOnPushOff：选中态由 state 承载
        btn.setState_(1 if key == self.selected_key else 0)
        btn.setWantsLayer_(True)
        self._paint_tile(btn, key == self.selected_key)
        btn.setTag_(_SECTION_ORDER.index(sec))
        btn.setRepresentedObject_(key)  # 反查 item 用（图标模式下标题为空）
        btn.setTarget_(self)
        btn.setAction_("onTileClick:")
        btn.setMenu_(self._menu_for(item, sec))
        owner = "系统" if item.owner_app == "系统" else item.owner_app
        btn.setToolTip_(f"{item.label}\n{owner}（{item.owner_bundle_id}）\n"
                        f"当前：{sections.SECTION_LABELS[sec]}")
        btn.setAccessibilityLabel_(f"{item.label}，{sections.SECTION_LABELS[sec]}")
        # 身份标识用配置键：图标名常常是活文本（温度、网速、Wi‑Fi 格数），
        # 拿名字当身份会在两次读取之间自己变脸
        btn.setAccessibilityIdentifier_(key)
        self.tiles[key] = btn
        return btn

    def _menu_for(self, item, cur_sec):
        """右键菜单：与 Thaw 「Move to」子菜单同构（当前区打勾，⌘1/2/3 直达）。"""
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        for idx, sec in enumerate(_SECTION_ORDER):
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                sections.SECTION_LABELS[sec], "onMoveSection:", str(idx + 1))
            mi.setKeyEquivalentModifierMask_(1 << 20)  # NSEventModifierFlagCommand
            mi.setTarget_(self)  # 显式 target，不依赖响应链（T21）
            mi.setState_(1 if sec == cur_sec else 0)
            mi.setTag_(idx)
            mi.setRepresentedObject_(sections.item_key(item))
            menu.addItem_(mi)
        return menu

    def _paint_tile(self, btn, selected):
        """选中格自己画一层淡底（其余格子透明），避开 NSButton 胶囊底块的硬边。"""
        layer = btn.layer()
        if layer is None:
            return
        layer.setCornerRadius_(6.0)
        if selected:
            cg = Quartz.CGColorCreateGenericRGB(1.0, 1.0, 1.0, 0.14)
        else:
            cg = Quartz.CGColorCreateGenericRGB(0.0, 0.0, 0.0, 0.0)
        layer.setBackgroundColor_(cg)

    # ---------- 交互 ----------

    def onTileClick_(self, sender):
        """单击图标 = 选中（底部提示与移区按钮随之可用）。不再在这里手弹菜单。"""
        item = self._item_at(sender)
        if item is None:
            print("[PeaseBar] 设置：格子点击但未反查到 item（representedObject 丢失）")
            return
        key = str(sender.representedObject())
        self.selected_key = key
        self._sync_selection()
        sec = _SECTION_ORDER[sender.tag()] if 0 <= sender.tag() < len(_SECTION_ORDER) \
            else sections.SECTION_VISIBLE
        print(f"[PeaseBar] 设置：选中 {item.label!r}（当前 {sections.SECTION_LABELS[sec]}）")

    def onMoveButton_(self, sender):
        """底部「移到 X 区」按钮：作用于当前选中项。"""
        if self.selected_key is None:
            return
        self.applyMove_to_(self.selected_key, _TAG_SECTIONS.get(sender.tag()))

    def onReorderButton_(self, sender):
        """底部「← 前移 / 后移 →」：同区内移动选中项（tag 就是位移量）。"""
        self.reorderSelected_by_(self.selected_key, sender.tag())

    def onUndo(self):
        """撤销按钮（零参 action）：回上一步分区/顺序改动。"""
        self._undo_step()

    def onMoveSection_(self, sender):
        """右键菜单项：移到 sender 标记的区（菜单项自带目标键）。"""
        key = sender.representedObject()
        self.applyMove_to_(str(key) if key is not None else None,
                          _TAG_SECTIONS.get(sender.tag()))

    def onPickPage_(self, sender):
        """侧栏切页：通用页先落盘超时输入，再整窗重画。"""
        if getattr(self, "page", "layout") == "general":
            self._save_timeout()
        self.page = str(sender.representedObject())
        print(f"[PeaseBar] 设置：切到 {self.page} 页")
        self._rebuild()

    def onSortSection_(self, sender):
        """每区「按名称排序」：把区内顺序按名字典序物化（压撤销点，⌘Z 可回；
        已经有序时不写盘不留撤销痕迹）。"""
        sec = str(sender.representedObject())
        buckets, changed = sections.sort_bucket_by_name(self.buckets, sec)
        if not changed:
            print(f"[PeaseBar] 设置：{sections.SECTION_LABELS[sec]} 已按名称有序，不改动")
            return
        self._commit_order_note(buckets, f"按名称排序：{sections.SECTION_LABELS[sec]}")

    def onResetLayout_(self, sender):
        """重置布局：先弹确认再动；压了撤销点，重置完还能 ⌘Z 撤回来。"""
        alert = NSAlert.alloc().init()
        alert.setMessageText_("重置布局？")
        alert.setInformativeText_("把弹窗显示/永久隐藏的图标全部带回菜单栏，并清空自定义顺序。"
                                  "此步可用 ⌘Z 撤销。")
        alert.addButtonWithTitle_("重置")
        alert.addButtonWithTitle_("取消")
        if int(alert.runModal()) != int(NSAlertFirstButtonReturn):
            print("[PeaseBar] 设置：重置布局被取消")
            return
        cfg = sections.load_config()
        self._push_undo(cfg)
        sections.reset_layout(cfg)
        sections.save_config(cfg)
        print("[PeaseBar] 设置：重置布局（全部回菜单栏，顺序清空）")
        self._rebuild()
        if self.on_changed:
            self.on_changed()

    def onLaunchToggle_(self, sender):
        """开机自启开关（SMAppService）：改完以系统回读为准，UI 不自说自话（P95 判据）。"""
        want_on = int(sender.state()) == 1
        svc = SM.SMAppService.mainAppService()
        try:
            res = (svc.registerAndReturnError_(None) if want_on
                   else svc.unregisterAndReturnError_(None))
            # PyObjC 把 NSError** 出参包成 (bool, error) 元组；老签名直接返回 bool
            ok, err = (res if isinstance(res, tuple) else (res, None))
            if not ok:
                sender.setState_(0 if want_on else 1)  # 没成就把开关拨回去
                desc = err.localizedDescription() if err is not None else "未知原因"
                self.lbl_launch_status.setStringValue_(f"系统拒绝了这次修改：{desc}")
        except Exception as exc:  # noqa: BLE001 — 如实上屏，不假装成功
            sender.setState_(0 if want_on else 1)
            self.lbl_launch_status.setStringValue_(f"调用失败：{exc}")
        self._sync_launch_state()
        print(f"[PeaseBar] 设置：开机自启切换 {'开' if want_on else '关'}，"
              f"回读状态={self._launch_status()}")

    def _launch_status(self):
        """回读 SMAppService 当前状态码；拿不到返回 None（老系统/异常如实反映）。"""
        try:
            return int(SM.SMAppService.mainAppService().status())
        except Exception:  # noqa: BLE001
            return None

    def _sync_launch_state(self):
        st = self._launch_status()
        on, text = _LOGIN_STATUS.get(st, (False, "读不到系统状态"))
        if getattr(self, "chk_launch", None) is not None:
            self.chk_launch.setState_(1 if on else 0)
        # 错误文案优先：刚失败过就别用状态码把失败信息盖掉
        if getattr(self, "lbl_launch_status", None) is not None and st is not None:
            cur = self.lbl_launch_status.stringValue() or ""
            if not cur.startswith(("系统拒绝", "调用失败")):
                self.lbl_launch_status.setStringValue_(text)

    # ---------- 静态页 builder（通用/快捷键/疑难解答/关于） ----------

    def _page_general(self, view, top):
        y = top
        # NSSwitch 画 macOS 原生拨动开关（Thaw 的 Toggle 同款观感），
        # 标题另给静态文本：开关本体不带 title，取证签名落在文本上才稳
        self.chk_launch = NSSwitch.alloc().initWithFrame_(
            NSMakeRect(EDGE, y - ROW_H + 1, 60, ROW_H - 2))
        self.chk_launch.setTarget_(self)
        self.chk_launch.setAction_("onLaunchToggle:")
        self.chk_launch.setAccessibilityLabel_("登录时启动 PeaseBar")
        self.chk_launch.setAccessibilityIdentifier_("launch-at-login")
        view.addSubview_(self.chk_launch)
        lab = NSTextField.labelWithString_("登录时启动 PeaseBar")
        lab.setFont_(NSFont.systemFontOfSize_(12))
        lab.setFrame_(NSMakeRect(EDGE + 68, y - ROW_H, 260, ROW_H))
        view.addSubview_(lab)
        y -= ROW_H + 8
        self.lbl_launch_status = self._mk_label(view, EDGE + 2, y - ROW_H, "", w=CONTENT_W - 2 * EDGE)
        y -= ROW_H + 22
        lbl_to = NSTextField.labelWithString_("面板自动收回（秒，0=不超时）")
        lbl_to.setFont_(NSFont.systemFontOfSize_(11))
        lbl_to.setFrame_(NSMakeRect(EDGE, y - ROW_H, 220, ROW_H))
        view.addSubview_(lbl_to)
        cfg = sections.load_config()
        self.field_timeout = NSTextField.alloc().initWithFrame_(
            NSMakeRect(EDGE + 224, y - ROW_H, 60, ROW_H))
        self.field_timeout.setStringValue_(str(int(cfg.get("panel_timeout", 8))))
        self.field_timeout.setEditable_(True)
        self.field_timeout.setTarget_(self)
        self.field_timeout.setAction_("onTimeoutChanged:")
        view.addSubview_(self.field_timeout)
        y -= ROW_H + 8
        lbl_ic = NSTextField.labelWithString_("菜单栏控制图标")
        lbl_ic.setFont_(NSFont.systemFontOfSize_(11))
        lbl_ic.setFrame_(NSMakeRect(EDGE, y - ROW_H, 220, ROW_H))
        view.addSubview_(lbl_ic)
        # pullsDown=False：选中项显示在钮体内，取证读 stringValue 即当前预设
        self.popup_icon = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(EDGE + 224, y - ROW_H - 2, 160, ROW_H + 4), False)
        for _sym, name in sections.CONTROL_ICONS:
            self.popup_icon.addItemWithTitle_(name)
        cur = next((i for i, (k, _) in enumerate(sections.CONTROL_ICONS)
                    if k == cfg.get("control_icon")), 0)
        self.popup_icon.selectItemAtIndex_(cur)
        self.popup_icon.setTarget_(self)
        self.popup_icon.setAction_("onControlIconChanged:")
        self.popup_icon.setAccessibilityIdentifier_("control-icon-picker")
        view.addSubview_(self.popup_icon)
        self._sync_launch_state()

    def _page_shortcuts(self, view, top):
        y = self._mk_row(view, top, "⌥⌘B　开关救援面板", NSColor.labelColor())
        y = self._mk_row(view, y, "⌥⌘S　打开设置窗口", NSColor.labelColor())
        self._mk_row(view, y - 8, "快捷键注册即全局生效（需辅助功能权限）；"
                               "自定义录制键排在后续版本，这里不放假按钮")

    def _page_troubleshoot(self, view, top):
        ax_ok = bool(AXIsProcessTrusted())
        rec_ok = bool(capture.has_screen_permission())
        y = top
        y = self._perm_row(view, y, "辅助功能（全局快捷键/读取图标）", ax_ok)
        y = self._perm_row(view, y, "屏幕录制（抓取图标真实像素）", rec_ok)
        x = EDGE
        if not ax_ok:
            self._mk_btn(view, x, y - ROW_H, "打开辅助功能设置", "onOpenAXSettings:", 150)
            x += 158
        if not rec_ok:
            self._mk_btn(view, x, y - ROW_H, "请求屏幕录制权限", "onRequestPermission:", 150)
            x += 158
        self._mk_btn(view, x, y - ROW_H, "重新抓取图标", "onRecapture:", 120)
        x += 128
        self._mk_btn(view, x, y - ROW_H, "打开日志文件", "onOpenLog:", 110)
        y -= ROW_H + 12
        self.lbl_diag_status = self._mk_label(view, EDGE, y - ROW_H, "", size=10)
        y -= ROW_H + 6
        summary = (f"图标 {len(self.items)} 项 · 被系统收纳 {self.stashed_count} · 被刘海遮挡 "
                   f"{self.notched_count}；真实像素 {self.stats['cropped']} 张 / 兜底 "
                   f"{self.stats['fallback']} 张")
        self._mk_row(view, y, summary)

    def _perm_row(self, view, y, name, ok):
        lab = NSTextField.labelWithString_(f"{name}：{'✓ 已授权' if ok else '✗ 未授权'}")
        lab.setFont_(NSFont.systemFontOfSize_(12))
        lab.setTextColor_(NSColor.labelColor() if ok else NSColor.systemRedColor())
        lab.setFrame_(NSMakeRect(EDGE, y - ROW_H, CONTENT_W - 2 * EDGE, ROW_H))
        view.addSubview_(lab)
        return y - ROW_H - 6

    def _page_about(self, view, top):
        from peasebar import __version__
        y = self._mk_row(view, top, f"版本 {__version__}", NSColor.labelColor())
        y = self._mk_row(view, y, "把被刘海遮挡、被系统收纳的菜单栏图标找回来，并一键触发。",
                      NSColor.labelColor())
        x = EDGE
        self._mk_btn(view, x, y - ROW_H, "复制版本信息", "onCopyVersion:", 130)
        x += 138
        self._mk_btn(view, x, y - ROW_H, "打开源码仓库", "onOpenRepo:", 120)
        y -= ROW_H + 10
        self.lbl_about_status = self._mk_label(view, EDGE, y - ROW_H, "", size=10)

    def onCopyVersion_(self, sender):
        from peasebar import __version__
        # operatingSystemVersionString 是属性：带尾下划线调会抛异常，而动作里的异常
        # 会被 AppKit 吞进系统日志（我们自己的文件里看不到），判据现场栽过一次
        text = (f"PeaseBar {__version__} · macOS "
                f"{NSProcessInfo.processInfo().operatingSystemVersionString()} · "
                f"Python {platform.python_version()}")
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.writeObjects_([text])
        if getattr(self, "lbl_about_status", None) is not None:
            self.lbl_about_status.setStringValue_(f"已复制：{text}")

    def onOpenRepo_(self, sender):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(REPO_URL))

    def onOpenLog_(self, sender):
        if not os.path.exists(LOG_PATH):
            self.lbl_diag_status.setStringValue_("尚无日志文件")
            return
        NSWorkspace.sharedWorkspace().openFile_(LOG_PATH)
        self.lbl_diag_status.setStringValue_(f"已请求打开 {LOG_PATH}")

    def onOpenAXSettings_(self, sender):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"))

    def _mk_label(self, view, x, y, text, size=11, w=None):
        """静态页的通用文本标签（左对齐、次级色），返回控件供后续改文本。"""
        lab = NSTextField.labelWithString_(text)
        lab.setFont_(NSFont.systemFontOfSize_(size))
        lab.setTextColor_(NSColor.secondaryLabelColor())
        lab.setFrame_(NSMakeRect(x, y, w or (CONTENT_W - x - EDGE), ROW_H))
        view.addSubview_(lab)
        return lab

    def _mk_row(self, view, y, text, color=None):
        lab = self._mk_label(view, EDGE, y - ROW_H, text)
        if color is not None:
            lab.setTextColor_(color)
        return y - ROW_H - 6

    def _mk_btn(self, view, x, y, text, action, width=120):
        b = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, ROW_H))
        b.setTitle_(text)
        b.setBezelStyle_(0)
        b.setFont_(NSFont.systemFontOfSize_(11))
        b.setTarget_(self)
        b.setAction_(action)
        view.addSubview_(b)
        return b

    def handleKey_(self, event):
        """键盘编辑（照 Thaw：⌥-arrows to move the selected one）。

        返回 True = 已消费；False = GridView 交回 super（响铃/焦点环照旧）。
        ⋅ 不带修饰：方向键只移动选中焦点；⌥：真改布局；⌘1/2/3：移区；⌘Z：撤销。
        """
        code = int(event.keyCode())
        flags = int(event.modifierFlags())
        opt = bool(flags & NSEventModifierFlagOption)
        cmd = bool(flags & NSEventModifierFlagCommand)
        ch = (event.charactersIgnoringModifiers() or "").lower()
        if cmd and not opt:
            if ch == "z":
                return self._undo_step()
            if ch in ("1", "2", "3") and self.selected_key:
                self.applyMove_to_(self.selected_key, _TAG_SECTIONS[int(ch) - 1])
                return True
            return False
        if cmd:
            return False
        dx = {KEY_LEFT: -1, KEY_RIGHT: 1}.get(code)
        dy = {KEY_UP: -1, KEY_DOWN: 1}.get(code)
        if dx is None and dy is None:
            return False
        if not opt:
            return self._move_focus(dx or 0, dy or 0)
        if dx is not None:
            return self.reorderSelected_by_(self.selected_key, dx)
        return self._move_selected_section(dy)

    # ---------- 编辑动作（键盘/按钮/菜单共用一套写入） ----------

    def _push_undo(self, cfg):
        """写盘前先拍快照（只存分区与顺序，没真改动不调这里）。"""
        self._undo.append(sections.snapshot(cfg))
        if len(self._undo) > UNDO_LIMIT:
            del self._undo[0]

    def _undo_step(self):
        """弹快照回盘并重建；栈空时返回 False（让 ⌘Z 响铃，不静默默响）。"""
        if not self._undo:
            return False
        snap = self._undo.pop()
        cfg = sections.load_config()
        sections.restore_snapshot(cfg, snap)
        sections.save_config(cfg)
        print("[PeaseBar] 设置：撤销一步")
        self._rebuild()
        if self.on_changed:
            self.on_changed()
        return True

    def _commit_order_note(self, buckets, note):
        """把一次编辑（分桶结果）物化成显式顺序写盘，再重建界面。"""
        cfg = sections.load_config()
        self._push_undo(cfg)
        sections.store_order(cfg, sections.flatten(buckets))
        sections.save_config(cfg)
        print(f"[PeaseBar] 设置：{note}")
        self.buckets = buckets  # 先同步状态再重建：持续 ⌥→ 时第二下才不会拿着旧分桶算
        self._rebuild()
        if self.on_changed:
            self.on_changed()

    def reorderSelected_by_(self, key, delta):
        """同区内前移/后移一格。返回是否真动了（动不了不记撤销点）。

        重排本体在 `sections.reorder_bucket`（纯函数、单测直接测它），
        这里只负责「取位置→写盘→刷界面」。注意重排只改我们自己的展示顺序，
        把顺序写回**真实菜单栏**是 Phase 3 的 ⌘拖拽（§8 P3.1）。
        """
        if not key or not delta:
            return False
        pos = self._sel_pos()
        if pos is None:
            return False
        sec = pos[0]
        buckets, changed = sections.reorder_bucket(self.buckets, sec, key, int(delta))
        if not changed:
            print(f"[PeaseBar] 设置：{sections.SECTION_LABELS[sec]} 已到边界，不动")
            return False
        n = sections.find_pos(buckets, key)[1] + 1
        total = len(buckets[sec])
        self._commit_order_note(buckets,
                                f"顺序：{key} → {sections.SECTION_LABELS[sec]} 第 {n}/{total} 格")
        return True

    def _move_selected_section(self, delta):
        """⌥↑/⌥↓：把选中项移到上/下一个区（对应 Thaw 拖拽跨区）。"""
        pos = self._sel_pos()
        if pos is None:
            return False
        target = sections.neighbour_section(pos[0], int(delta))
        if target is None:
            return False
        self.applyMove_to_(self.selected_key, target)
        return True

    def _move_focus(self, dx, dy):
        """不带修饰的方向键：只移动选中焦点（落位规则在 sections.select_neighbour）。"""
        key = sections.select_neighbour(self.buckets, self.selected_key, int(dx), int(dy))
        if key is None:
            return False
        self.selected_key = key
        self._sync_selection()
        return True

    def _sel_pos(self):
        """选中项在 (区, 区内序号) 里的位置；没选中或已消失返回 None。"""
        return sections.find_pos(self.buckets, self.selected_key)

    def applyMove_to_(self, key, target):
        """写配置 + 刷新（按钮、右键菜单、⌥↑↓、⌘1/2/3 共用的唯一入口）。

        命名注意（PyObjC 的选择子映射，规则来自 objc._transform.default_selector）：
        方法名只带**一个**下划线时会被当成选择子（尾部的 `_` 换成 `:`，
        只有前导 `_` 则当零参选择子），参数对不上就在建类时报 BadPrototypeError
        （启动即死）。所以：带参方法要么写成 `xxx_y_`（冒号数 = 参数数），
        要么名字里至少放两个下划线（`_commit_order_note` 这种就根本不导出）。
        """
        if not key or target is None:
            return
        cfg = sections.load_config()
        if sections.section_of(cfg, key) == target:
            return  # 原地不动不算改动：不记撤销点，免得 ⌘Z 看起来失灵
        self._push_undo(cfg)
        sections.set_section(cfg, key, target)
        # 换区后抻到目标区末尾：不重排的话新位置由旧 order 位次决定，跳来跳去没规律
        buckets = sections.plan_sections(self.items, cfg)
        item = self._item_by_key(key)
        if item is not None:
            rest = [it for it in buckets[target] if sections.item_key(it) != key]
            buckets[target] = rest + [item]
        sections.store_order(cfg, sections.flatten(buckets))
        sections.save_config(cfg)
        print(f"[PeaseBar] 设置：{key}（{item.label if item else '?'}）→ "
              f"{sections.SECTION_LABELS[target]}")
        self.buckets = buckets
        self._rebuild()
        if self.on_changed:
            self.on_changed()

    def _sync_selection(self):
        """把选中态刷到界面：格子高亮、提示文字、移区/顺序/撤销按钮可用度。"""
        item = self._item_by_key(self.selected_key) if self.selected_key else None
        for key, btn in self.tiles.items():
            btn.setState_(1 if key == self.selected_key else 0)
            self._paint_tile(btn, key == self.selected_key)
        pos = self._sel_pos()
        # 选中项可能在两次刷新之间退场（App 退出）：拿不到落位就不当作选中，
        # 否则下一行解包 pos 会直接抛（提示行比格子重要，不能让它弄崩设置窗）
        if item is None or pos is None:
            text = "未选择图标 · 单击图标选中，也可右键直接弹移区菜单"
        else:
            owner = "系统" if item.owner_app == "系统" else item.owner_app
            sec, idx = pos
            text = (f"已选：{item.label}（{owner}）· 当前："
                    f"{sections.SECTION_LABELS[sec]} 第 {idx + 1}/{len(self.buckets[sec])} 格")
        if getattr(self, "lbl_selection", None) is not None:
            self.lbl_selection.setStringValue_(text)
        for btn in getattr(self, "move_buttons", []):
            # 已在目标区的按钮直接置灰（不拿 setState 画勾：momentary 按钮画 state 会看起来卡住）
            btn.setEnabled_(item is not None and
                            (pos is None or _TAG_SECTIONS.get(btn.tag()) != pos[0]))
        for btn in getattr(self, "order_buttons", []):
            # 边界上不给能点：首格再前移、尾格再后移都是无效动作
            able = (item is not None and pos is not None and
                    ((btn.tag() < 0 and pos[1] > 0) or
                     (btn.tag() > 0 and pos[1] < len(self.buckets[pos[0]]) - 1)))
            btn.setEnabled_(able)
        if getattr(self, "btn_undo", None) is not None:
            self.btn_undo.setEnabled_(bool(self._undo))
        self._grab_keys()

    def _grab_keys(self):
        """把键盘所有权从按钮抢回内容视图（GridView）。

        点了格子后焦点会跑到那个 NSButton 上，方向键就不再进内容视图（P81 取证验这一点）。
        只从按钮手里抢：文本输入中的 firstResponder 是窗口的字段编辑器（NSText），
        按类名判定而不是按「是不是我那两个输入框」——否则用户改到一半就被抢走焦点丢字。
        """
        win = self.window
        if win is None:
            return
        fr = win.firstResponder()
        container = win.contentView()
        if container is None or fr is None:
            return
        if isinstance(fr, NSText):        # 正在输入：不打断
            return
        if not isinstance(fr, NSButton):  # 其余（侧栏、滚动条…）一律不抢
            return
        # 页视图不再是窗口 contentView：从容器里找回 GridView，把焦点交给它
        grid = next((v for v in container.subviews() if isinstance(v, GridView)), None)
        if grid is not None and fr is not grid:
            win.makeFirstResponder_(grid)

    def onRecapture_(self, sender):
        capture.invalidate_cache()
        self._reload_items()
        self._rebuild()

    def onRequestPermission_(self, sender):
        ok = capture.request_screen_permission()
        print(f"[PeaseBar] 请求屏幕录制权限，返回={ok}（授权后需重启进程生效）")
        self._reload_items()
        self._rebuild()

    def onTimeoutChanged_(self, sender):
        self._save_timeout()

    def onControlIconChanged_(self, sender):
        """通用页换触发图标预设：落盘 + 回调即时重画菜单栏上的控制图标。"""
        idx = sender.indexOfSelectedItem()
        if not (0 <= idx < len(sections.CONTROL_ICONS)):
            return
        key, name = sections.CONTROL_ICONS[idx]
        cfg = sections.load_config()
        cfg["control_icon"] = key
        sections.save_config(cfg)
        if self.on_control_icon_changed is not None:
            self.on_control_icon_changed()
        print(f"[PeaseBar] 菜单栏控制图标已切换：{name}（{key}）")

    def _save_timeout(self):
        if getattr(self, "field_timeout", None) is None:
            return
        try:
            value = int(float(self.field_timeout.stringValue()))
        except (TypeError, ValueError):
            return
        value = max(0, value)
        cfg = sections.load_config()
        cfg["panel_timeout"] = value
        sections.save_config(cfg)
        print(f"[PeaseBar] 面板自动收回设为 {value}s")
        if self.on_changed:
            self.on_changed()

    def _item_at(self, sender):
        """由格子的 representedObject（配置键）反查 item。"""
        key = sender.representedObject()
        if key is None:
            return None
        return self._item_by_key(str(key))

    def _item_by_key(self, key):
        """按配置键在已盘点项里查找。"""
        if not key:
            return None
        for it in self.items:
            if sections.item_key(it) == key:
                return it
        return None
