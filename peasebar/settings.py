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

拖拽（Phase 9 补上，对标 Thaw 布局编辑器）：按住格子拖 6pt 就起一次拖拽会话，
条内拖动改顺序，拖到另一个区就换区（与键盘 ⌥←/→、⌥↑/↓、底部按钮、右键菜单
共用同一套写入链与撤销栈）。为什么自己写 mouseDown 跟踪循环：NSButton 的
 mouseDown 会进 cell 自己的跟踪循环，view 的 mouseDragged 根本不会被调用；
左键自己圈事件，右键仍交给 super（T27：setMenu: 让系统自己弹，手弹不可靠）。

Phase 8（对标 Thaw Settings 窗）：侧栏加宽到 220pt 带 SF Symbol 图标与分组小标题；
布局页每区改成「区标题行（左区名 + 右排序钮）+ 横向单行图标条」，格子宽度随真实
裁图的宽高比伸缩；静态页设置项逐行 GroupBox 卡片化（左标题+副说明、右控件）。
Phase 9 再把拖拽提示、每区排序菜单、底部选项卡片（真实像素优先 / 图标条换行）
一并接上；宽图标不再拒收，同比例缩着完整显示（capture.scaled_copy）。

另含维持性设置：面板自动收回秒数（F5，通用页）、图标位图重抓与权限入口（疑难解答页）。
"""
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSDragOperationGeneric,
    NSDragOperationNone,
    NSDraggingItem,
    NSEventModifierFlagCommand,
    NSEventModifierFlagOption,
    NSEventTypeLeftMouseDown,
    NSFont,
    NSImage,
    NSImageLeading,
    NSImageOnly,
    NSImageScaleProportionallyDown,
    NSLineBreakByTruncatingTail,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPasteboard,
    NSPasteboardTypeString,
    NSProcessInfo,
    NSPopUpButton,
    NSScrollView,
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
from Foundation import (NSObject, NSMakePoint, NSMakeSize, NSString, NSURL)
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

# Phase 8 对标 Thaw：侧栏 220pt（图标+文字+分组小标题），内容区加宽
SIDEBAR_W = 220
CONTENT_W = 640
WIN_WIDTH = SIDEBAR_W + CONTENT_W
STATIC_H = 340
TILE_W, TILE_H = 44, 38
TILE_GAP = 4
EDGE = 16
ROW_H = 24
SECTION_H = 20
HEADER_H = 34
GAP = 12
# 布局页横向图标条高度（对标 Thaw 的 AXScrollArea 高 48，含胶囊上下留白）
BAR_H = 46
# 图标条胶囊内边距（上下 / 左右）与宽图标的格宽上限
BAR_PAD_Y, BAR_PAD_X = 4, 6
BAR_TILE_MAX_W = 110
# 选项卡片高（标题行 24 + 两行开关各 34，再留点底）
OPT_CARD_H = 96
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

# 侧栏 SF Symbol 图标（对标 Thaw：纯文字页签太素）；系统取不到符号时优雅降级为纯文字
_PAGE_ICONS = {"layout": "square.grid.2x2", "general": "gearshape",
               "shortcuts": "keyboard", "troubleshoot": "wrench.and.screwdriver",
               "about": "info.circle"}
# 侧栏分组小标题（对标 Thaw 的 MODULES/MANAGE）
_SIDEBAR_GROUPS = (("模块", ("layout", "general", "shortcuts")),
                   ("管理", ("troubleshoot", "about")))

# 拖拽：按下后移动多少点算「拖」（小于它当点击，T9 手感与系统一致）
DRAG_SLOP = 6.0
# 图标条换行时每格占高（格子高 + 行间距）
BAR_ROW_H = 38 + 4
# 布局页底部选项开关（存配置，重启后照旧）
_OPT_SWITCHES = (
    ("use_captured", "优先用菜单栏真实像素", "关掉后格子一律用 App 图标/系统符号，截图权限没给也长得整齐"),
    ("bar_wrap", "图标条放不下时换行", "开：整区图标一次看全（区会变高）；关：单行横向滚动"),
)

LOG_PATH = os.path.expanduser("~/Library/Logs/PeaseBar.log")
REPO_URL = "https://github.com/PeaseAPI/PeaseBar"


def _sidebar_symbol(name, label):
    """侧栏图标：把 15×15 的 SF 符号画进 23×15 的透明画布，右边 8pt 就是图文间距。

    NSButton 的 image/title 之间那段间距调不了（只给 2pt，看上去糊在一起），而把
    符号本身的 size 拉宽会连图标一起变形，所以拿透明画布垫出间距。
    取不到符号（系统降级）时返回 None，那一行就是纯文字，不比旧版差。
    """
    sym = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, label)
    if sym is None:
        return None
    sym.setSize_(NSMakeSize(15, 15))
    box = NSImage.alloc().initWithSize_(NSMakeSize(23, 15))
    if box is None:
        sym.setSize_(NSMakeSize(15, 15))
        return sym
    box.lockFocus()
    sym.drawInRect_(NSMakeRect(0, 0, 15, 15))
    box.unlockFocus()
    box.setTemplate_(True)  # 跟着 contentTintColor 走（选中白、未选灰）
    return box


def _chevron_symbol():
    """区标题行右侧那个「⌄」（更多排序）：拿不到 SF 符号时退成文字，不阻塞主流程。"""
    sym = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
        "chevron.down", "更多排序")
    if sym is None:
        return None
    sym.setSize_(NSMakeSize(10, 10))
    return sym


def _sort_menu(ctrl, sec):
    """每区的更多排序菜单（对标 Thaw 的 Sort ⌄）：反转本区 / 恢复默认顺序。

    tag 带两个信息：区下标×10 + 动作号（1=反转、2=恢复默认），处理端拆回；
    菜单项显式给 target，不靠响应链（T21）。
    """
    menu = NSMenu.alloc().init()
    menu.setAutoenablesItems_(False)
    idx = sections.SECTION_ORDER.index(sec)
    for kind, name in ((1, "反转本区顺序"), (2, "恢复默认顺序")):
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            name, "onSortMore:", "")
        mi.setTarget_(ctrl)
        mi.setTag_(idx * 10 + kind)
        menu.addItem_(mi)
    return menu


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
    """布局页的页视图：接住键盘，同时是整页唯一的拖拽落点。

    键盘：内容视图做 firstResponder，`keyDown:` 里判修饰键。**没有选中项或控制器不认
    这根键时一律交回 super**（系统该响铃响铃、该走焦点环走焦点环），
    绝不吞键 —— 否则输入框、快捷键回退都会莫名其妙失效。

    落点为什么在页视图而不是每条图标条：Phase 9 真机实测，一次拖拽会话里 AppKit
    只认「会话开始时从源视图往上找到的那一条」——鼠标拖到别的条上，那条的
    draggingEntered: 一次都不来（连 draggingSession:movedToPoint: 都在离开源条后停掉），
    于是跨区拖拽永远落不了地。页视图是所有条的祖先，从会话开始到结束都是同一个
    落点，落在哪一条、插到第几格由我们自己按坐标算（draggingLocation 在松手那一刻
    是准的：实测窗口坐标与释放点分毫不差）。
    """

    def acceptsFirstResponder(self):
        return True

    def keyDown_(self, event):
        ctrl = getattr(self, "settings_ctrl", None)
        if ctrl is None or not ctrl.handleKey_(event):
            objc.super(GridView, self).keyDown_(event)

    def viewDidMoveToWindow(self):
        # 注册落点类型要在进窗口之后：窗口未建时的注册不会报给窗口服务
        if self.window() is not None and getattr(self, "drop_bars", None):
            self.registerForDraggedTypes_([NSPasteboardTypeString])
        return objc.super(GridView, self).viewDidMoveToWindow()

    @objc.python_method
    def drop_key_from(self, sender):
        """拖拽里带的配置键；不是我们自己的格子（外部拖进来的文本）一律认作无效。"""
        ctrl = getattr(self, "settings_ctrl", None)
        if ctrl is None:
            return None
        pb = sender.draggingPasteboard()
        key = pb.stringForType_(NSPasteboardTypeString) if pb is not None else None
        if not key or str(key) not in ctrl.tiles:
            return None
        return str(key)

    @objc.python_method
    def bar_at(self, pt):
        """页视图坐标 pt 落在哪一条图标条里：返回 (条, 条内坐标)，不在任何条上返回 (None, None)。"""
        for frame, doc in (getattr(self, "drop_bars") or []):
            if (frame.origin.x <= pt.x < frame.origin.x + frame.size.width
                    and frame.origin.y <= pt.y < frame.origin.y + frame.size.height):
                return doc, doc.convertPoint_fromView_(pt, self)
        return None, None

    @objc.python_method
    def drop_target(self, sender):
        """把一次拖拽翻译成「哪一条 + 第几格」；键不对或落在条外就翻译不出来。"""
        if self.drop_key_from(sender) is None:
            return None
        pt = self.convertPoint_fromView_(sender.draggingLocation(), None)
        doc, inner = self.bar_at(pt)
        if doc is None:
            return None
        return doc, doc.drop_index_at_(inner)

    @objc.python_method
    def set_hot_bar(self, target):
        for _frame, doc in (getattr(self, "drop_bars") or []):
            doc._set_hot(target is not None and doc == target)

    def draggingEntered_(self, sender):
        target = self.drop_target(sender)
        self.set_hot_bar(target[0] if target else None)
        return NSDragOperationGeneric if target else NSDragOperationNone

    def draggingUpdated_(self, sender):
        target = self.drop_target(sender)
        self.set_hot_bar(target[0] if target else None)
        return NSDragOperationGeneric if target else NSDragOperationNone

    def draggingExited_(self, sender):
        self.set_hot_bar(None)
        return NSDragOperationNone

    def concludeDragOperation_(self, sender):
        self.set_hot_bar(None)

    def prepareForDragOperation_(self, sender):
        return self.drop_key_from(sender) is not None

    def performDragOperation_(self, sender):
        self.set_hot_bar(None)
        key = self.drop_key_from(sender)
        ctrl = getattr(self, "settings_ctrl", None)
        if key is None or ctrl is None:
            return False
        target = self.drop_target(sender)
        if target is None:
            return False
        doc, index = target
        return ctrl.applyDrop_key_toSection_atIndex_(key, doc.bar_section, index)


class FlippedView(NSView):
    """图标条的内容视图：左上原点。AppKit 默认 y 朝上，横排要从底部倒数，
    翻过来排「从左到右 + 上下居中」最直白。"""

    def isFlipped(self):
        return True


class TileButton(NSButton):
    """图标格子：在 NSButton 的点击之外多干一件事 —— 按住拖 6pt 起一次拖拽。

    为什么不在 mouseDown 里自己圈事件：nextEventMatchingMask 把后续事件从队列里
    抽干，窗口就不会再把这些事件交给拖拽会话，跨视图的落点命中测试从此不再更新
    —— 实测只会拖中「起点那一条」，落到别的条上一点反应都没有（同一条内改序却
    能用，因为落点一直是起点那条）。所以走系统正常派发：mouseDown: 只记起点
    （不进 cell 的 trackMouse，否则 mouseDragged: 永远收不到），过阈值在
    mouseDragged: 里起会话，没拖过阈值在 mouseUp: 里当一次点击；右键不拦，
    回系统 rightMouseDown: 弹 setMenu: 挂的移区菜单（T27/T41）。
    """

    def mouseDown_(self, event):
        ctrl = getattr(self, "settings_ctrl", None)
        if ctrl is None or event.type() != NSEventTypeLeftMouseDown:
            return objc.super(TileButton, self).mouseDown_(event)
        # 故意不调 super：进了 NSCell 的 trackMouse，mouseDragged: 就再也收不到
        self._drag_start = event.locationInWindow()
        self._drag_raised = False

    def mouseDragged_(self, event):
        ctrl = getattr(self, "settings_ctrl", None)
        start = getattr(self, "_drag_start", None)
        if ctrl is None or start is None or getattr(self, "_drag_raised", True):
            return
        p = event.locationInWindow()
        if abs(p.x - start.x) + abs(p.y - start.y) < DRAG_SLOP:
            return
        self._drag_raised = True
        self._drag_start = None
        ctrl.startTileDrag_withEvent_(self, event)  # 会话接手：往后的事件归它调度

    def mouseUp_(self, event):
        ctrl = getattr(self, "settings_ctrl", None)
        start, raised = getattr(self, "_drag_start", None), getattr(self, "_drag_raised", False)
        self._drag_start = None
        self._drag_raised = False
        if ctrl is None or raised or start is None:
            return  # 拖起来了（会话自己收尾）；或者压根不是我们从按下走到松手的
        ctrl.select_tile_(self)  # 没拖起来 = 一次点击（选中与高亮都走控制器这条路）


class BarDocView(FlippedView):
    """一条图标条的内容视图：格子们的主人。

    拖拽落点不在这个视图上（原因见 GridView 的注释），它只负责两件事：
    把「条内坐标」翻译成插入位，以及拖入时把胶囊底色亮一档。
    """

    def _set_hot(self, hot):
        scroll = self.enclosingScrollView()
        layer = scroll.layer() if scroll is not None else None
        if layer is None:
            return
        cg = (Quartz.CGColorCreateGenericRGB(0.42, 0.62, 1.0, 0.34) if hot
              else Quartz.CGColorCreateGenericRGB(0.55, 0.55, 0.58, 0.22))
        layer.setBackgroundColor_(cg)

    @objc.python_method
    def drop_index_at_(self, pt):
        """条内坐标 pt 对应的插入位（行/列数学抽到 drop_index_in_rows，单测能直接跑）。"""
        rects = [(v.frame().origin.x, v.frame().origin.y,
                  v.frame().size.width, v.frame().size.height)
                 for v in self.subviews() if isinstance(v, TileButton)]
        return drop_index_in_rows(rects, pt.x, pt.y)


# 同一行的 y 允许多大差：个别格子（Wi-Fi 那种小图标）会被报高/低 1~2pt
ROW_TOL = 6.0


def drop_index_in_rows(rects, x, y):
    """图标条里的插入位：rects 是各格子的 (x, y, 宽, 高)（条内坐标、左上原点），(x, y) 是落点。

    先按 y 把格子归成行（与行首 y 相差不超 ROW_TOL 算同一行），再在落点所在那一行
    里数「中心在它左边的格子」有几个。只按 x 排会串行：换行开时第二行的 x 与第一行
    重复，实测把第 3 格拖过去落到第 5 格就是这个坑。
    """
    if not rects:
        return 0
    rows = []
    for r in sorted(rects, key=lambda r: r[1]):
        if not rows or r[1] - rows[-1][0][1] > ROW_TOL:
            rows.append([r])
        else:
            rows[-1].append(r)
    base = 0
    for row in rows:
        top, h = min(r[1] for r in row), row[0][3]
        if y > top + h:
            base += len(row)  # 落点在这一行下面，整行跳过
            continue
        for i, r in enumerate(sorted(row, key=lambda r: r[0])):
            if x < r[0] + r[2] / 2.0:
                return base + i
        return base + len(row)  # 落在本行右侧末尾
    return base


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
        self.drag_key = None      # 正在拖的图标配置键（没拖时 None）
        self.use_captured = True  # 布局页选项：格子优先用真实截图像素
        self.bar_wrap = True      # 布局页选项：图标条装不下就换行而不是横向滚动
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
                         f"可在右键菜单「展开收纳区」找回，或选中后改为弹窗显示。")
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
        """各页内容高度：布局页随分区数变（每区只有一行图标条），静态页定高。"""
        if page != "layout":
            return STATIC_H
        h = EDGE + HEADER_H
        for sec in _SECTION_ORDER:
            if not buckets[sec]:
                continue
            h += SECTION_H + self._bar_height(buckets[sec]) + GAP
        # 拖拽提示行 + 选项卡片（Phase 9 新增，与 _build_layout_page 的排版一一对应）
        h += ROW_H + 4 + OPT_CARD_H + 8
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
        # 两个布局选项同步成标记：格子宽/高与取图都看它，一处读盘多处用
        self.use_captured = bool(cfg.get("use_captured", True))
        self.bar_wrap = bool(cfg.get("bar_wrap", True))
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
        """左侧页签列（对标 Thaw）：220pt 宽、SF Symbol 图标、
        分组小标题、32pt 行高 + 选中圆角垫底。

        图文排版就靠两件事（Phase 9 修好那个「文字贴左边、图标不知道跑哪去了」）：
        ① imagePosition 用 NSImageLeading（旧代码写了 6 = NSImageOverlaps，
           图标与文字重叠画在一起，看上去就是排版坏了）；
        ② 图文间距 NSButton 自己调不了（只给 2pt），所以把 15pt 的符号画进 23pt
           宽、右边透空的画布，那 8pt 就是间距（直接改符号尺寸会把图标拉变形）。
        """
        side = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, SIDEBAR_W, height))
        side.setMaterial_(NSVisualEffectMaterialSidebar)
        side.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        side.setState_(1)
        container.addSubview_(side)
        names = {k: name for k, name, _sub in PAGES}
        y = height - 14
        for group, keys in _SIDEBAR_GROUPS:
            cap = NSTextField.labelWithString_(group)
            cap.setFont_(NSFont.systemFontOfSize_(11))
            cap.setTextColor_(NSColor.tertiaryLabelColor())
            cap.setFrame_(NSMakeRect(16, y - 16, SIDEBAR_W - 32, 14))
            side.addSubview_(cap)
            y -= 22
            for key in keys:
                # 行左缩 10pt，图标从 x≈16 起，文字再退到 x≈39（Q72 判据：缩进 ≥12）
                btn = NSButton.alloc().initWithFrame_(NSMakeRect(10, y - 32, SIDEBAR_W - 20, 32))
                btn.setTitle_(names[key])
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
                sym = _sidebar_symbol(_PAGE_ICONS[key], names[key])
                if sym is not None:
                    btn.setImage_(sym)
                    btn.setImagePosition_(NSImageLeading)  # 图标在左、文字在右
                    btn.setImageHugsTitle_(True)           # 图文不留一段空白，挨着排
                    btn.setImageScaling_(NSImageScaleProportionallyDown)
                    btn.setContentTintColor_(NSColor.labelColor() if key == page
                                             else NSColor.secondaryLabelColor())
                btn.setTarget_(self)
                btn.setAction_("onPickPage:")
                btn.setRepresentedObject_(key)
                # 取证靠标识认页，不靠标题猜（标题日后可能本地化）
                btn.setAccessibilityIdentifier_("page-" + key)
                side.addSubview_(btn)
                y -= 34
            y -= 10

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
        content.drop_bars = []        # 拖拽落点：[(胶囊在页视图坐标下的矩形, 条内容视图), …]

        title = NSTextField.labelWithString_(
            "菜单栏布局 · 单击选中，拖动改位置，⌥←/→ 改顺序")
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
                # Thaw 的 Sort ⌄ ：多几个排序玩法（反转/恢复默认），同样写 order 可撤销
                mb = NSButton.alloc().initWithFrame_(
                    NSMakeRect(CONTENT_W - EDGE - 26, top - SECTION_H + 1, 26, 20))
                mb.setTitle_("")
                mb.setBezelStyle_(0)
                mb.setImage_(_chevron_symbol())
                mb.setImagePosition_(NSImageOnly)
                mb.setMenu_(_sort_menu(self, sec))
                mb.setAccessibilityLabel_(f"{sections.SECTION_LABELS[sec]}的更多排序")
                mb.setAccessibilityIdentifier_("sort-menu-" + sec)
                content.addSubview_(mb)
            top -= SECTION_H
            # Thaw 同款横向图标条（胶囊容器，真实裁图宽度可变，选项开则换行）
            bar_h = self._bar_height(group)
            top -= bar_h
            self._build_section_bar(content, group, sec, top, bar_h)
            top -= GAP

        # ---------- 底部（自上而下）：拖拽提示 / 提示行 / 选中提示 / 移区 / 顺序 / 选项 / 重置 ----------
        # 权限提醒与重抓、超时都搬到对应页（疑难解答/通用），这页只留编辑相关

        # 拖拽提示（对标 Thaw LayoutBarsSection 的 dragHint，翻成中文）：
        # 新界面得告诉用户「能拖」，不然没人知道鼠标按住图标可以动
        hint = NSTextField.labelWithString_(
            "把图标在区之间拖动即可换区，条内拖动改顺序；"
            "也可用 ⌥←/→ 改顺序、⌥↑/↓ 换区，⌘Z 撤销。")
        hint.setFont_(NSFont.systemFontOfSize_(11))
        hint.setTextColor_(NSColor.secondaryLabelColor())
        hint.setFrame_(NSMakeRect(EDGE, top - ROW_H, CONTENT_W - 2 * EDGE, ROW_H))
        hint.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
        content.addSubview_(hint)
        top -= ROW_H + 4

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
        kb = NSTextField.labelWithString_("拖动改位置 · ⌥←/→ 改顺序 · ⌥↑/↓ 换区 · ⌘Z 撤销")
        kb.setFont_(NSFont.systemFontOfSize_(10))
        kb.setTextColor_(NSColor.tertiaryLabelColor())
        kb.setAlignment_(2)  # 右对齐
        kb.setFrame_(NSMakeRect(x + 84, top - ROW_H, CONTENT_W - EDGE - x - 84, ROW_H))
        kb.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
        content.addSubview_(kb)
        top -= ROW_H + 8

        # 选项卡片（对标 Thaw 布局页的 Options）：能真的写进配置、影响渲染的开关才进来
        card = self._mk_card(content, top, OPT_CARD_H)
        cap = NSTextField.labelWithString_("选项")
        cap.setFont_(NSFont.boldSystemFontOfSize_(11))
        cap.setTextColor_(NSColor.secondaryLabelColor())
        cap.setFrame_(NSMakeRect(14, OPT_CARD_H - 24, 120, 16))
        card.addSubview_(cap)
        self.opt_switches = []
        for i, (flag, name, tip) in enumerate(_OPT_SWITCHES):
            row_y = OPT_CARD_H - 24 - (i + 1) * 34 + 6
            lab = NSTextField.labelWithString_(name)
            lab.setFont_(NSFont.systemFontOfSize_(12))
            lab.setFrame_(NSMakeRect(14, row_y + 6, 240, 18))
            card.addSubview_(lab)
            sub = NSTextField.labelWithString_(tip)
            sub.setFont_(NSFont.systemFontOfSize_(10))
            sub.setTextColor_(NSColor.tertiaryLabelColor())
            sub.setFrame_(NSMakeRect(14, row_y - 8, 380, 14))
            card.addSubview_(sub)
            sw = NSSwitch.alloc().initWithFrame_(
                NSMakeRect(CONTENT_W - 2 * EDGE - 74, row_y, 60, 28))
            sw.setState_(1 if self.opt(flag) else 0)
            sw.setTarget_(self)
            sw.setAction_("onOptionSwitch:")
            sw.setRepresentedObject_(flag)
            sw.setAccessibilityLabel_(name)
            sw.setAccessibilityIdentifier_("option-" + flag)
            card.addSubview_(sw)
            self.opt_switches.append(sw)
        top -= OPT_CARD_H + 8

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

    @objc.python_method
    def _build_section_bar(self, content, group, sec, top, bar_h=None):
        """Thaw LayoutBar 同款横向图标条：圆角胶囊容器 + 格子（单行或换行）。

        格子宽度按图标真实宽伸缩（菜单栏宽图标不再挤进正方形格子里留大片
        空隙，Thaw 靠这个把间距做得舒服）；换行关时超出条宽走横向滚动，不弹滚动条；
        换行开时按条宽拆成多行，整区一次看全（高随行数长，与 _bar_height 同源）。
        内容视图是 BarDocView：它同时是拖拽落点（同区改序 / 跨区换区）。
        """
        bar_w = CONTENT_W - 2 * EDGE
        pad = BAR_PAD_X
        rows = self._bar_rows(group)
        bar_h = bar_h or self._bar_height(group)
        doc_w = bar_w if self.bar_wrap else max(
            bar_w, max((sum(w for _, w in row) + TILE_GAP * (len(row) - 1) for row in rows),
                       default=0) + 2 * pad)
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(EDGE, top, bar_w, bar_h))
        scroll.setWantsLayer_(True)
        scroll.layer().setCornerRadius_(10.0)
        # 胶囊底色比窗口背景亮一档（Thaw 的 LayoutBar 对比度；0.10/0.16 在深色下几乎看不出）
        scroll.layer().setBackgroundColor_(Quartz.CGColorCreateGenericRGB(0.55, 0.55, 0.58, 0.22))
        scroll.setBorderType_(0)  # NSNoBorder：胶囊圆角由 layer 画，系统边框是直角方框
        scroll.setDrawsBackground_(False)  # 底色交给 layer 胶囊，系统白底会盖掉圆角
        scroll.setHasVerticalScroller_(False)
        scroll.setHasHorizontalScroller_(False)  # 项数不多，滚轮/触控板够用，不弹滚动条
        scroll.setAutomaticallyAdjustsContentInsets_(False)
        doc = BarDocView.alloc().initWithFrame_(NSMakeRect(0, 0, doc_w, bar_h))
        doc.settings_ctrl = self
        doc.bar_section = sec
        # 落点登记到页视图（整页只有一个落点，原因见 GridView）：页视图坐标下
        # 的胶囊矩形 + 它的内容视图，拖拽时按坐标反查「落在哪一条」
        getattr(content, "drop_bars", []).append((scroll.frame(), doc))
        for r, row in enumerate(rows):
            x = pad
            y = BAR_PAD_Y + r * (TILE_H + TILE_GAP)
            for item, w in row:
                doc.addSubview_(self._make_tile(item, sec, x, y, w))
                x += w + TILE_GAP
        scroll.setDocumentView_(doc)
        content.addSubview_(scroll)

    @objc.python_method
    def _bar_rows(self, group):
        """图标条的行拆分：每行是 [(item, 格宽), …]。

        换行关：一行到底（装不下就横向滚动）；换行开：按条宽折行，单个图标再宽
        也独占一行（不会因格子比条还宽而进死循环）。
        """
        avail = CONTENT_W - 2 * EDGE - 2 * BAR_PAD_X
        out, row, used = [], [], 0.0
        for item in group:
            w = self._bar_tile_width(sections.item_key(item))
            if self.bar_wrap and row and used + TILE_GAP + w > avail:
                out.append(row)
                row, used = [], 0.0
            row.append((item, w))
            used += w + TILE_GAP
        if row:
            out.append(row)
        return out or []

    @objc.python_method
    def _bar_height(self, group):
        """图标条高度（行高一算就定）：单行恰好等于旧版 BAR_H，不改变未换行时的外观。"""
        rows = self._bar_rows(group)
        if not rows:
            return BAR_H
        return 2 * BAR_PAD_Y + len(rows) * TILE_H + (len(rows) - 1) * TILE_GAP

    @objc.python_method
    def _bar_tile_width(self, key):
        """图标条格子宽度：按真实像素的宽伸缩，钳在合理区间里；
        没有位图（App 图标/系统符号兜底）时用默认格宽。

        旧版按「格高×宽高比」算，但图标本体只有 18pt 高、格子高 34，宽图标因此
        被估得很宽；Phase 9 直接用图自身的点宽加内边距，多少图占多少位。
        """
        img = self._tile_image_key(key)
        if img is None:
            return TILE_W
        return max(30, min(BAR_TILE_MAX_W, int(round(img.size().width)) + 12))

    @objc.python_method
    def _tile_image_key(self, key):
        """取图入口：选项「真实像素优先」关掉时当作没截到，直接走兜底链。"""
        if not self.use_captured:
            return None
        return self.images.get(key)

    @objc.python_method
    def _tile_image(self, item, max_w, max_h):
        """格子里那张图：真实像素优先，没截到用兜底，永远有图；
        再按格子大小同比例缩一份副本（不删像素、不改缓存原件，宽图也不半截）。"""
        key = sections.item_key(item)
        img = self._tile_image_key(key) or capture.fallback_image_for_item(item)
        return capture.scaled_copy(img, max_w, max_h)

    @objc.python_method
    def _make_tile(self, item, sec, x, y, w=None):
        """一个图标格子：**只有图标**（截取像素缺失时用兜底图标，绝不显示名字）。

        单击 = 选中（按钮切换态高亮）；右键 = 系统自动弹 setMenu: 挂的移区菜单（T27）；
        按住拖 6pt = 起拖拽会话（TileButton 自己圈事，落点由 BarDocView 接）。
        """
        btn = TileButton.alloc().initWithFrame_(NSMakeRect(x, y, w or TILE_W, TILE_H))
        btn.settings_ctrl = self
        key = sections.item_key(item)
        img = self._tile_image(item, (w or TILE_W) - 10, TILE_H - 10)
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
        """单击图标 = 选中（底部提示与移区按钮随之可用）。不再在这里手弹菜单。

        这条路现在主要给 AX 用（取证 AXPress 格子会直接发 action），
        鼠标点击走 TileButton.mouseDown:（它要兼顾「是不是拖」）。
        """
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

    @objc.python_method
    def select_tile_(self, tile):
        """鼠标左键在格子上松手（没拖起来）：与 action 同一条选中路。"""
        self.onTileClick_(tile)

    # ---------- 拖拽（源与落点共用一套写入链） ----------

    @objc.python_method
    def startTileDrag_withEvent_(self, tile, event):
        """把按住的格子变成一次拖拽会话：pasteboard 里只放配置键。

        只放键不放自定义类型：外部 App 拖一段文本进来时 _drag_key_from 对不上我们的格子，
        自然就接不了（不会因为收到野字符串就把图标搬走）。会话自带RunLoop，
        返回时拖拽已经结束，这里只需把拖动中的格子恢复平静。
        """
        key = str(tile.representedObject())
        drag_item = NSDraggingItem.alloc().initWithPasteboardWriter_(
            NSString.stringWithString_(key))
        img = tile.image()
        if drag_item is None:
            return
        try:
            drag_item.setDraggingFrame_contents_(tile.bounds(), img)
        except Exception:  # 旧系统签名不一致时退位：没拖影也能拖，不能因它报错
            pass
        self.drag_key = key
        session = tile.beginDraggingSessionWithItems_event_source_([drag_item], event, self)
        # 日志是取证唯一能看出「拖到底没起会话」的地方（探针看不到拖影）
        print(f"[PeaseBar] 起拖：{key} 会话={'有' if session is not None else '无'}")
        if session is not None:
            session.setAnimatesRelease_(True)
        self.drag_key = None

    def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
        """拖拽源：只在自家窗口内搬（拖到桌面/其他 App 不给落点）。"""
        return NSDragOperationGeneric

    def draggingSession_endedAtPoint_operation_(self, session, location, operation):
        """会话结束（NSDraggingSource 的回调）：只用来收掉拖动中的键。"""
        self.drag_key = None

    @objc.python_method
    def applyDrop_key_toSection_atIndex_(self, key, target, index):
        """拖拽落位：一次写定「换哪个区 + 插到第几格」，同样进撤销栈。

        与 applyMove_to_ 的分工：那个只把项抻到目标区末尾（按钮/⌥↑↓/⌘123 用），
        拖拽多了「落在哪两格之间」这一维；算完新分桶与原桶完全一致就当没动过，
        不写盘也不记撤销点（否则原地拖一下就把 ⌘Z 堵了一层）。
        """
        if not key or target is None:
            return False
        cfg = sections.load_config()
        buckets = sections.plan_sections(self.items, cfg)
        pos = sections.find_pos(buckets, key)
        item = self._item_by_key(key)
        if pos is None or item is None:
            return False
        new = {s: list(buckets[s]) for s in _SECTION_ORDER}
        src_sec, _idx = pos
        if src_sec == target:
            new[target] = sections.move_to_index(buckets[target], sections.item_key, key, index)
        else:
            new[src_sec] = [it for it in buckets[src_sec] if sections.item_key(it) != key]
            joined = list(buckets[target]) + [item]  # 不在目标区时先挂尾，再按落点插
            new[target] = sections.move_to_index(joined, sections.item_key, key, index)
        if all(new[s] == buckets[s] for s in _SECTION_ORDER):
            return False  # 落回原位：不算改动
        self._push_undo(cfg)
        sections.set_section(cfg, key, target)
        sections.store_order(cfg, sections.flatten(new))
        sections.save_config(cfg)
        self.selected_key = key  # 拖完就是选中，底部提示与按钮立即可用
        self.buckets = new
        self._rebuild()
        if self.on_changed:
            self.on_changed()
        print(f"[PeaseBar] 设置：拖动 {key} → {sections.SECTION_LABELS[target]} "
              f"第 {min(index, len(new[target]))} 格")
        return True

    # ---------- 布局页选项（真实像素优先 / 图标条换行） ----------

    @objc.python_method
    def opt(self, flag):
        """读布局选项（只在 _rebuild 同步下来的两个标记上取值，不二次读盘）。"""
        return bool(getattr(self, flag, True))

    def onOptionSwitch_(self, sender):
        """选项开关：写盘后整窗重建（换行会改窗高，真实像素会改格子里的图）。"""
        flag = str(sender.representedObject())
        on = sender.state() == 1
        cfg = sections.load_config()
        cfg[flag] = on
        sections.save_config(cfg)
        if flag == "use_captured" and on and not self.images:
            self._reload_items()  # 开关拉回真实像素但手上没货：补一次取图
        print(f"[PeaseBar] 设置：选项 {flag} = {on}")
        self._rebuild()
        if self.on_changed:
            self.on_changed()

    def onSortMore_(self, sender):
        """排序菜单项：反转本区 / 恢复默认顺序（都走 order 写入，⌘Z 可撤）。"""
        sec = _TAG_SECTIONS.get(sender.tag() // 10)
        kind = sender.tag() % 10
        if sec is None:
            return
        cfg = sections.load_config()
        buckets = sections.plan_sections(self.items, cfg)
        group = buckets[sec]
        if len(group) < 2:
            return
        self._push_undo(cfg)
        if kind == 1:      # 反转本区
            buckets[sec] = list(reversed(group))
        else:              # 恢复默认：清掉本区记录的顺序，回到盘点时的菜单栏序
            keys = {sections.item_key(it) for it in group}
            cfg["order"] = [k for k in cfg.get("order") or [] if k not in keys]
            buckets = sections.plan_sections(self.items, cfg)
        sections.store_order(cfg, sections.flatten(buckets))
        sections.save_config(cfg)
        self.buckets = buckets
        self._rebuild()
        if self.on_changed:
            self.on_changed()

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

    @objc.python_method
    def _mk_card(self, view, top, h):
        """Thaw GroupBox 同款卡片：圆角浅底分组，调用方把内容摆进卡片。

        卡片是普通坐标（左下原点），内部布局按「标题左、控件右」约定；
        卡片里全是静态文本/原控件，AX 角色与判据和平铺时一致，取证不用改。
        """
        card = NSView.alloc().initWithFrame_(
            NSMakeRect(EDGE, top - h, CONTENT_W - 2 * EDGE, h))
        card.setWantsLayer_(True)
        card.layer().setCornerRadius_(8.0)
        card.layer().setBackgroundColor_(Quartz.CGColorCreateGenericRGB(0.5, 0.5, 0.5, 0.10))
        view.addSubview_(card)
        return card

    def _page_general(self, view, top):
        """通用页（Phase 8 对标 Thaw）：每项设置一张卡片行，左标题+副说明、右控件。"""
        cw = CONTENT_W - 2 * EDGE
        y = top
        # 开机自启：NSSwitch 画 macOS 原生拨动开关（Thaw Toggle 同款），
        # 标题/状态行在左：开关本体不带 title，取证签名落在文本与标识上才稳
        card = self._mk_card(view, y, 56)
        lab = NSTextField.labelWithString_("登录时启动 PeaseBar")
        lab.setFont_(NSFont.systemFontOfSize_(12))
        lab.setFrame_(NSMakeRect(14, 32, 260, 18))
        card.addSubview_(lab)
        self.lbl_launch_status = NSTextField.labelWithString_("")
        self.lbl_launch_status.setFont_(NSFont.systemFontOfSize_(11))
        self.lbl_launch_status.setTextColor_(NSColor.secondaryLabelColor())
        self.lbl_launch_status.setFrame_(NSMakeRect(14, 12, cw - 96, 16))
        card.addSubview_(self.lbl_launch_status)
        self.chk_launch = NSSwitch.alloc().initWithFrame_(NSMakeRect(cw - 74, 14, 60, 28))
        self.chk_launch.setTarget_(self)
        self.chk_launch.setAction_("onLaunchToggle:")
        self.chk_launch.setAccessibilityLabel_("登录时启动 PeaseBar")
        self.chk_launch.setAccessibilityIdentifier_("launch-at-login")
        card.addSubview_(self.chk_launch)
        y -= 66
        # 面板自动收回：标题左，数字输入框右
        card = self._mk_card(view, y, 44)
        lbl_to = NSTextField.labelWithString_("面板自动收回（秒，0=不超时）")
        lbl_to.setFont_(NSFont.systemFontOfSize_(12))
        lbl_to.setFrame_(NSMakeRect(14, 13, 300, 18))
        card.addSubview_(lbl_to)
        cfg = sections.load_config()
        self.field_timeout = NSTextField.alloc().initWithFrame_(
            NSMakeRect(cw - 114, 9, 64, 26))
        self.field_timeout.setStringValue_(str(int(cfg.get("panel_timeout", 8))))
        self.field_timeout.setEditable_(True)
        self.field_timeout.setTarget_(self)
        self.field_timeout.setAction_("onTimeoutChanged:")
        card.addSubview_(self.field_timeout)
        y -= 54
        # 菜单栏控制图标：标题左，下拉右（pullsDown=False：选中项显示在钮体内，
        # 取证读 stringValue 即当前预设）
        card = self._mk_card(view, y, 44)
        lbl_ic = NSTextField.labelWithString_("菜单栏控制图标")
        lbl_ic.setFont_(NSFont.systemFontOfSize_(12))
        lbl_ic.setFrame_(NSMakeRect(14, 13, 300, 18))
        card.addSubview_(lbl_ic)
        self.popup_icon = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(cw - 194, 7, 180, 30), False)
        for _sym, name in sections.CONTROL_ICONS:
            self.popup_icon.addItemWithTitle_(name)
        cur = next((i for i, (k, _) in enumerate(sections.CONTROL_ICONS)
                    if k == cfg.get("control_icon")), 0)
        self.popup_icon.selectItemAtIndex_(cur)
        self.popup_icon.setTarget_(self)
        self.popup_icon.setAction_("onControlIconChanged:")
        self.popup_icon.setAccessibilityIdentifier_("control-icon-picker")
        card.addSubview_(self.popup_icon)
        self._sync_launch_state()

    def _page_shortcuts(self, view, top):
        """快捷键页：每根键一张卡片行（文本保持「⌥⌘B　说明」一体，取证前缀判据不动）。"""
        y = top
        for text in ("⌥⌘B　开关救援面板", "⌥⌘S　打开设置窗口"):
            card = self._mk_card(view, y, 44)
            lab = NSTextField.labelWithString_(text)
            lab.setFont_(NSFont.systemFontOfSize_(12))
            lab.setFrame_(NSMakeRect(14, 13, CONTENT_W - 2 * EDGE - 28, 18))
            card.addSubview_(lab)
            y -= 54
        self._mk_label(view, EDGE, y - ROW_H, "快捷键注册即全局生效（需辅助功能权限）；"
                                      "自定义录制键排在后续版本，这里不放假按钮")

    def _page_troubleshoot(self, view, top):
        ax_ok = bool(AXIsProcessTrusted())
        rec_ok = bool(capture.has_screen_permission())
        y = self._perm_row(view, top, "辅助功能（全局快捷键/读取图标）", ax_ok)
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

    def _perm_row(self, view, top, name, ok):
        """权限卡片行（Thaw 同款）：左项目名、右彩色状态文本。"""
        cw = CONTENT_W - 2 * EDGE
        card = self._mk_card(view, top, 44)
        lab = NSTextField.labelWithString_(name)
        lab.setFont_(NSFont.systemFontOfSize_(12))
        lab.setFrame_(NSMakeRect(14, 13, cw - 140, 18))
        card.addSubview_(lab)
        st = NSTextField.labelWithString_("✓ 已授权" if ok else "✗ 未授权")
        st.setFont_(NSFont.systemFontOfSize_(12))
        st.setTextColor_(NSColor.labelColor() if ok else NSColor.systemRedColor())
        st.setAlignment_(2)  # 右对齐
        st.setFrame_(NSMakeRect(cw - 120, 13, 106, 18))
        card.addSubview_(st)
        return top - 54

    def _page_about(self, view, top):
        """关于页：版本+一句话介绍一张卡片，按钮在卡片下（取证靠「版本 x.y.z」文本）。"""
        from peasebar import __version__
        cw = CONTENT_W - 2 * EDGE
        card = self._mk_card(view, top, 64)
        v = NSTextField.labelWithString_(f"版本 {__version__}")
        v.setFont_(NSFont.boldSystemFontOfSize_(13))
        v.setFrame_(NSMakeRect(14, 38, 200, 18))
        card.addSubview_(v)
        d = NSTextField.labelWithString_("把被刘海遮挡、被系统收纳的菜单栏图标找回来，并一键触发。")
        d.setFont_(NSFont.systemFontOfSize_(11))
        d.setTextColor_(NSColor.secondaryLabelColor())
        d.setFrame_(NSMakeRect(14, 14, cw - 28, 18))
        card.addSubview_(d)
        y = top - 74
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
