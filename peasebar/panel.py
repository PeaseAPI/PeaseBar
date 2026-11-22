#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""救援面板（F3）：PeaseBar 的核心 UI。

交互（验收标准见 docs/DEVELOPMENT.md F3/F4/F5）：
- 左键控制图标或全局快捷键 ⌥⌘B → 面板出现在控制图标正下方（居中锚定）；
- 网格按三区（F4：可见/隐藏/永久隐藏，配置在 config.json）分组展示，
  **只显示图标本身**（被刘海遮挡的图标角标「▨」）；空区不展示；
- 单击面板内图标 → 触发真实图标，面板随即收起：画在可见段上的合成右键（弹其原生
  状态菜单，T17），被系统收纳的合成点击会打偏，改走 AXPress 直接投递；
- 分区编辑不在本面板进行（参照 Thaw：编辑在设置窗口），右键控制图标 →「设置…」；
- 「展开/收起收纳区」按钮联动原生收纳按钮（F12 提前接入，核心场景：
  被刘海遮挡/被收纳的图标从这里找回——展开后再点图标即可弹出菜单）；
- 失焦自动收回（全局鼠标监听，T19）+ 超时自动收回（F5，默认 8s，config.json 可改，0=不超时）。

实现要点：
- 图标位图由 capture 模块截条带裁剪而来，需「屏幕录制」权限；缺权限或抓取失败
  时用兜底图标（App 图标/系统模块 SF 符号）顶上，**格子上永远只有图标、不出名字**
  （照 Thaw 的 OverflowFallbackIcon 思路）；名字只在悬停提示里；
- 分区编辑不在本面板做（参照 Thaw），这里只负责找回并触发图标；
- borderless NSPanel 默认不能成为 key 窗口，用 KeyPanel 子类放开 canBecomeKey；
- 失焦收回不依赖 key 窗口状态（合成事件场景激活是半吊子，T19）；
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
from Foundation import (NSMakePoint, NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer)
import objc

from peasebar import capture, inventory, sections, trigger

# 面板几何（格子只放图标，取小方格；PANEL_WIDTH 保持 468，测试脚本据此识别窗口）
PANEL_WIDTH = 468
GRID_COLS = 9
CELL_W, CELL_H = 44, 38
CELL_GAP = 4
EDGE = 8
HEADER_H = 26
SECTION_H = 22  # 区标题行高（F4）
FOOTER_H = 36

# 刘海遮挡角标（画在格子左上角，不占文字位）
NOTCH_BADGE = "\u25a8"  # ▨


