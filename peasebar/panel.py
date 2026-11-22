#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""救援面板（F3）：PeaseBar 的核心 UI。

交互（验收标准见 docs/DEVELOPMENT.md F3/F4/F5）：
- 左键控制图标或全局快捷键 ⌥⌘B → 面板出现在控制图标正下方（居中锚定）；
- **只列被隐藏的图标、且只有一张干净的网格**（照 Thaw 的 overflow 面板：
  无头部标题、无分区标题、无底部按钮，图标居中排布）：
  弹窗显示区（SECTION_HIDDEN）+ 逻辑上在菜单栏但此刻被系统收纳/刘海遮挡的项；
  永久隐藏区不展示；全空时给一行空态提示；
- 单击面板内图标 → 触发真实图标，面板随即收起：画在可见段上的合成右键（弹其原生
  状态菜单，T17），被系统收纳的合成点击会打偏，改走 AXPress 直接投递；
- 分区编辑不在本面板进行（参照 Thaw：编辑在设置窗口），右键控制图标 →「设置…」；
- 「展开/收起收纳区」联动原生收纳按钮（F12）已移到控制图标右键菜单——面板本体不留按钮；
- 失焦自动收回（全局鼠标监听，T19）+ 超时自动收回（F5，默认 8s，config.json 可改，0=不超时）。

性能（T98，用户反馈「点一下卡半天、连点卡死」的修法）：
- 盘点 + 全屏截图像素是重活（最坏秒级），绝不在点击后的主线程同步跑：
  show() 用上一次数据快照**立即渲染**，随后后台线程重新采集，采完回主线程就地更新；
- _collecting 标志防重入：连点只切显隐，不会排队多份采集把主线程事件压垮；
- app.py 启动即 prewarm()，第一次点开也有快照可用。

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
    NSImageOnly,
    NSImageScaleProportionallyDown,
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
import threading
import time

from peasebar import capture, inventory, sections, trigger

