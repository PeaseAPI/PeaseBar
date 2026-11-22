#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置窗口（F14 提前落地，分区编辑的唯一入口）。

参照 Thaw 的分工：Thaw 把图标的分区/顺序编辑放在**设置 → 布局页**的仿真菜单栏里
（拖拽跨区、⌥方向键移动、格子只有图标），救援面板只负责临时找回图标。
我们据此把 v1 的「面板格子右键移区」搬进设置窗口，并采用同样的图标化显示：

    控制图标右键 →「设置…」（或 ⌥⌘S）→ 三区图标列表（**只有图标，名字进悬停提示**）
    单击图标 = 选中 → 底部「移到 X 区」按钮；右键图标 = 移区菜单（系统自动弹）

为什么两条路都留：实测本 App 里手动 `NSMenu.popUpContextMenu` 的菜单跟踪不可靠
（T41：action 进去了、菜单却没出现在屏幕上），而按钮路径 100% 可控可测；
右键菜单改用 `setMenu:`（T27：NSView 带菜单时系统自己弹），不再手写跟踪循环。

另含两项维持设置：面板自动收回秒数（F5）、图标位图重抓与屏幕录制授权入口。
顺序编辑（拖拽真实菜单栏）属 Phase 3，本窗口暂不提供。
"""
from AppKit import (
    NSBackingStoreBuffered,
    NSButton,
    NSFont,
    NSImageOnly,
    NSImageScaleProportionallyDown,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSLineBreakByTruncatingTail,
    NSColor,
    NSTextField,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialWindowBackground,
    NSVisualEffectView,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
    NSWindow,
)
from Foundation import NSObject, NSMakeSize
from AppKit import NSApplication
import objc
import Quartz

from peasebar import capture, inventory, sections

WIN_WIDTH = 560
TILE_W, TILE_H = 44, 38
TILE_GAP = 4
EDGE = 16
ROW_H = 24
SECTION_H = 20
HEADER_H = 34
GAP = 12
# 底部固定行数：选中提示 + 移区按钮 + 重抓 + 超时（缺权限时另加 1 行）
BOTTOM_ROWS = 4

# 区 → 移区菜单文案（与面板旧实现一致，编辑语义在设置里更贴切）
_MOVE_TITLES = {
    sections.SECTION_VISIBLE: "回到可见区",
    sections.SECTION_HIDDEN: "移到隐藏区",
    sections.SECTION_ALWAYS_HIDDEN: "移到永久隐藏区",
}
_SECTION_ORDER = (
    sections.SECTION_VISIBLE,
    sections.SECTION_HIDDEN,
    sections.SECTION_ALWAYS_HIDDEN,
)
_TAG_SECTIONS = {0: sections.SECTION_VISIBLE, 1: sections.SECTION_HIDDEN,
                 2: sections.SECTION_ALWAYS_HIDDEN}


class SettingsController(NSObject):
    """设置窗口的创建/刷新/单例持有。app.py 持有本对象强引用。"""

    def init(self):
        # PyObjC 13.0：NSObject 子类必须用 objc.super，普通 super().init() 会报 AttributeError
        self = objc.super(SettingsController, self).init()
        if self is None:
            return None
        self.window = None
        self.items = []
        self.images = {}
        self.stashed_count = 0    # 被系统收纳项数（提示行用，与盘点同源不二次枚举）
        self.notched_count = 0    # 被刘海遮挡项数
        self.stats = dict(capture.last_stats)  # 最近一次取图构成（真实像素/兜底）
        self.tiles = {}       # 配置键 → 格子按钮（选中态/反查用）
        self.selected_key = None  # 当前选中的图标（编辑动作的作用对象）
        self.on_changed = None  # 分区/超时变更后回调（app 用来刷新面板）
        return self

    # ---------- 打开与刷新 ----------

    def show(self):
        """打开或前置设置窗口，并重新盘点刷新内容。"""
        self._reload_items()
        if self.window is None:
            self._build_window()
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
                         f"可在面板「展开收纳区」找回，或选中后移到隐藏区。")
        if self.notched_count:
            hints.append(f"有 {self.notched_count} 项被刘海遮挡：够不着，可移到隐藏区腾位置。")
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
        win.setTitle_("PeaseBar 设置")
        win.setReleasedWhenClosed_(False)  # 关闭后仍复用（否则二次打开野指针）
        win.setDelegate_(self)  # 点红叉关闭时也把超时输入落盘
        win.center()
        self.window = win

    def windowWillClose_(self, notification):
        self._save_timeout()

    def _content_height(self, buckets):
        cols = max(1, int((WIN_WIDTH - 2 * EDGE) // (TILE_W + TILE_GAP)))
        h = EDGE + HEADER_H
        for sec in _SECTION_ORDER:
            n = len(buckets[sec])
            if not n:
                continue
            rows = (n + cols - 1) // cols
            h += SECTION_H + rows * (TILE_H + TILE_GAP) + GAP
        h += (BOTTOM_ROWS + (1 if self.no_permission else 0) + len(self._hints())) * (ROW_H + 8) + EDGE
        return int(h)

    def _rebuild(self):
        cfg = sections.load_config()
        buckets = sections.plan_sections(self.items, cfg)
        cols = max(1, int((WIN_WIDTH - 2 * EDGE) // (TILE_W + TILE_GAP)))
        height = self._content_height(buckets)
        self.tiles = {}
        self.move_buttons = []

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WIN_WIDTH, height))
        blur = NSVisualEffectView.alloc().initWithFrame_(content.frame())
        blur.setMaterial_(NSVisualEffectMaterialWindowBackground)
        blur.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        blur.setState_(1)
        content.addSubview_(blur)

        title = NSTextField.labelWithString_("菜单栏布局 · 单击选中，底部按钮或右键菜单移区")
        title.setFont_(NSFont.boldSystemFontOfSize_(13))
        title.setFrame_(NSMakeRect(EDGE, height - HEADER_H, WIN_WIDTH - 2 * EDGE, ROW_H))
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
            label.setFrame_(NSMakeRect(EDGE, top - SECTION_H, WIN_WIDTH - 2 * EDGE, SECTION_H))
            content.addSubview_(label)
            top -= SECTION_H
            for idx, item in enumerate(group):
                row, col = divmod(idx, cols)
                x = EDGE + col * (TILE_W + TILE_GAP)
                y = top - TILE_H - row * (TILE_H + TILE_GAP)
                content.addSubview_(self._make_tile(item, sec, x, y))
            top -= ((len(group) + cols - 1) // cols) * (TILE_H + TILE_GAP) + GAP

        # ---------- 底部（自上而下）：权限提示 / 选中提示 / 移区按钮 / 重抓 / 超时 ----------
        if self.no_permission:
            warn = NSTextField.labelWithString_(
                "未授予「屏幕录制」权限，图标以 App 图标/系统符号代替。")
            warn.setFont_(NSFont.systemFontOfSize_(11))
            warn.setTextColor_(NSColor.systemRedColor())
            warn.setFrame_(NSMakeRect(EDGE, top - ROW_H, WIN_WIDTH - 2 * EDGE - 130, ROW_H))
            content.addSubview_(warn)
            btn_perm = NSButton.alloc().initWithFrame_(
                NSMakeRect(WIN_WIDTH - EDGE - 120, top - ROW_H, 120, ROW_H))
            btn_perm.setTitle_("请求权限")
            btn_perm.setBezelStyle_(0)
            btn_perm.setFont_(NSFont.systemFontOfSize_(11))
            btn_perm.setTarget_(self)
            btn_perm.setAction_("onRequestPermission:")
            content.addSubview_(btn_perm)
            top -= ROW_H + 8

        # 挤不下/够不着提示（Thaw OutOfRoomWarning/.outOfReach 的位置选择，T72）
        for text in self._hints():
            hint = NSTextField.labelWithString_(text)
            hint.setFont_(NSFont.systemFontOfSize_(11))
            hint.setTextColor_(NSColor.systemOrangeColor())
            hint.setFrame_(NSMakeRect(EDGE, top - ROW_H, WIN_WIDTH - 2 * EDGE, ROW_H))
            hint.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)   # 窄窗口截尾不折行（枚举用命名常量，T70）
            content.addSubview_(hint)
            top -= ROW_H + 8

        # 选中提示（名字只在这里出现，格子上永远只有图标）
        self.lbl_selection = NSTextField.labelWithString_("")
        self.lbl_selection.setFont_(NSFont.systemFontOfSize_(11))
        self.lbl_selection.setTextColor_(NSColor.secondaryLabelColor())
        self.lbl_selection.setFrame_(NSMakeRect(EDGE, top - ROW_H, WIN_WIDTH - 2 * EDGE, ROW_H))
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

        btn_recapture = NSButton.alloc().initWithFrame_(
            NSMakeRect(EDGE, top - ROW_H, 150, ROW_H))
        btn_recapture.setTitle_("重新抓取图标")
        btn_recapture.setBezelStyle_(0)
        btn_recapture.setFont_(NSFont.systemFontOfSize_(11))
        btn_recapture.setTarget_(self)
        btn_recapture.setAction_("onRecapture:")
        content.addSubview_(btn_recapture)
        top -= ROW_H + 8

        lbl_to = NSTextField.labelWithString_("面板自动收回（秒，0=不超时）")
        lbl_to.setFont_(NSFont.systemFontOfSize_(11))
        lbl_to.setFrame_(NSMakeRect(EDGE, top - ROW_H, 200, ROW_H))
        content.addSubview_(lbl_to)
        self.field_timeout = NSTextField.alloc().initWithFrame_(
            NSMakeRect(EDGE + 204, top - ROW_H, 60, ROW_H))
        self.field_timeout.setStringValue_(str(int(cfg.get("panel_timeout", 8))))
        self.field_timeout.setEditable_(True)
        self.field_timeout.setTarget_(self)
        self.field_timeout.setAction_("onTimeoutChanged:")
        content.addSubview_(self.field_timeout)
        top -= ROW_H + 8

        self.window.setContentSize_(NSMakeSize(WIN_WIDTH, height))
        self.window.setContentView_(content)
        self.window.center()
        self._sync_selection()

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

    def onMoveSection_(self, sender):
        """右键菜单项：移到 sender 标记的区（菜单项自带目标键）。"""
        key = sender.representedObject()
        self.applyMove_to_(str(key) if key is not None else None,
                          _TAG_SECTIONS.get(sender.tag()))

    def applyMove_to_(self, key, target):
        """写配置 + 刷新（按钮与菜单共用的唯一入口）。

        命名注意：PyObjC 把不以 `_` 结尾的方法名映射成零参选择子，
        `_move(self, a, b)` 会在建类时报 BadPrototypeError（启动即死的根因），
        带参数的内部方法必须写成 `xxx_y_` 形式。
        """
        if not key or target is None:
            return
        cfg = sections.load_config()
        sections.set_section(cfg, key, target)
        sections.save_config(cfg)
        item = self._item_by_key(key)
        print(f"[PeaseBar] 设置：{key}（{item.label if item else '?'}）→ "
              f"{sections.SECTION_LABELS[target]}")
        self._rebuild()
        if self.on_changed:
            self.on_changed()

    def _sync_selection(self):
        """把选中态刷到界面：格子高亮、提示文字、移区按钮可用度。"""
        item = self._item_by_key(self.selected_key) if self.selected_key else None
        for key, btn in self.tiles.items():
            btn.setState_(1 if key == self.selected_key else 0)
            self._paint_tile(btn, key == self.selected_key)
        if item is None:
            text = "未选择图标 · 单击图标选中，也可右键直接弹移区菜单"
        else:
            owner = "系统" if item.owner_app == "系统" else item.owner_app
            sec = sections.section_of(sections.load_config(), self.selected_key)
            text = (f"已选：{item.label}（{owner}）· 当前："
                    f"{sections.SECTION_LABELS[sec]} · 点下方按钮移区")
        if getattr(self, "lbl_selection", None) is not None:
            self.lbl_selection.setStringValue_(text)
        for btn in getattr(self, "move_buttons", []):
            btn.setEnabled_(item is not None)

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