class KeyPanel(NSPanel):
    """允许成为 key 的无边框面板（否则收不到失焦事件）。"""

    def canBecomeKey(self):
        return True


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
        self._timeout_timer = None  # 超时自动收回（F5）
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
            self._arm_timeout()  # 超时自动收回（F5）
            print(f"[PeaseBar] 面板已显示：visible={self.panel.isVisible()}，"
                  f"key={self.panel.isKeyWindow()}，active={NSApp.isActive()}")
        except Exception:
            import traceback
            traceback.print_exc()

    def close(self):
        print("[PeaseBar] close 调用")
        self._disarm_timeout()
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
        """盘点 → 按三区分桶（F4）→ 重建面板内容（每次弹出/刷新调用）。"""
        # 收纳按钮不在网格重复出现（底部有专用按钮）；其余全量展示
        all_items, _ = inventory.list_items()
        self.items = [m for m in all_items if not m.is_stash_button]
        notched = sum(1 for m in self.items if m.notched)
        stashed = sum(1 for m in self.items if m.stashed)
        cfg = sections.load_config()
        buckets = sections.plan_sections(self.items, cfg)
        print(f"[PeaseBar] 盘点完成：总 {len(all_items)} 项，网格 {len(self.items)} 项，"
              f"刘海 {notched} 项，被收纳 {stashed} 项；"
              f"分区：可见 {len(buckets[sections.SECTION_VISIBLE])}"
              f" / 隐藏 {len(buckets[sections.SECTION_HIDDEN])}"
              f" / 永久隐藏 {len(buckets[sections.SECTION_ALWAYS_HIDDEN])}")

        # 图标位图（只显示图标）：截不到像素时 capture_icons 会用兜底图标顶上
        images, no_perm = capture.capture_icons(self.items)
        if no_perm:
            print("[PeaseBar] 无屏幕录制权限 → 格子用兜底图标（App 图标/系统符号）")

        # 高度：头部 + Σ(非空区标题 + 该区网格行) + 底部；空区整段不占位
        groups = []  # (区名, [item])，按展示顺序
        height = EDGE + HEADER_H + FOOTER_H + EDGE
        for s in (sections.SECTION_VISIBLE, sections.SECTION_HIDDEN,
                  sections.SECTION_ALWAYS_HIDDEN):
            group = buckets[s]
            if not group:
                continue
            rows = (len(group) + GRID_COLS - 1) // GRID_COLS
            height += SECTION_H + rows * (CELL_H + CELL_GAP)
            groups.append((s, group))

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
            + (f" · 被收纳 {stashed} 项" if stashed else "")
        )
        header.setFont_(NSFont.boldSystemFontOfSize_(12))
        header.setFrame_(NSMakeRect(EDGE, height - HEADER_H, PANEL_WIDTH - 2 * EDGE, HEADER_H))
        content.addSubview_(header)

        # 分区绘制（从顶部往下：区标题 + 该区网格；AppKit y 轴向上，逐区下移）。
        # 格子 tag 必须是全量 items 的下标（onIconClick_ 按 tag 取 self.items），
        # 分桶只影响展示顺序，用 id 映射还原原索引
        id_to_idx = {id(m): i for i, m in enumerate(self.items)}
        top = height - HEADER_H
        for sec, group in groups:
            title = NSTextField.labelWithString_(
                f"{sections.SECTION_LABELS[sec]} · {len(group)}")
            title.setFont_(NSFont.boldSystemFontOfSize_(10))
            title.setTextColor_(NSColor.secondaryLabelColor())
            title.setFrame_(NSMakeRect(EDGE, top - SECTION_H,
                                       PANEL_WIDTH - 2 * EDGE, SECTION_H))
            content.addSubview_(title)
            top -= SECTION_H
            rows = (len(group) + GRID_COLS - 1) // GRID_COLS
            for idx, item in enumerate(group):
                row, col = divmod(idx, GRID_COLS)
                x = EDGE + col * (CELL_W + CELL_GAP)
                y = top - CELL_H - row * (CELL_H + CELL_GAP)
                content.addSubview_(
                    self._make_cell(item, id_to_idx[id(item)],
                                    images.get(sections.item_key(item)), x, y))
                if item.notched:  # 角标压在格子上方（后加的子视图层级更高）
                    badge = NSTextField.labelWithString_(NOTCH_BADGE)
                    badge.setFont_(NSFont.boldSystemFontOfSize_(9))
                    badge.setTextColor_(NSColor.systemOrangeColor())
                    badge.setFrame_(NSMakeRect(x + 2, y + CELL_H - 14, 12, 12))
                    content.addSubview_(badge)
            top -= rows * (CELL_H + CELL_GAP)

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

        hint = NSTextField.labelWithString_("左键=触发图标 · 分区编辑请进设置")
        hint.setFont_(NSFont.systemFontOfSize_(10))
        hint.setTextColor_(NSColor.secondaryLabelColor())
        hint.setAlignment_(2)  # 右对齐
        hint.setFrame_(NSMakeRect(PANEL_WIDTH - 240, footer_y + 4, 232, 18))
        content.addSubview_(hint)

        panel.setContentView_(content)
        self._position_panel(height)

    def _make_cell(self, item, index, image, x, y):
        """网格格子：**只有图标**（无位图时兜底图标顶上），名字只进悬停提示。"""
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, CELL_W, CELL_H))
        img = image if image is not None else capture.fallback_image_for_item(item)
        if img is not None:
            btn.setImage_(img)
        btn.setTitle_("")
        btn.setImagePosition_(5)  # NSImageOverlaps：无标题，图标居中
        btn.setBezelStyle_(0)  # rounded：保留可点击的按钮外形
        btn.setTag_(index)     # 必须是全量 items 下标（onIconClick_ 按 tag 取）
        btn.setTarget_(self)
        btn.setAction_("onIconClick:")
        owner = "系统" if item.owner_app == "系统" else item.owner_app
        tip = f"{item.label}\n{owner}（{item.owner_bundle_id}）\n左键：触发它（弹原生菜单/默认动作）"
        if item.stashed:
            tip += "\n被系统收纳：坐标不可信，走 AX 直接投递"
        if item.notched:
            tip += "\n▨ 被刘海遮挡"
        btn.setToolTip_(tip)
        btn.setAccessibilityLabel_(item.label)
        return btn

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
        """点击面板内图标：触发真实图标，面板随即收起。

        触发本身交给 trigger（按观察结果分级试），这里只负责「先收面板、再触发」：
        原生菜单的跟踪循环会占住主线程，面板不先收掉会一直悬在那儿。

        为什么不再用合成右键（T59/T60 推翻 T17）：macOS 27.2.1 上把左/右键
        合成到控制中心、时钟、微信的槽位上，指针确实到位了但一个窗口都没多；
        而对托管元素 AXPress 则真的能弹（T61：ToDesk/钉钉/TG Pro/One Switch 弹原生菜单）。
        被收纳的图标同理：槽位挤在收纳按钮口，坐标不可信，只有 AXPress 能递到。
        """
        idx = sender.tag()
        item = self.items[idx] if 0 <= idx < len(self.items) else None
        self.close()  # 先收面板：对方的菜单跟踪循环会占住主线程
        if item is None:
            return
        how, seen = trigger.open_item(item)
        print(f"[PeaseBar] 触发 {item.owner_app}/{item.label}"
              f"{'（被收纳）' if item.stashed else ''}：{how}，反应={'有' if seen else '无'}")

    def onStashClick_(self, sender):
        """展开/收起系统收纳区，然后刷新网格（图标像素变了，同时使位图缓存失效）。"""
        inventory.set_stash_revealed(not inventory.stash_revealed())
        capture.invalidate_cache()
        self._rebuild()
        self.panel.makeKeyAndOrderFront_(None)
        self._arm_timeout()  # 交互续期，避免操作中突然收回

    def onRefreshClick_(self, sender):
        """手动刷新盘点（图标可能增删/位移，位图缓存一并作废）。"""
        capture.invalidate_cache()
        self._rebuild()
        self.panel.makeKeyAndOrderFront_(None)
        self._arm_timeout()  # 交互续期

    # ---------- 超时自动收回（F5） ----------

    def _arm_timeout(self):
        """按 config.json 的 panel_timeout（秒）设定超时收回；0/负值 = 不超时。"""
        self._disarm_timeout()
        timeout = sections.load_config().get("panel_timeout", 8)
        if not timeout or timeout <= 0:
            print("[PeaseBar] 超时收回：已禁用（panel_timeout=0）")
            return
        self._timeout_timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            float(timeout), self, "onTimeout:", None, False)
        NSRunLoop.mainRunLoop().addTimer_forMode_(self._timeout_timer, NSRunLoopCommonModes)
        print(f"[PeaseBar] 超时收回：{timeout:.0f}s 后自动关面板")

    def _disarm_timeout(self):
        """撤销超时计时器（幂等）。"""
        t = self._timeout_timer
        if t is not None and t.isValid():
            t.invalidate()
        self._timeout_timer = None

    def onTimeout_(self, timer):
        """超时到期：面板还开着则收回。"""
        print("[PeaseBar] 面板超时 → 自动收回")
        self._disarm_timeout()
        self.close()

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