# 面板几何：单张干净网格（Thaw 式），格子只放图标、四周留呼吸感；
# PANEL_WIDTH 保持 468，测试脚本据此识别窗口
PANEL_WIDTH = 468
GRID_COLS = 9
CELL_W, CELL_H = 44, 40
CELL_GAP = 6
EDGE = 10
EMPTY_H = 28  # 空态提示行高


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
        self._snapshot = None    # 上一次采集的数据快照：无它也能秒开渲染
        self._collecting = False  # 后台采集进行中标记（防重入）
        self._pending = None      # 后台采完待回主线程的结果
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
        """秒开：先用快照渲染显示，再后台采集刷新（T98：点击响应与重活解耦）。"""
        t0 = time.perf_counter()
        print("[PeaseBar] 面板 show 开始")
        try:
            if self._snapshot is None:
                # 首次无快照（prewarm 还没采完）：只能同步采一次，仅此一回
                self._snapshot = self._collect()
            self._render(self._snapshot)
            print(f"[PeaseBar] 网格完成（{time.perf_counter() - t0:.3f}s），"
                  f"frame={self.panel.frame()}")
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
            self._start_background_refresh()  # 显示后再换最新数据，不阻塞点击响应
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

    # ---------- 内部：采集（重活，可后台）与渲染（主线程） ----------
    
    def prewarm(self):
        """启动后后台预热快照：第一次点击也能秒开。"""
        self._start_background_refresh()
    
    def refresh_now(self):
        """设置变更/展开收纳后：作废位图缓存并后台刷新（面板开着就即时更新）。"""
        capture.invalidate_cache()
        if self._snapshot is None:
            self._snapshot = self._collect()
            if self.panel is not None and self.panel.isVisible():
                self._render(self._snapshot)
        else:
            self._start_background_refresh()
    
    def _collect(self):
        """纯数据采集：盘点 → 挑「被隐藏的图标」→ 位图。不做任何 AppKit UI，可子线程调用。
    
        照 Thaw：弹窗不是全量镜像——菜单栏此刻画着的图标不出现在面板里；
        面板只负责找回「看不见」的：弹窗显示区（用户藏起来的）+
        逻辑上在菜单栏但被系统收纳/刘海遮挡的（系统藏起来的）。永久隐藏不展示。
        """
        all_items, _ = inventory.list_items()
        items = [m for m in all_items if not m.is_stash_button]
        cfg = sections.load_config()
        buckets = sections.plan_sections(items, cfg)
        hidden_group = buckets[sections.SECTION_HIDDEN]
        # 可见区里此刻没画在菜单栏上的（被收纳/被刘海挡）：救援目标
        lost_group = [m for m in buckets[sections.SECTION_VISIBLE]
                      if m.stashed or m.notched]
        stashed = sum(1 for m in items if m.stashed)
        notched = sum(1 for m in items if m.notched)
        # 单张网格：先用户藏的、再系统藏的（两类的区分留给 tooltip 说明）
        group = hidden_group + lost_group
        # 图标位图（只显示图标）：截不到像素时 capture_icons 会用兕底图标顶上；
        # 位置没变时代际缓存命中，后台刷新也不会重截
        images, no_perm = capture.capture_icons(items)
        print(f"[PeaseBar] 盘点完成：总 {len(all_items)} 项，弹窗显示 {len(hidden_group)} 项，"
              f"被收纳 {stashed} 项，刘海 {notched} 项；网格 {len(group)} 项"
              + ("，无屏幕录制权限→兕底图标" if no_perm else ""))
        return {"items": items, "images": images, "group": group}
    
    def _start_background_refresh(self):
        """后台采集（防重入）：同一时刻最多一份，点击再快也不会排队堆积压垮主线程。"""
        if self._collecting:
            return
        self._collecting = True
        threading.Thread(target=self._collect_worker, daemon=True).start()
    
    def _collect_worker(self):
        """子线程：只采纯数据，采完回主线程渲染（UI 绝不在子线程碰）。"""
        try:
            self._pending = self._collect()
        except Exception:
            import traceback
            traceback.print_exc()
            self._pending = None
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "_refreshDone:", None, False)
    
    def _refreshDone_(self, _sender):
        """主线程回调：快照落袋；面板还开着就地更新（不抢焦点、不重设超时）。"""
        self._collecting = False
        snap = self._pending
        self._pending = None
        if snap is None:
            return
        self._snapshot = snap
        if self.panel is not None and self.panel.isVisible():
            self._render(snap)
    
    @objc.python_method
    def _render(self, snap):
        """主线程渲染单张干净网格：无标题、无按钮、图标居中（Thaw 式）。

        必须 @objc.python_method：单参且无尾下划线的名字会被 PyObjC 拿去对号
        运行时里已存在的 0 参选择子 _render，建类即 BadPrototypeError（T41 变体，
        启动装配崩、面板快捷键全挂——日志里抓到的真因）。"""
        items, images, group = snap["items"], snap["images"], snap["group"]
        self.items = items  # onIconClick_ 按 tag 取格，必须与快照一致
        rows = (len(group) + GRID_COLS - 1) // GRID_COLS if group else 1
        height = EDGE * 2 + (rows * (CELL_H + CELL_GAP) - CELL_GAP
                             if group else EMPTY_H)
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
    
        if not group:
            empty = NSTextField.labelWithString_("没有隐藏的图标")
            empty.setFont_(NSFont.systemFontOfSize_(11))
            empty.setTextColor_(NSColor.secondaryLabelColor())
            empty.setAlignment_(1)  # 居中
            empty.setFrame_(NSMakeRect(EDGE, EDGE + (EMPTY_H - 16) // 2,
                                       PANEL_WIDTH - 2 * EDGE, 16))
            content.addSubview_(empty)
        else:
            # 水平居中：按最宽一行的实际宽度起算，不再贴左边留大空位
            cols = min(len(group), GRID_COLS)
            grid_w = cols * (CELL_W + CELL_GAP) - CELL_GAP
            x0 = (PANEL_WIDTH - grid_w) / 2
            # 格子 tag 必须是全量 items 的下标（onIconClick_ 按 tag 取 self.items），
            # 网格是展示顺序，用 id 映射还原原索引
            id_to_idx = {id(m): i for i, m in enumerate(items)}
            top = height - EDGE
            for idx, item in enumerate(group):
                row, col = divmod(idx, GRID_COLS)
                x = x0 + col * (CELL_W + CELL_GAP)
                y = top - CELL_H - row * (CELL_H + CELL_GAP)
                content.addSubview_(
                    self._make_cell(item, id_to_idx[id(item)],
                                    images.get(sections.item_key(item)), x, y))
    
        panel.setContentView_(content)
        self._position_panel(height)

    def _make_cell(self, item, index, image, x, y):
        """网格格子：**只有图标**（无位图时兜底图标顶上），名字只进悬停提示。"""
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, CELL_W, CELL_H))
        img = image if image is not None else capture.fallback_image_for_item(item)
        if img is not None:
            btn.setImage_(img)
        btn.setTitle_("")
        # 只有图、居中：原先写的 5 其实是 NSImageAbove（图在标题上方），
        # 空标题下图标被顶到格子上沿；NSImageOnly=1 才居中（t72 像素定位实测）
        btn.setImagePosition_(NSImageOnly)
        # 宽图标（网速/温度这类文字条）的宽度收口在 capture.fit_box：
        # 无边框 NSButton 不执行 imageScaling，这里只当兜底（值为 ProportionallyDown，
        # 写成 3 就变成 UpOrDown、会把小图撑满）
        btn.setImageScaling_(NSImageScaleProportionallyDown)
        # 不画按钮外形：rounded 胶囊会在图标后面垫一块灰底，违背「只显示图标」
        # （P42 截图实测：带 bezel 时格子四角与背景差 54，去掉后只剩毛玻璃本身）
        btn.setBordered_(False)
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
        # 身份标识用配置键（与设置窗口同一套）：图标名是活文本，不能当身份用
        btn.setAccessibilityIdentifier_(sections.item_key(item))
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

        触发走 trigger 的阶梯（T61/T66：AXPress → AXShowMenu → 坐标可信时补一次合成右键），
        并且丢后台跑：阶梯里全是跨进程等待（最坏 ~3s），卡在主线程会把面板和热键一起冻住。
        面板先收再触发：对方的菜单跟踪循环会占住主线程，面板不先收掉会一直悬在那儿。

        为什么不能只靠坐标：合成点击按 App 家族分裂（部分根本不吃），而被收纳的图标
        frame 不是画出来的位置（坐标点击 0/9），那一类只能靠 AXPress 投递。
        """
        idx = sender.tag()
        item = self.items[idx] if 0 <= idx < len(self.items) else None
        self.close()  # 先收面板：对方的菜单跟踪循环会占住主线程
        if item is None:
            return

        def done(how, seen):
            # 子线程回调：只写日志，不碰 UI
            print(f"[PeaseBar] 触发 {item.owner_app}/{item.label}"
                  f"{'（被收纳）' if item.stashed else ''}：{how}，反应={'有' if seen else '无'}")

        trigger.open_item_async(item, done)

    def toggle_stash(self):
        """展开/收起系统收纳区（F12，已移到控制图标右键菜单，面板本体不留按钮）：
        操作后作废位图缓存并刷新，面板开着就即时更新。"""
        inventory.set_stash_revealed(not inventory.stash_revealed())
        self.refresh_now()

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
