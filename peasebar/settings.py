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
    NSSegmentedControl,
    NSSlider,
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
from AppKit import (NSApplication, NSFontAttributeName,
                    NSAppearance,
                    NSStringDrawingUsesLineFragmentOrigin,
                    NSStringDrawingUsesFontLeading)
import os
import platform
import time

import objc
import Quartz
from ApplicationServices import AXIsProcessTrusted

import ServiceManagement as SM

from peasebar import capture, ccnative, i18n, inventory, layout_table, menubar_drag, panel, sections
from peasebar.i18n import t as tr

# 方向键的 keyCode（AppKit 的 NS*ArrowFunctionKey 取值，写数字谁也看不懂）
KEY_LEFT, KEY_RIGHT, KEY_DOWN, KEY_UP = 123, 124, 125, 126

# Phase 8 对标 Thaw：侧栏 220pt（图标+文字+分组小标题），内容区加宽
SIDEBAR_W = 220
CONTENT_W = 640
WIN_WIDTH = SIDEBAR_W + CONTENT_W
STATIC_H = 560
# 窗口最小高：侧栏现在 12 行页签 + 两个分组小标题，得给它留够高度（否则底部页签被截）
MIN_WIN_H = 560
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
# 选项卡片高（标题行 24 + 三行开关各 34，再留点底）
OPT_CARD_H = 142
# 布局页底部固定行数：选中提示 + 移区按钮 + 顺序按钮 + 重置行
BOTTOM_ROWS = 4
# 撤销栈深度（一次编辑只存两个小列表，50 步足够找回手滑，也不会吃掉多少内存）
UNDO_LIMIT = 50

# 区 → 移区菜单/按钮文案（三区语义对齐 Thaw：菜单栏显示 / 弹窗显示 / 永久隐藏）。
# 2026-11-24 多语言：模块级常量在 import 时求值会冻结语言，文案表一律函数化，
# 每次构建界面时现取（t() 带进程内语言缓存，开销可忽略）。
def _move_titles():
    return {
        sections.SECTION_VISIBLE: tr("move.visible"),
        sections.SECTION_HIDDEN: tr("move.hidden"),
        sections.SECTION_ALWAYS_HIDDEN: tr("move.always"),
    }
_SECTION_ORDER = sections.SECTION_ORDER
_TAG_SECTIONS = {0: sections.SECTION_VISIBLE, 1: sections.SECTION_HIDDEN,
                 2: sections.SECTION_ALWAYS_HIDDEN}

# 侧栏页签键（显示名/副标题进 i18n 表，pages() 运行时现取）；key 也写进侧栏
# 按钮的 AXIdentifier 供取证认页。
# 只留真实生效的功能页（2026-11-24 收缩：外观/工具栏/显示器/模块四页的后端从未
# 实现，摆着只会让用户拨了没反应——宁少勿假）；visibility 页改为展示真实
# 隐藏通道状态与自动核对开关，about 页不再提 Thaw（代码已全部自有，仅仿其 UI 观感）。
PAGE_KEYS = ("general", "layout", "visibility", "shortcuts",
             "profiles", "privacy", "troubleshoot", "about")


def pages():
    """侧栏页签 (key, 显示名, 副标题)：随语言切换现取，不在 import 时冻结。"""
    return tuple((k, tr(f"page.{k}"), tr(f"page.{k}.sub")) for k in PAGE_KEYS)

# 侧栏 SF Symbol 图标（取不到符号时优雅降级为纯文字）
_PAGE_ICONS = {"general": "gearshape", "layout": "square.grid.2x2",
               "visibility": "eye", "shortcuts": "keyboard",
               "profiles": "square.stack.3d.up", "privacy": "lock.shield",
               "troubleshoot": "wrench.and.screwdriver", "about": "info.circle"}
# 侧栏分组：首组无小标题（_build_sidebar 见空串就不画小标题行），「管理」收工具性页面
def _sidebar_groups():
    return (("", ("general", "layout", "visibility", "shortcuts")),
            (tr("group.manage"), ("profiles", "privacy", "troubleshoot", "about")))

# 拖拽：按下后移动多少点算「拖」（小于它当点击，T9 手感与系统一致）
DRAG_SLOP = 6.0
# 图标条换行时每格占高（格子高 + 行间距）
BAR_ROW_H = 38 + 4
# 布局页底部选项开关（存配置，重启后照旧；文案随语言现取）
def _opt_switches():
    return (
        ("use_captured", tr("opt.use_captured"), tr("opt.use_captured.tip")),
        ("bar_wrap", tr("opt.bar_wrap"), tr("opt.bar_wrap.tip")),
        ("real_bar", tr("opt.real_bar"), tr("opt.real_bar.tip")),
    )

LOG_PATH = os.path.expanduser("~/Library/Logs/PeaseBar.log")
REPO_URL = "https://github.com/PeaseAPI/PeaseBar"

# ---------- 行/块声明工厂（1:1 对标 Thaw 设置页，供各 _spec_* 拼装） ----------
# 返回的都是普通 dict，由 _render_blocks / _draw_ctl 解读。


def _row_switch(key, title, help=None):
    return {"title": title, "help": help, "ctl": ("switch", key)}


def _row_popup(key, title, options, help=None):
    return {"title": title, "help": help, "ctl": ("popup", key, list(options))}


def _row_seg(key, title, options, help=None):
    return {"title": title, "help": help, "ctl": ("segmented", key, list(options))}


def _row_tgl(title, items, help=None):
    # items: [(label, pref_key, tip)]，对标 Thaw CheckBox[Toggle] 组
    return {"title": title, "help": help, "ctl": ("toggles", list(items))}


def _row_slider(key, title, mn, mx, unit="", help=None):
    return {"title": title, "help": help, "ctl": ("slider", key, mn, mx, unit)}


def _row_text(key, title, placeholder="", help=None):
    return {"title": title, "help": help, "ctl": ("text", key, placeholder)}


def _row_buttons(title, items, help=None):
    # items: [(label, action_sel)] / [(label, action_sel, width)] / [(label, action_sel, width, rep)]
    return {"title": title, "help": help, "ctl": ("buttons", list(items))}


def _row_status(title, ok, text, help=None):
    return {"title": title, "help": help, "ctl": ("status", ok, text)}


def _row_launch(title=None, help=None):
    # 默认标题在调用时现取（写作默认参数会在 import 时冻结语言）
    return {"title": title or tr("launch.title"), "help": help, "ctl": ("launch",)}


def _row_timeout(title=None, help=None):
    return {"title": title or tr("timeout.title"), "help": help, "ctl": ("timeout",)}


def _row_cicon(title=None, help=None):
    return {"title": title or tr("cicon.caption"), "help": help, "ctl": ("control_icon",)}


def _block(heading, rows):
    return {"heading": heading, "rows": rows}


def _para(text):
    return {"para": text}


def _tabbar(page, options):
    return {"tabbar": True, "page": page, "options": list(options)}



def _sidebar_symbol(name, label):
    """侧栏图标：把 15×15 的 SF 符号画进 33×15 的透明画布——左留 10pt 让图标
    离选中框左缘远一点（用户批评贴边难看），右边 8pt 仍是图文间距。

    NSButton 的 image/title 之间那段间距调不了（只给 2pt，看上去糊在一起），而把
    符号本身的 size 拉宽会连图标一起变形，所以拿透明画布垫出间距。
    取不到符号（系统降级）时返回 None，那一行就是纯文字，不比旧版差。
    """
    sym = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, label)
    if sym is None:
        return None
    sym.setSize_(NSMakeSize(15, 15))
    box = NSImage.alloc().initWithSize_(NSMakeSize(33, 15))
    if box is None:
        sym.setSize_(NSMakeSize(15, 15))
        return sym
    box.lockFocus()
    sym.drawInRect_(NSMakeRect(10, 0, 15, 15))  # 左留 10pt：不再贴选中框左缘
    box.unlockFocus()
    box.setTemplate_(True)  # 跟着 contentTintColor 走（选中白、未选灰）
    return box


def _chevron_symbol():
    """区标题行右侧那个「⌄」（更多排序）：拿不到 SF 符号时退成文字，不阻塞主流程。"""
    sym = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
        "chevron.down", tr("layout.sort.more"))
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
    for kind, name in ((1, tr("layout.sort.reverse")), (2, tr("layout.sort.resetorder"))):
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            name, "onSortMore:", "")
        mi.setTarget_(ctrl)
        mi.setTag_(idx * 10 + kind)
        menu.addItem_(mi)
    return menu


# SMAppService 状态码 → (开关是否显示为已开, 给用户的说明)（文案随语言现取）
def _login_status():
    return {
        int(SM.SMAppServiceStatusNotRegistered): (False, tr("login.off")),
        int(SM.SMAppServiceStatusEnabled): (True, tr("login.on")),
        int(SM.SMAppServiceStatusRequiresApproval): (
            True, tr("login.approval")),
        int(SM.SMAppServiceStatusNotFound): (
            False, tr("login.notfound")),
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
        self.use_captured = False  # 布局页选项：默认用 App 图标（真实像素会把未读数等拍进格子）
        self.bar_wrap = True      # 布局页选项：图标条装不下就换行而不是横向滚动
        self.real_bar = True      # 布局页选项：换区/改序镜像到真实菜单栏（合成 ⌘-拖）
        self.buckets = {}     # 最近一次 _rebuild 的分桶结果（键盘编辑读它，不二次盘点）
        self._undo = []       # 撤销栈：每格是 {sections, order} 快照
        # 布局草稿（暂存+应用模式，2026-11-24 用户定调「编辑完点应用立刻生效」）：
        # 首次编辑把盘上配置拍成工作副本，之后所有编辑都落在副本上；点「应用改动」
        # 才写盘并一次性贴回真实菜单栏。None = 没有未应用改动。
        self._pending_cfg = None
        self._applying = False  # 应用流程后台部分进行中（防重入 + 按钮转忙）
        self.on_changed = None  # 分区/超时变更后回调（app 用来刷新面板）
        self.on_control_icon_changed = None  # 触发图标预设变更后回调（app 接 ControlItem.refresh_icon）
        return self

    # ---------- 布局草稿（暂存+应用模式，2026-11-24 用户定调） ----------

    @objc.python_method
    def _layout_cfg(self):
        """布局编辑的工作配置：有草稿用草稿副本，否则读盘（_rebuild/盘点同源）。"""
        if getattr(self, "_pending_cfg", None) is not None:
            return self._pending_cfg
        return sections.load_config()

    @objc.python_method
    def _begin_pending(self):
        """首次编辑把盘上配置拍成草稿副本；之后所有编辑都落在副本上，应用才落盘。"""
        if getattr(self, "_pending_cfg", None) is None:
            self._pending_cfg = sections.load_config()

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
        # 取证钩子：PEASEBAR_OPEN_PAGE=<页键> 直接开到指定页——真机截页时
        # 免去辅助功能权限（CGEvent/AX 点击在沙箱里都会被系统静默丢弃）
        forced = os.environ.get("PEASEBAR_OPEN_PAGE", "")
        if forced and any(k == forced for k, _l, _s in pages()):
            self.page = forced
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
        # 原生通道（isAllowed=false）藏起的图标不进 AX 盘点（MenuBarAgent 不再
        # 暴露它）：补伪项进布局页，否则「弹窗显示」区在设置里是空的，用户想
        # 调整已藏图标（显回/移到永久隐藏）根本找不到入口（与救援面板同口径）
        self.items = self.items + panel.native_hidden_items(
            self.items, self._layout_cfg())  # 草稿在编辑期也跟着布局页显示
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
            hints.append(tr("hint.stashed", n=self.stashed_count))
        if self.notched_count:
            hints.append(tr("hint.notched", n=self.notched_count))
        # 有权限却一张真像素都没截到 = 菜单栏此刻没画出来（全屏 App 遮住）。
        # 不说清楚的话，用户只会看到一屏「不像本人」的 App 图标又找不到原因（T76）。
        if not self.stats["cropped"] and self.stats["permission"] and not self.stats["bar_drawn"]:
            hints.append(tr("hint.nobar"))
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
        # 有未应用的布局草稿：关窗视为「确认应用」（半路关窗把草稿静默丢掉更伤——
        # 落盘+后台生效，与点「应用改动」按钮走同一条链路）
        if getattr(self, "_pending_cfg", None) is not None and not self._applying:
            print("[PeaseBar] 设置：关窗时有未应用改动，自动应用")
            self.onApplyLayout_(None)

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
        cfg = self._layout_cfg()  # 有布局草稿时按草稿分桶（所见即所得），否则读盘
        buckets = sections.plan_sections(self.items, cfg)
        self.buckets = buckets  # 键盘编辑（⌥方向键/前移后移）就在这份分桶上动手
        # 三个布局选项同步成标记：格子宽/高、取图、真实菜单栏镜像都看它，一处读盘多处用
        self.use_captured = bool(cfg.get("use_captured", False))
        self.bar_wrap = bool(cfg.get("bar_wrap", True))
        self.real_bar = bool(cfg.get("real_bar", True))
        self.tiles = {}
        self.move_buttons = []
        self.order_buttons = []
        self.field_timeout = None  # 切页即失效，_save_timeout 的空判据此生效
        self.popup_icon = None     # 同上：触发图标下拉也随旧内容丢弃
        page = getattr(self, "page", "layout")
        # 内容高度随分区变；窗高给侧栏 12 行页签兑底（MIN_WIN_H），不够高的页拉到此高
        height = max(MIN_WIN_H, self._page_height(page, buckets))

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

        label = next(l for k, l, _ in pages() if k == page)
        # 有未应用草稿时标题挂点提醒（前缀「PeaseBar 设置」不动，找窗判据不变）
        dirty = " ●" if getattr(self, "_pending_cfg", None) is not None else ""
        self.window.setTitle_(f"PeaseBar 设置 · {label}{dirty}")  # 前缀「PeaseBar 设置」不变，找窗判据不动
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
        names = {k: name for k, name, _sub in pages()}
        y = height - 14
        for group, keys in _sidebar_groups():
            if group:  # 空串标题的首组不画小标题行（对标 Thaw：顶部页签前无分组名）
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
        """非布局页：顶部固定「页名 + 副标题」，下方一个纵向滚动区，内容
        由通用块渲染引擎按 _spec_<page>() 返回的声明式块列表 1:1 排（对标 Thaw 的 ScrollArea）。
        """
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, CONTENT_W, height))
        label, sub = next((l, s) for k, l, s in pages() if k == page)
        t = NSTextField.labelWithString_(label)
        t.setFont_(NSFont.boldSystemFontOfSize_(15))
        t.setFrame_(NSMakeRect(EDGE, height - 34, CONTENT_W - 2 * EDGE, 24))
        view.addSubview_(t)
        s2 = NSTextField.labelWithString_(sub)
        s2.setFont_(NSFont.systemFontOfSize_(11))
        s2.setTextColor_(NSColor.secondaryLabelColor())
        s2.setFrame_(NSMakeRect(EDGE, height - 54, CONTENT_W - 2 * EDGE, 18))
        view.addSubview_(s2)
        # 滚动区铺满标题以下区域；document 用翻转视图，块从顶部往下排
        viewport_h = height - 62
        sv = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, CONTENT_W, viewport_h))
        sv.setBorderType_(0)
        sv.setHasVerticalScroller_(True)
        sv.setHasHorizontalScroller_(False)
        sv.setDrawsBackground_(False)
        sv.setAutohidesScrollers_(True)
        doc = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, CONTENT_W, viewport_h))
        used = self._render_blocks(doc, getattr(self, "_spec_" + page)())
        doc.setFrame_(NSMakeRect(0, 0, CONTENT_W, max(used, viewport_h)))
        doc.setFrameSize_(NSMakeSize(CONTENT_W, max(used, viewport_h)))
        sv.setDocumentView_(doc)
        view.addSubview_(sv)
        return view

    # ---------- 布局页（4d 编辑本体原样搬入，宽度改为 CONTENT_W） ----------

    def _build_layout_page(self, buckets, height):
        # 页视图用 GridView：它是窗口的 firstResponder，方向键才能进到我们手里
        content = GridView.alloc().initWithFrame_(NSMakeRect(0, 0, CONTENT_W, height))
        content.settings_ctrl = self  # 方向键转发给控制器（不起 controller 这个名字，避开与 AppKit 同名属性撞车）
        content.drop_bars = []        # 拖拽落点：[(胶囊在页视图坐标下的矩形, 条内容视图), …]

        title = NSTextField.labelWithString_(tr("layout.title"))
        title.setFont_(NSFont.boldSystemFontOfSize_(13))
        title.setFrame_(NSMakeRect(EDGE, height - HEADER_H, CONTENT_W - 2 * EDGE, ROW_H))
        content.addSubview_(title)
        top = height - HEADER_H

        for sec in _SECTION_ORDER:
            group = buckets[sec]
            if not group:
                continue
            label = NSTextField.labelWithString_(
                tr("layout.count", sec=sections.section_label(sec), n=len(group)))
            label.setFont_(NSFont.boldSystemFontOfSize_(11))
            label.setTextColor_(NSColor.secondaryLabelColor())
            label.setFrame_(NSMakeRect(EDGE, top - SECTION_H,
                                       CONTENT_W - 2 * EDGE - 100, SECTION_H))
            content.addSubview_(label)
            if len(group) > 1:
                # Thaw 每区的「Sort by Name」：点一下把该区按名字典序写进 order（⌘Z 可撤）
                sb = NSButton.alloc().initWithFrame_(
                    NSMakeRect(CONTENT_W - EDGE - 92, top - SECTION_H + 1, 92, 20))
                sb.setTitle_(tr("layout.sort.byname"))
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
                mb.setAccessibilityLabel_(
                    tr("layout.sort.more.ax", sec=sections.section_label(sec)))
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
        hint = NSTextField.labelWithString_(tr("layout.hint.drag"))
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
        move_titles = _move_titles()
        for idx, sec in enumerate(_SECTION_ORDER):
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, top - ROW_H, 116, ROW_H))
            btn.setTitle_(move_titles[sec])
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
        for label, delta in ((tr("layout.prev"), -1), (tr("layout.next"), 1)):
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
        btn_undo.setTitle_(tr("layout.undo"))
        btn_undo.setBezelStyle_(0)
        btn_undo.setFont_(NSFont.systemFontOfSize_(11))
        btn_undo.setEnabled_(bool(self._undo))
        btn_undo.setTarget_(self)
        btn_undo.setAction_("onUndo")  # onUndo 是零参方法，选择子不带冒号
        content.addSubview_(btn_undo)
        btn_undo.setToolTip_(tr("layout.undo.tip"))
        self.btn_undo = btn_undo
        kb = NSTextField.labelWithString_(tr("layout.kb"))
        kb.setFont_(NSFont.systemFontOfSize_(10))
        kb.setTextColor_(NSColor.tertiaryLabelColor())
        kb.setAlignment_(2)  # 右对齐
        kb.setFrame_(NSMakeRect(x + 84, top - ROW_H, CONTENT_W - EDGE - x - 84, ROW_H))
        kb.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
        content.addSubview_(kb)
        top -= ROW_H + 8

        # 选项卡片（对标 Thaw 布局页的 Options）：能真的写进配置、影响渲染的开关才进来
        card = self._mk_card(content, top, OPT_CARD_H)
        cap = NSTextField.labelWithString_(tr("layout.opt.caption"))
        cap.setFont_(NSFont.boldSystemFontOfSize_(11))
        cap.setTextColor_(NSColor.secondaryLabelColor())
        cap.setFrame_(NSMakeRect(14, OPT_CARD_H - 24, 120, 16))
        card.addSubview_(cap)
        self.opt_switches = []
        for i, (flag, name, tip) in enumerate(_opt_switches()):
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
        btn_reset.setTitle_(tr("layout.reset"))
        btn_reset.setBezelStyle_(0)
        btn_reset.setFont_(NSFont.systemFontOfSize_(11))
        btn_reset.setTarget_(self)
        btn_reset.setAction_("onResetLayout:")
        btn_reset.setToolTip_(tr("layout.reset.tip"))
        content.addSubview_(btn_reset)

        # 授权布局表（对标 Thaw「Grant Access to the Menu Bar Layout Table」）：
        # 逐枚隐藏走「直写权重表」这条正路的前提，就是让用户亲自授权那一个文件。
        # 已授权时按钮显示状态、再点可重新授权（文件挪位/书签失效时自救）。
        try:
            granted = layout_table.has_access()
        except Exception:  # noqa: BLE001
            granted = False
        btn_grant = NSButton.alloc().initWithFrame_(
            NSMakeRect(EDGE + 96 + 8, top - ROW_H, 132, ROW_H))
        btn_grant.setTitle_(tr("layout.grant.ok") if granted else tr("layout.grant"))
        btn_grant.setBezelStyle_(0)
        btn_grant.setFont_(NSFont.systemFontOfSize_(11))
        btn_grant.setTarget_(self)
        btn_grant.setAction_("onGrantLayoutTable:")
        btn_grant.setToolTip_(tr("layout.grant.tip"))
        content.addSubview_(btn_grant)

        # 「应用改动」（暂存+应用模式的核心按钮）：布局页所有编辑都是草稿，
        # 点这里才写盘并一次性贴回真实菜单栏；有草稿时窗口标题挂点提醒
        btn_apply = NSButton.alloc().initWithFrame_(
            NSMakeRect(CONTENT_W - EDGE - 150, top - ROW_H, 150, ROW_H))
        btn_apply.setTitle_(tr("layout.applying") if getattr(self, "_applying", False)
                           else tr("layout.apply"))
        btn_apply.setBezelStyle_(0)
        btn_apply.setFont_(NSFont.boldSystemFontOfSize_(11))
        btn_apply.setEnabled_(getattr(self, "_pending_cfg", None) is not None
                              and not getattr(self, "_applying", False))
        btn_apply.setTarget_(self)
        btn_apply.setAction_("onApplyLayout:")
        btn_apply.setToolTip_(tr("layout.apply.tip"))
        btn_apply.setAccessibilityIdentifier_("apply-layout")
        content.addSubview_(btn_apply)
        self.btn_apply = btn_apply
        return content

    def onGrantLayoutTable_(self, sender):
        """弹一次中文文件选择框，请用户授权布局权重表；成功后刷新按钮。"""
        ok = layout_table.request_access()
        print(f"[PeaseBar] 授权布局表：{'成功' if ok else '未授权/取消'}")
        # 临时诊断：把真实表的顶层键与 menuItemLocations 样例 dump 到 tmp/，
        # 用于核对状态键格式（匹配不准时据此修正 resolve_key）。
        if ok:
            try:
                layout_table.dump_table()
            except Exception as exc:  # noqa: BLE001
                print(f"[PeaseBar] 布局表 dump 失败：{exc}")
        # 授权成功即把已保存的布局重新贴回真实菜单栏（走权重表正路）
        if ok and self.opt("real_bar"):
            self.reconcile_real_bar_async(delay=0.6)
        self._rebuild()

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
        owner = tr("common.system") if item.owner_app == "系统" else item.owner_app
        btn.setToolTip_(tr("layout.tile.tip", label=item.label, owner=owner,
                           bid=item.owner_bundle_id, sec=sections.section_label(sec)))
        btn.setAccessibilityLabel_(
            tr("layout.tile.ax", label=item.label, sec=sections.section_label(sec)))
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
                sections.section_label(sec), "onMoveSection:", str(idx + 1))
            mi.setKeyEquivalentModifierMask_(1 << 20)  # NSEventModifierFlagCommand
            mi.setTarget_(self)  # 显式 target，不依赖响应链（T21）
            mi.setState_(1 if sec == cur_sec else 0)
            mi.setTag_(idx)
            mi.setRepresentedObject_(sections.item_key(item))
            menu.addItem_(mi)
        # 同区内前移/后移（用户主诉「编辑前后顺序不順」）：右键哪枚就动哪枚，
        # 不要求先单击选中再按 ⌥方向键——多一条低门槛路径
        menu.addItem_(NSMenuItem.separatorItem())
        for label, delta in ((tr("menu.prev"), -1), (tr("menu.next"), 1)):
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                label, "onMenuReorder:", "")
            mi.setTarget_(self)
            mi.setTag_(delta)
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
        不记撤销点（否则原地拖一下就把 ⌘Z 堵了一层）。

        暂存+应用模式（2026-11-24）：落位只改草稿副本，不写盘不镜像不刷面板——
        点「应用改动」才一次性生效。
        """
        if not key or target is None:
            return False
        self._begin_pending()
        cfg = self._pending_cfg
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
        self.selected_key = key  # 拖完就是选中，底部提示与按钮立即可用
        self.buckets = new
        self._rebuild()
        print(f"[PeaseBar] 设置：拖动 {key} → {sections.SECTION_LABELS[target]} "
              f"第 {min(index, len(new[target]))} 格（暂存，待应用）")
        return True

    # ---------- 布局页选项（真实像素优先 / 图标条换行） ----------

    @objc.python_method
    def opt(self, flag):
        """读布局选项（只在 _rebuild 同步下来的两个标记上取值，不二次读盘）。"""
        return bool(getattr(self, flag, True))

    def onOptionSwitch_(self, sender):
        """布局选项开关：只改草稿副本（同样待「应用改动」才落盘生效）；
        换行/真实像素会改窗高与格子里的图，重建整窗让草稿所见即所得。"""
        flag = str(sender.representedObject())
        on = sender.state() == 1
        self._begin_pending()
        self._pending_cfg[flag] = on
        if flag == "use_captured" and on and not self.images:
            self._reload_items()  # 开关拉回真实像素但手上没货：补一次取图
        print(f"[PeaseBar] 设置：选项 {flag} = {on}（暂存，待应用）")
        self._rebuild()

    def onSortMore_(self, sender):
        """排序菜单项：反转本区 / 恢复默认顺序（都走 order 写入草稿，⌘Z 可撤）。"""
        sec = _TAG_SECTIONS.get(sender.tag() // 10)
        kind = sender.tag() % 10
        if sec is None:
            return
        self._begin_pending()
        cfg = self._pending_cfg
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
        self.buckets = buckets
        self._rebuild()
        print(f"[PeaseBar] 设置：{sections.SECTION_LABELS[sec]} "
              f"{'反转' if kind == 1 else '恢复默认'}（暂存，待应用）")

    def onMoveButton_(self, sender):
        """底部「移到 X 区」按钮：作用于当前选中项。"""
        if self.selected_key is None:
            return
        self.applyMove_to_(self.selected_key, _TAG_SECTIONS.get(sender.tag()))

    def onReorderButton_(self, sender):
        """底部「← 前移 / 后移 →」：同区内移动选中项（tag 就是位移量）。"""
        self.reorderSelected_by_(self.selected_key, sender.tag())

    def onUndo(self):
        """撤销按钮（零参 action）：回上一步分区/顺序改动（返回是否真撤了）。"""
        return self._undo_step()

    def onMoveSection_(self, sender):
        """右键菜单项：移到 sender 标记的区（菜单项自带目标键）。"""
        key = sender.representedObject()
        self.applyMove_to_(str(key) if key is not None else None,
                          _TAG_SECTIONS.get(sender.tag()))

    def onMenuReorder_(self, sender):
        """右键菜单项「前移/后移」：作用于菜单项标记的图标（tag 即位移量）。"""
        key = sender.representedObject()
        self.reorderSelected_by_(str(key) if key is not None else None,
                                 sender.tag())

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
        """重置布局：先弹确认再动草稿；应用前不落盘不拖拽（暂存+应用模式）。"""
        alert = NSAlert.alloc().init()
        alert.setMessageText_(tr("layout.reset.title"))
        alert.setInformativeText_(tr("layout.reset.body"))
        alert.addButtonWithTitle_(tr("layout.reset.btn"))
        alert.addButtonWithTitle_(tr("common.cancel"))
        if int(alert.runModal()) != int(NSAlertFirstButtonReturn):
            print("[PeaseBar] 设置：重置布局被取消")
            return
        self._begin_pending()
        cfg = self._pending_cfg
        self._push_undo(cfg)
        sections.reset_layout(cfg)
        print("[PeaseBar] 设置：重置布局（全部回菜单栏，顺序清空；暂存，待应用）")
        self._rebuild()

    def onApplyLayout_(self, sender):
        """「应用改动」：暂存的布局草稿一次写盘并立刻生效。

        生效三件事都在后台线程做（CC 全量对齐含 2s 实效自检、系统收纳区放出、
        「菜单栏显示」区整区顺序对齐——合成 ⌘-拖很慢，不能卡主线程）；期间
        应用按钮转忙防重入；完成后回主线程重盘点、重建界面、刷新面板。
        应用前的盘上配置压进撤销栈：应用错了还能 ⌘Z 回滚（回滚同样只是草稿，
        再点应用才落盘）。
        """
        if getattr(self, "_pending_cfg", None) is None or getattr(self, "_applying", False):
            return
        self._undo.append(sections.snapshot(sections.load_config()))
        if len(self._undo) > UNDO_LIMIT:
            del self._undo[0]
        sections.save_config(self._pending_cfg)
        self._pending_cfg = None
        self._applying = True
        print("[PeaseBar] 设置：应用改动（草稿已落盘，真实菜单栏对齐中…）")
        import threading

        def _run():
            summary = {}
            try:
                if self.opt("real_bar"):
                    summary["cc"] = self.sync_cc_now()
                    try:
                        self._reveal_all_stashed()
                    except Exception as exc:  # noqa: BLE001
                        print(f"[PeaseBar] 应用：收纳区放出失败：{exc}")
                    try:
                        self._align_section_order()
                    except Exception as exc:  # noqa: BLE001
                        print(f"[PeaseBar] 应用：顺序对齐失败：{exc}")
            except Exception as exc:  # noqa: BLE001
                summary["error"] = str(exc)
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "applyDone:", summary, False)

        threading.Thread(target=_run, daemon=True).start()
        self._rebuild()  # 立即按盘上配置重画：按钮转忙、标题去点
        if self.on_changed:
            self.on_changed()

    def applyDone_(self, summary):
        """应用流程的后台部分跑完：回主线程收尾（重盘点/重建/刷新面板）。"""
        self._applying = False
        cc = summary.get("cc") or {}
        if cc.get("writable") and (cc.get("hide") or cc.get("show")):
            print(f"[PeaseBar] 应用：真实菜单栏收 {cc.get('hide', 0)} 枚 / 显 "
                  f"{cc.get('show', 0)} 枚")
        if cc.get("still_visible"):
            print(f"[PeaseBar] 应用：实效自检重写 {len(cc['still_visible'])} 枚")
        if cc.get("error"):
            print(f"[PeaseBar] 应用：CC 对齐异常：{cc['error']}")
        if summary.get("error"):
            print(f"[PeaseBar] 应用：异常：{summary['error']}")
        self._reload_items()
        self._rebuild()
        if self.on_changed:
            self.on_changed()
        print("[PeaseBar] 设置：应用改动完成")

    @objc.python_method
    def _align_section_order(self):
        """应用时把「菜单栏显示」区整区目标顺序一次对齐到真实菜单栏。

        按目标序逐项拖到左邻右边；每步拖完刷一遍实时坐标再动下一项（合成
        ⌘-拖会重排菜单栏，旧坐标会拖空）。实况已是目标序就不折腾——合成拖拽
        哪怕幂等也会让图标抖一下。系统项拖不动，但永远占着前排，正好当锚。
        """
        if not self.opt("real_bar"):
            return
        group = self.buckets.get(sections.SECTION_VISIBLE) or []
        if len(group) < 2:
            return
        import time
        try:
            fresh = [sections.item_key(m) for m in inventory.list_items()[0]
                     if not m.is_stash_button]
            pos = {k: i for i, k in enumerate(fresh)}
            seq = [pos[k] for k in (sections.item_key(it) for it in group) if k in pos]
            if seq == sorted(seq):
                return  # 实况相对序已等于目标序：无需动手
        except Exception:  # noqa: BLE001
            pass
        # CC 刚显回的项可能还没进盘点缓存：补一次全量盘点再动手
        try:
            all_items, _ = inventory.list_items()
            have = {sections.item_key(m) for m in self.items}
            for m in all_items:
                if not m.is_stash_button and sections.item_key(m) not in have:
                    self.items.append(m)
        except Exception:  # noqa: BLE001
            pass
        self._resync_frames()
        prev = None
        moved = 0
        for it in group:
            src = self._item_by_key(sections.item_key(it))
            if prev is not None and src is not None and menubar_drag.movable(src):
                anchor = self._item_by_key(sections.item_key(prev))
                if anchor is not None:
                    try:
                        if menubar_drag.reorder(src, anchor, after=True):
                            moved += 1
                            time.sleep(0.35)  # 给系统一拍重排，下一项的坐标才新
                            self._resync_frames()
                    except Exception as exc:  # noqa: BLE001
                        print(f"[PeaseBar] 应用：顺序对齐失败（{it.label}）：{exc}")
            prev = it
        if moved:
            print(f"[PeaseBar] 应用：「菜单栏显示」区顺序对齐 {moved} 项")

    @objc.python_method
    def _reveal_all_stashed(self):
        """把系统收纳区里的第三方图标逐个拖回可见段（重置布局用）。"""
        n = 0
        for it in list(self.items):
            if getattr(it, "stashed", False) and not it.is_stash_button:
                bid = it.owner_bundle_id or ""
                if bid and not bid.startswith("com.apple."):
                    try:
                        if self._real_reveal(it):
                            n += 1
                    except Exception as exc:
                        print(f"[PeaseBar] 真实菜单栏同步（重置放出）失败：{exc}")
        self._resync_frames()
        if n:
            print(f"[PeaseBar] 重置：把 {n} 个图标拖回真实菜单栏")

    # ---------- 真实菜单栏显隐的统一入口（真机取证：合成拖拽） ----------

    @objc.python_method
    def _real_hide(self, item, always=False):
        """逐枚隐藏一枚图标：CC 按 App 开关优先（无容量限制、双向即时），

        不可用时回退合成 ⌘-拖（塞系统收纳条，有容量上限）。CC 通道真机实证
        （2026-11-23）：写 isAllowed=false + killall cfprefsd/MenuBarAgent →
        图标消失而 App 照跑；记录侧车以便启动同步将来显回。
        """
        bid = getattr(item, "owner_bundle_id", "") or ""
        if ccnative.is_protected(bid):
            # 系统项（com.apple.*/PeaseBar 自己）CC 管不了、⌘-拖也拖不动
            # （真机实证）：不再试拖——模拟鼠标乱跑却永远无效，用户零容忍
            print(f"[PeaseBar] {bid} 是系统项，系统不允许第三方隐藏，跳过")
            return False
        st = ccnative.is_app_hidden(bid)
        if st is True:
            return True  # 已是隐藏态：幂等成功
        if st is False:
            try:
                changed = ccnative.set_apps_allowed([bid], False)
                if changed:
                    ccnative.record_hidden(changed)
                return True
            except Exception as exc:  # noqa: BLE001
                print(f"[PeaseBar] CC 隐藏失败（{bid}）：{exc}，回退拖拽")
        try:
            return menubar_drag.movable(item) and menubar_drag.hide(item)
        except Exception as exc:  # noqa: BLE001
            print(f"[PeaseBar] 拖拽隐藏失败（{bid}）：{exc}")
            return False

    @objc.python_method
    def _real_reveal(self, item):
        """取消隐藏一枚图标：CC 按 App 开关优先，无记录可管时回退合成拖拽。"""
        bid = getattr(item, "owner_bundle_id", "") or ""
        if ccnative.is_protected(bid):
            print(f"[PeaseBar] {bid} 是系统项，显隐由系统管理，跳过")
            return False
        if ccnative.is_app_hidden(bid) is not None:
            try:
                ccnative.set_apps_allowed([bid], True)
                return True
            except Exception as exc:  # noqa: BLE001
                print(f"[PeaseBar] CC 显回失败（{bid}）：{exc}，回退拖拽")
        try:
            return menubar_drag.reveal(item)
        except Exception as exc:  # noqa: BLE001
            print(f"[PeaseBar] 拖拽显示失败（{bid}）：{exc}")
            return False

    @objc.python_method
    def _drag_cycle_test(self, owner, label):
        """真机逐条取证：对一枚图标跑 hide→确认 stashed→reveal→确认回到可见。

        走的是正式入口 _real_hide/_real_reveal（含拖拽验证与重试），结果落
        tmp/peasebar_exp_result.json。选当前可见的靶标，周期结束回到可见=原状。
        """
        import time

        def find():
            try:
                for m in inventory.list_items()[0]:
                    if (m.owner_bundle_id or "").lower() == owner.lower() and (
                            not label or label.lower() in (m.label or "").lower()):
                        return m
            except Exception:  # noqa: BLE001
                pass
            return None

        m0 = find()
        if m0 is None:
            return {"error": f"未找到 {owner}/{label}"}
        before = bool(getattr(m0, "stashed", False))
        hide_ret = self._real_hide(m0)
        time.sleep(0.4)
        m1 = find()
        after_hide = bool(getattr(m1, "stashed", False)) if m1 else None
        reveal_ret = self._real_reveal(m1 or m0)
        time.sleep(0.4)
        m2 = find()
        after_reveal = bool(getattr(m2, "stashed", True)) if m2 else None
        return {"owner": owner, "label": getattr(m0, "label", label),
                "before_stashed": before,
                "hide_returned": hide_ret, "after_hide_stashed": after_hide,
                "hide_ok": after_hide is True,
                "reveal_returned": reveal_ret, "after_reveal_stashed": after_reveal,
                "reveal_ok": after_reveal is False,
                "reversible": (after_hide is True and after_reveal is False)}

    @objc.python_method
    def sync_cc_now(self):
        """按配置全量对齐 CC 开关（启动同步与周期核对共用的正路）。

        真机实证：写 isAllowed=false + killall MenuBarAgent → 图标消失且 App
        照跑；true → 回来。CC plist 是持久存储，App 没跑也能写——只处理
        「此刻盘点到的」会漏掉没跑的 App（欧路词典案例）。幂等：目标态与
        现状一致时 set_apps_allowed 不写盘、不重启 Agent，周期核对零感知。

        返回摘要：writable / hide / show / leftover(label 列表) / error。
        """
        cfg = sections.load_config()
        out = {"writable": False, "hide": 0, "show": 0, "leftover": []}
        cfg_hidden_bids = {k.split("|", 1)[0]
                           for k, s in cfg["sections"].items()
                           if s in (sections.SECTION_HIDDEN,
                                    sections.SECTION_ALWAYS_HIDDEN)}
        cfg_visible_bids = {k.split("|", 1)[0]
                            for k, s in cfg["sections"].items()
                            if s == sections.SECTION_VISIBLE}
        # 输入法菜单（搜狗等输入法图标的宿主）走专用 visible 键通道：CC 按 App
        # 开关不管 Apple 进程（真机实证与死路对比见 ccnative 输入法菜单段注释）。
        # 配置 hidden → 隐藏；配置 visible → 显示；两区都没标（用户没管）→
        # 不动系统现状。该通道只写普通偏好域，不依赖 CC plist 写权，放在
        # writable 判断之前——CC 通道不可用时搜狗照样能管。
        try:
            if ccnative.match_bid(ccnative.INPUT_MENU_AGENT, cfg_hidden_bids):
                out["input_menu"] = (
                    "hide" if ccnative.set_input_menu_visible(False) else "hidden")
            elif ccnative.match_bid(ccnative.INPUT_MENU_AGENT, cfg_visible_bids):
                out["input_menu"] = (
                    "show" if ccnative.set_input_menu_visible(True) else "shown")
        except Exception as exc:  # noqa: BLE001
            out["input_menu_error"] = str(exc)
        if not ccnative.is_writable():
            return out
        out["writable"] = True
        try:
            # 显回的只限「自己上轮藏过、现在配置改显示」的：用户在系统设置
            # 里手动关掉的（配置是显示）不动，尊重手动选择。
            prev = ccnative.last_hidden()
            to_show = {b for b in prev
                       if ccnative.match_bid(b, cfg_visible_bids)}
            # 盘点到的可见项也补写 true（幂等，防中途被谁动过）
            for m in inventory.list_items()[0]:
                if m.is_stash_button or ccnative.is_protected(m.owner_bundle_id):
                    continue
                if sections.section_of(cfg, sections.item_key(m)) == sections.SECTION_VISIBLE:
                    to_show.add(m.owner_bundle_id)
            out["hide"] = len(ccnative.set_apps_allowed(cfg_hidden_bids, False))
            out["show"] = len(ccnative.set_apps_allowed(to_show, True))
            # 实效自检：写成功≠生效（2026-11-24 事故教训：格式写坏后每次幂等
            # 跳过，图标全在栏上却无人报错）。给 MenuBarAgent 重读留一拍再
            # 盘点栏上实况，配置要藏的 bid 仍在线就重写一轮并如实上报。
            time.sleep(2.0)
            online_bids = [m.owner_bundle_id
                           for m in inventory.list_items()[0]
                           if not m.is_stash_button]
            still = [b for b in sorted(cfg_hidden_bids)
                     if ccnative.match_bid(b, set(online_bids))]
            if still:
                print(f"[PeaseBar] 实效自检：{len(still)} 个配置隐藏项仍在菜单栏上"
                      f"（{', '.join(still[:4])}...），重写一次")
                ccnative.set_apps_allowed(set(still), False)
                out["still_visible"] = still
            # 侧车记「此刻系统藏着的、且是配置让它藏的」全集：配置日后改成
            # 「显示」时同步据此负责显回。
            duty = {b for b in ccnative.hidden_bids_now()
                    if not ccnative.is_protected(b)
                    and ccnative.match_bid(b, cfg_hidden_bids)}
            ccnative.record_hidden(duty)
            out["leftover"] = [
                m.label or m.owner_bundle_id
                for m in inventory.list_items()[0]
                if not m.is_stash_button
                and ccnative.is_protected(m.owner_bundle_id)
                and m.owner_bundle_id != ccnative.INPUT_MENU_AGENT
                and sections.section_of(cfg, sections.item_key(m)) in (
                    sections.SECTION_HIDDEN, sections.SECTION_ALWAYS_HIDDEN)]
        except Exception as exc:  # noqa: BLE001
            out["error"] = str(exc)
        return out

    def syncCCTick_(self, timer):
        """周期核对（60s，app.py 挂钟）：系统状态会漂移——App 断线重连时重建
        图标（真机实证：Synology Drive Client 隐藏后重现），启动时一次同步
        管不住全程。后台跑一次全量对齐：无漂移时幂等零动作（不写盘、不
        重启 Agent、菜单栏不闪），有漂移才真正落盘收回来。"""

        def _run():
            try:
                r = self.sync_cc_now()
                if r.get("writable") and (r.get("hide") or r.get("show")):
                    print(f"[PeaseBar] 周期核对：收回 {r['hide']} 枚 / 显回 "
                          f"{r['show']} 枚（系统状态漂移已纠正）")
                if r.get("input_menu") in ("hide", "show"):
                    print(f"[PeaseBar] 周期核对：输入法菜单"
                          f"{'已收回' if r['input_menu'] == 'hide' else '已显回'}"
                          f"（系统状态漂移已纠正）")
            except Exception as exc:  # noqa: BLE001
                print(f"[PeaseBar] 周期核对异常：{exc}")

        import threading
        threading.Thread(target=_run, daemon=True).start()

    def driftInject_(self, timer):
        """主线程回调（__DRIFT__ 取证）：注入漂移——把指定 App 的 isAllowed
        写回 true（模拟 App 重连重建图标/系统重写记录），之后 60s 周期核对
        应自动把它收回。写盘在后台线程，主线程不卡。"""
        bid = str(getattr(self, "_drift_bid", "") or "")
        if not bid:
            return

        def _run():
            try:
                changed = ccnative.set_apps_allowed({bid}, True)
                print(f"[PeaseBar] 漂移实验：已把 {bid} 写回显示态"
                      f"（改动 {sorted(changed)}），等 60s 周期核对收回")
            except Exception as exc:  # noqa: BLE001
                print(f"[PeaseBar] 漂移实验注入失败：{exc}")

        import threading
        threading.Thread(target=_run, daemon=True).start()

    @objc.python_method
    def reconcile_real_bar(self):
        """把已保存的分区一次性镜像到真实菜单栏（启动/授权后调一次）。

        用户痛点「设为弹窗显示的图标还在菜单栏上」的根因：换区只在拖动的
        那一瞬间镜像到真实菜单栏，启动时从不把「上次保存的布局」重新贴回系统。

        正路（拿到布局权重表授权时）：读一次表→按每枚图标的目标分区批量调
        权重（隐藏=停车权重、显示=还原正常值）→写一次→广播一次。权重表没有
        溢出区容量上限，也不靠拖拽，因此一趟到位、不振荡、可逆、不重启 App。

        回退（未授权布局表时）：才用合成 ⌘-拖逐枚塞进系统溢出区，并带容量
        护栏（一旦不再让被收纳数上升说明溢出区已满，立即收手，别再硬塞）。
        在后台线程跑（拖拽较慢时不能卡主线程/启动）。
        """
        import time

        # 诊断触发文件：只在开发取证时用（文件在才跑各种 dump/实验），
        # 平时启动不落盘、不扰民。
        trig = os.path.join(os.path.expanduser("~/Project/PeaseBar/tmp"),
                            "peasebar_exp_hide")
        if os.path.exists(trig):
            # 落一份真实表 + 访问链诊断（离线核对权限断点与 key 格式）。
            try:
                layout_table.dump_table()
            except Exception as exc:  # noqa: BLE001
                print(f"[PeaseBar] 启动同步：dump 布局表异常：{exc}")
            # 把在线第三方图标清单（owner/label/key_part/stashed）落一份。
            try:
                import json as _json
                items = inventory.list_items()[0]
                rec = [{"owner_app": m.owner_app, "owner_bundle_id": m.owner_bundle_id,
                        "label": m.label, "key_part": m.key_part, "role": m.role,
                        "stashed": bool(getattr(m, "stashed", False)),
                        "is_stash_button": bool(m.is_stash_button)}
                       for m in items]
                with open(os.path.join(os.path.expanduser("~/Project/PeaseBar/tmp"),
                                       "live_inventory.json"), "w",
                          encoding="utf-8") as f:
                    _json.dump(rec, f, ensure_ascii=False, indent=2)
                print(f"[PeaseBar] 启动同步：已 dump 在线图标清单 {len(rec)} 项")
            except Exception as exc:  # noqa: BLE001
                print(f"[PeaseBar] 启动同步：dump 在线清单异常：{exc}")

        # 诊断：若 tmp/peasebar_exp_hide 存在，跑一次受控隐藏实验（写多种候选
        # 状态键），把结果落 tmp/peasebar_exp_result.json，然后删掉触发文件。
        try:
            trig = os.path.join(os.path.expanduser("~/Project/PeaseBar/tmp"),
                                "peasebar_exp_hide")
            if os.path.exists(trig):
                import json as _json
                spec = open(trig, encoding="utf-8").read().strip().split("\t")
                owner = spec[0] if spec else ""
                if owner == "__CLEANUP__":
                    r = layout_table.clear_table()
                elif owner == "__REVEAL__":
                    o = spec[1] if len(spec) > 1 else ""
                    t = (spec[2] if len(spec) > 2 else "").lower()
                    _it = inventory.list_items()[0]
                    hit = None
                    for m in _it:
                        if (m.owner_bundle_id or "").lower() == o.lower() and (
                                not t or t in (m.label or "").lower()):
                            hit = m
                            break
                    ok = bool(hit is not None and menubar_drag.reveal(hit))
                    r = {"revealed": ok, "owner": o,
                         "label": getattr(hit, "label", None)}
                elif owner == "__DRAGTEST__":
                    r = self._drag_cycle_test(
                        spec[1] if len(spec) > 1 else "",
                        (spec[2] if len(spec) > 2 else ""))
                elif owner == "__REALHIDE__":
                    o = spec[1] if len(spec) > 1 else owner
                    ident = spec[2] if len(spec) > 2 else o
                    title = spec[3] if len(spec) > 3 else ident
                    w = spec[4] if len(spec) > 4 else None
                    try:
                        w = (None if w in (None, "", "None") else float(w))
                    except ValueError:
                        w = None
                    r = layout_table.real_hide_test(o, ident, title, w)
                elif owner == "__REALAGENT__":
                    o = spec[1] if len(spec) > 1 else owner
                    ident = spec[2] if len(spec) > 2 else o
                    title = spec[3] if len(spec) > 3 else ident
                    w = spec[4] if len(spec) > 4 else None
                    try:
                        w = (None if w in (None, "", "None") else float(w))
                    except ValueError:
                        w = None
                    r = layout_table.real_hide_agent_test(o, ident, title, w)
                elif owner == "__REALPROBE__":
                    try:
                        _it = inventory.list_items()[0]
                    except Exception:  # noqa: BLE001
                        _it = []
                    r = {"real_probe": layout_table.real_probe(_it),
                         "cfprefs_write": layout_table.cfprefs_suite_write_probe()}
                elif owner == "__CFWRITE__":
                    ident = spec[1] if len(spec) > 1 else owner
                    title = spec[2] if len(spec) > 2 else ident
                    r = layout_table.cfprefs_write_probe(ident, title)
                elif owner == "__INVENTORY__":
                    # 只盘点+截图，不动任何图标：拿「此刻」真实收纳/可见状态取证
                    r = self._inventory_diag()
                elif owner == "__APPLYALL__":
                    # 逐枚把「弹窗显示」收进真实收纳区，每步落日志（验容量自增强）
                    r = self._apply_hidden_all()
                elif owner == "__PARKTEST__":
                    # 停车实验：写容器真表权重(≥50000)→重启MenuBarAgent→观察落点
                    r = self._park_test(spec[1] if len(spec) > 1 else "",
                                        spec[2] if len(spec) > 2 else "")
                elif owner == "__PARKRESTORE__":
                    # 恢复停车实验改过的所有权重 + 清垃圾键 + 重启 Agent
                    r = self._park_restore_all()
                elif owner == "__PANEL__":
                    # 取证：主线程把救援面板打开，供外部截屏看面板现状
                    r = self._panel_open_test()
                elif owner == "__POSTCHECK__":
                    # 取证：置标志，启动同步全部跑完后盘点最终收纳状态
                    self._postcheck_armed = True
                    r = {"postcheck_scheduled": True}
                elif owner == "__OFFSCREEN__":
                    # 实验：把「配置隐藏但仍在栏上」的状态项窗口 AX 移出屏幕右缘
                    r = self._offscreen_test()
                elif owner == "__OFFSCREEN2__":
                    # 实验 2：AX 不暴露状态项窗口，改走 CGS 私有通道
                    r = self._offscreen_cgs_test()
                elif owner == "__OFFSCREEN3__":
                    # 实验 3：修正 SkyLight 路径 + 列出菜单栏条带内全部窗口再打击
                    r = self._offscreen_cgs_test(enumerate_all=True)
                elif owner == "__OFFSCREEN4__":
                    # 实验 4：状态项无独立 CG 窗口（实验 3 实证），
                    # 改对状态项 AX 元素本身写 AXPosition 移出屏幕
                    r = self._offscreen_ax_pos_test()
                elif owner == "__CCPROBE__":
                    # CC plist 通道在 PeaseBar.app 进程内的真实可用性取证：
                    # 终端能读写不代表 app 进程能（TCC 按进程算）。读计数 +
                    # 用 Thaw Debug 的 bid 真写一次再还原，结果落盘离线分析。
                    probe = {"writable": ccnative.is_writable(),
                             "now_hidden": sorted(ccnative.hidden_bids_now())}
                    try:
                        _o, _r = ccnative._load()
                        probe["read_recs"] = len(_r)
                    except Exception as exc:  # noqa: BLE001
                        probe["read_error"] = repr(exc)
                    try:
                        hid = ccnative.set_apps_allowed(
                            {"com.stonerl.Thaw.debug"}, False)
                        probe["write_test"] = sorted(hid)
                        if hid:  # 还原：真写 False 成功后立即写回 True
                            ccnative.set_apps_allowed(
                                {"com.stonerl.Thaw.debug"}, True)
                    except Exception as exc:  # noqa: BLE001
                        probe["write_error"] = repr(exc)
                    r = probe
                elif owner == "__SETTINGSWIN__":
                    # 取证：主线程开设置窗口（布局页），4s 后截屏 + 三区清单落盘
                    r = self._settings_open_test()
                elif owner == "__DRIFT__":
                    # 取证：启动同步完成后延迟注入「系统漂移」（PeaseBar 进程才有
                    # TCC 写权，终端写会 Errno 1）——把指定 App 的 isAllowed 写回
                    # true 模拟 App 重连重建图标，验证 60s 周期核对的自动收回
                    self._drift_bid = spec[1] if len(spec) > 1 else ""
                    self._drift_armed = True
                    r = {"drift_armed": True, "bid": self._drift_bid}
                else:
                    ident = spec[1] if len(spec) > 1 else owner
                    title = spec[2] if len(spec) > 2 else ident
                    r = layout_table.run_hide_experiment(owner, ident, title)
                with open(os.path.join(os.path.dirname(trig),
                                       "peasebar_exp_result.json"), "w",
                          encoding="utf-8") as f:
                    _json.dump(r, f, ensure_ascii=False, indent=2, default=str)
                os.remove(trig)
                print(f"[PeaseBar] 启动同步：隐藏实验已跑，结果落 peasebar_exp_result.json")
        except Exception as exc:  # noqa: BLE001
            # print 进 launchd 看不见，异常全文落盘才能离线取证
            import traceback
            try:
                with open(os.path.join(
                        os.path.dirname(trig), "peasebar_exp_error.txt"),
                        "w", encoding="utf-8") as f:
                    traceback.print_exc(file=f)
            except Exception:  # noqa: BLE001
                pass
            print(f"[PeaseBar] 启动同步：隐藏实验异常：{exc}")

        cfg = sections.load_config()
        if not cfg.get("real_bar", True):
            return
        if not AXIsProcessTrusted():
            print("[PeaseBar] 启动同步：无辅助功能权限，跳过真实菜单栏镜像")
            return

        # ---- 主通道：CC 按 App 显隐（不受收纳条容量限制；细节见 sync_cc_now）----
        r = self.sync_cc_now()
        if not r.get("writable"):
            # CC 通道不可用（is_writable=False）：不再回退启动期拖拽——
            # 不在用户不设防时抢鼠标，如实告知即可。
            print("[PeaseBar] 启动同步：CC 通道不可用，本次不动真实菜单栏；"
                  "可在设置窗口里手动调整图标显隐")
        elif "error" in r:
            print(f"[PeaseBar] 启动同步：原生通道异常（{r['error']}），本次跳过"
                  f"（不自动拖拽：启动时模拟鼠标移动会打扰用户）")
        else:
            if r.get("hide") or r.get("show"):
                print(f"[PeaseBar] 启动同步：原生显隐收 {r['hide']} 枚 / 放 "
                      f"{r['show']} 枚（ControlCenter 通道，无容量限制）")
            if r.get("leftover"):
                # 系统项（com.apple.*）走不了按 App 开关（is_protected 永不触碰），
                # 拖拽也拖不动（真机实证）——诚实说明。启动同步永不自动模拟鼠标
                # （用户对「鼠标乱跑」零容忍，2026-11-23）：合成 ⌘-拖只保留给
                # 设置窗口里用户的显式操作（_real_hide/_real_reveal）。
                print(f"[PeaseBar] 启动同步：{len(r['leftover'])} 枚系统项"
                      f"（{'、'.join(r['leftover'])}）系统不允许第三方隐藏，跳过")

        # 注：无论主通道成败都落到这里（取证调度在下方），不再走启动期拖拽。

        # 输入法菜单（搜狗宿主）的显隐独立于 CC 通道成败，动作结果放公共尾部打印
        if r.get("input_menu") in ("hide", "show"):
            print(f"[PeaseBar] 启动同步：输入法菜单（搜狗等输入法图标的宿主）已"
                  f"{'隐藏' if r['input_menu'] == 'hide' else '显示'}")
        if r.get("input_menu_error"):
            print(f"[PeaseBar] 启动同步：输入法菜单显隐失败："
                  f"{r['input_menu_error']}")

        # __PANEL__ 取证：启动同步已全部跑完，这里才把「开面板」安排进主 runloop
        # （0.1s 后 fire）——不能在触发文件处直接调度：reconcile 在后台线程跑，
        # 主 runloop 一直在转，过早调度会让面板在拖拽进行中打开、截到中间态。
        if getattr(self, "_panel_test_armed", False):
            from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer
            t = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                0.1, self, "panelOpen:", None, False)
            NSRunLoop.mainRunLoop().addTimer_forMode_(t, NSRunLoopCommonModes)
            print("[PeaseBar] 面板取证：启动同步完成，已安排主线程开面板")

        # __SETTINGSWIN__ 取证：启动同步全部跑完再开设置窗（布局页），
        # 4s 后截屏 + 三区清单落盘（验证「已藏图标在设置里可见可管」）
        if getattr(self, "_settings_test_armed", False):
            from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer
            t = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                0.1, self, "settingsOpen:", None, False)
            NSRunLoop.mainRunLoop().addTimer_forMode_(t, NSRunLoopCommonModes)
            print("[PeaseBar] 设置取证：启动同步完成，已安排主线程开设置窗")

        # __DRIFT__ 取证：启动同步全部完成后再注入漂移（太早注入会被启动同步
        # 立刻收回去，验不到周期核对），8s 足够稳
        if getattr(self, "_drift_armed", False):
            from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer
            t = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                8.0, self, "driftInject:", None, False)
            NSRunLoop.mainRunLoop().addTimer_forMode_(t, NSRunLoopCommonModes)
            print("[PeaseBar] 漂移实验：启动同步完成，8s 后注入")

        # __POSTCHECK__ 取证：启动同步收敛完，盘点最终收纳状态（只读不动）
        if getattr(self, "_postcheck_armed", False):
            try:
                r2 = self._inventory_diag()
                with open(os.path.expanduser(
                        "~/Project/PeaseBar/tmp/peasebar_exp_result.json"),
                        "w", encoding="utf-8") as f:
                    import json as _json
                    _json.dump(r2, f, ensure_ascii=False, indent=2, default=str)
                print(f"[PeaseBar] 后置盘点：已收 {len(r2.get('stashed', []))} 枚，"
                      f"仍在栏 {len(r2.get('configured_hidden_still_visible', []))} 枚")
            except Exception as exc:  # noqa: BLE001
                print(f"[PeaseBar] 后置盘点失败：{exc}")

    @objc.python_method
    def reconcile_real_bar_async(self, delay=1.5):
        """延后一点、在后台线程跑一次启动同步（等菜单栏把状态项摆稳）。"""
        import threading

        def _run():
            import time
            time.sleep(delay)
            try:
                self.reconcile_real_bar()
            except Exception:  # noqa: BLE001
                # 后台线程的 traceback 只会进 launchd 不可见，落盘一份才能查
                import traceback
                try:
                    with open(os.path.expanduser(
                            "~/Project/PeaseBar/tmp/reconcile_error.txt"),
                            "w", encoding="utf-8") as f:
                        traceback.print_exc(file=f)
                except Exception:  # noqa: BLE001
                    pass
                traceback.print_exc()

        threading.Thread(target=_run, daemon=True).start()

    @objc.python_method
    def _inventory_diag(self):
        """诊断（__INVENTORY__ 触发）：当前真实菜单栏的收纳/可见状态 + 条带截图。

        只读不动：列出已收纳、可见第三方、以及「配置为弹窗显示但仍在可见段」的项，
        配一张顶部条带 PNG（App 有屏幕录制权限，截到真实像素），结果落 tmp/。
        """
        import time as _t
        from AppKit import NSScreen, NSBitmapImageRep, NSPNGFileType
        tmp = os.path.expanduser("~/Project/PeaseBar/tmp")
        items = inventory.list_items()[0]
        cfg = sections.load_config()

        def rec(m):
            return {"app": m.owner_app, "bid": m.owner_bundle_id,
                    "label": m.label,
                    "frame": tuple(m.frame) if m.frame else None}

        stashed = [m for m in items if getattr(m, "stashed", False)
                   and not m.is_stash_button]
        vis3 = [m for m in items if not getattr(m, "stashed", False)
                and not m.is_stash_button
                and (m.owner_bundle_id or "") != "com.apple.MenuBarAgent"]
        pend = [m for m in vis3
                if sections.section_of(cfg, sections.item_key(m)) in
                (sections.SECTION_HIDDEN, sections.SECTION_ALWAYS_HIDDEN)]
        shot = os.path.join(tmp, "menubar_strip.png")
        shot_ok = False
        try:
            s = NSScreen.mainScreen().frame()
            img = Quartz.CGWindowListCreateImage(
                Quartz.CGRectMake(0, 0, int(s.size.width), 40),
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault)
            if img is not None:
                rep = NSBitmapImageRep.alloc().initWithCGImage_(img)
                if rep is not None:
                    data = rep.representationUsingType_properties_(NSPNGFileType, None)
                    shot_ok = bool(data.writeToFile_atomically_(shot, True))
        except Exception as exc:  # noqa: BLE001
            print(f"[PeaseBar] 诊断截图失败：{exc}")
        return {"time": _t.strftime("%H:%M:%S"),
                "screenshot": shot if shot_ok else None,
                "stashed": [rec(m) for m in stashed],
                "visible_3rd": [rec(m) for m in vis3],
                "configured_hidden_still_visible": [rec(m) for m in pend]}

    @objc.python_method
    def _offscreen_test(self):
        """验证「移出屏幕」隐藏通道（不受收纳条宽度限制，Bartender/Ice 同款思路）：

        把「配置隐藏但仍在栏上」的状态项窗口用跨进程 AX 写 AXPosition 移到
        屏幕右缘之外，回答三件事：
        1) 系统是否放行（set_err=0）；
        2) MenuBarAgent / 图标 App 会不会拉回（移后 1s 与 6s 各回读窗口位置）；
        3) 图标 App 是否健在（其菜单栏项 AX 元素还能读吗）。
        实验不自动恢复：若移成功且不拉回，这正是用户要的隐藏终态；
        若被拉回，无需恢复；before 位置已记录在结果里供手动还原。
        """
        import time as _t
        from AppKit import NSScreen
        from peasebar import axutil
        items = inventory.list_items()[0]
        cfg = sections.load_config()
        try:
            sw = int(NSScreen.mainScreen().frame().size.width)
        except Exception:  # noqa: BLE001
            sw = 2056
        off_x = sw + 80  # 完全出屏（窗口全部在可视区外）
        out = {"time": _t.strftime("%H:%M:%S"), "screen_w": sw,
               "off_x": off_x, "moved": []}
        targets = []
        for m in items:
            if m.is_stash_button or getattr(m, "stashed", False) or m.frame is None:
                continue
            sec = sections.section_of(cfg, sections.item_key(m))
            if (sec in (sections.SECTION_HIDDEN, sections.SECTION_ALWAYS_HIDDEN)
                    and menubar_drag.movable(m)):
                targets.append(m)
        out["targets"] = [f"{m.owner_app}/{m.label}" for m in targets]
        for m in targets:
            rec = {"target": f"{m.owner_app}/{m.label}",
                   "before": tuple(m.frame)}
            try:
                app = axutil.app_element_for_pid(m.owner_pid)
                axutil.set_messaging_timeout(app, 0.8)
                err, wins = axutil.copy_attr(app, "AXWindows")
                wins = axutil._as_list(wins) if err == 0 else []
                hit = None
                fx, fy, fw, fh = m.frame
                for w in wins:
                    wf = axutil.element_frame(w)
                    if wf is None:
                        continue
                    wx, wy, ww, wh = wf
                    # 状态项窗口与图标矩形重叠、贴着菜单栏（窗口通常比图标大一圈）
                    if (wx <= fx + fw and wx + ww >= fx
                            and abs(wy - fy) < 12 and wh <= 60):
                        hit = w
                        rec["win_frame"] = wf
                        break
                if hit is None:
                    rec["error"] = f"没找到匹配窗口（该 App 共 {len(wins)} 个窗口）"
                else:
                    rec["set_err"] = axutil.set_position(hit, off_x, fy)
                    _t.sleep(1.0)
                    rec["after_1s"] = axutil.element_frame(hit)
                    _t.sleep(5.0)
                    rec["after_6s"] = axutil.element_frame(hit)
                    el = getattr(m, "el", None)
                    rec["el_alive"] = (axutil.element_frame(el) is not None
                                       if el is not None else None)
            except Exception as exc:  # noqa: BLE001
                rec["error"] = str(exc)
            out["moved"].append(rec)
        return out

    @objc.python_method
    def _offscreen_cgs_test(self, enumerate_all=False):
        """实验：CGS 私有通道隐藏状态项窗口（Bartender/Ice 同源思路）。

        enumerate_all=False：按 pid+layer=25 精确找窗口；True：列出菜单栏
        条带内（y<=30、h<=60）的全部窗口（摸清状态项窗口真实的
        layer/owner/pid 分布），再对与目标图标重叠的窗口执行隐藏操作。
        """
        import ctypes
        import time as _t
        from AppKit import NSScreen, NSBitmapImageRep, NSPNGFileType
        items = inventory.list_items()[0]
        cfg = sections.load_config()
        targets = []
        for m in items:
            if m.is_stash_button or getattr(m, "stashed", False) or m.frame is None:
                continue
            sec = sections.section_of(cfg, sections.item_key(m))
            if (sec in (sections.SECTION_HIDDEN, sections.SECTION_ALWAYS_HIDDEN)
                    and menubar_drag.movable(m)):
                targets.append(m)
        out = {"time": _t.strftime("%H:%M:%S"),
               "targets": [f"{m.owner_app}/{m.label}" for m in targets],
               "pids": [m.owner_pid for m in targets], "ops": [],
               "enumerate_all": enumerate_all}
        # 1) CGWindowList 枚举：精确模式按 pid+layer=25；摸底模式列出条带内全部
        wins = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID)
        pid_set = {m.owner_pid for m in targets}
        found = {}  # pid -> [{win, bounds, alpha, layer, owner}]
        strip_all = []
        pid_all = []  # 目标 pid 的全部窗口（不过滤，摸清状态项窗口注册形态）
        for w in wins or []:
            try:
                pid = w.get("kCGWindowOwnerPID")
                layer = w.get("kCGWindowLayer")
                num = w.get("kCGWindowNumber")
                if num is None:
                    continue
                b = dict(w.get("kCGWindowBounds") or {})
                bx, by = b.get("X", 0), b.get("Y", 0)
                bw, bh = b.get("Width", 0), b.get("Height", 0)
                if enumerate_all:
                    # 菜单栏条带内的小窗口（状态项/菜单栏本体的候选）
                    if by <= 30 and bh <= 60 and bw <= 400:
                        strip_all.append({
                            "win": int(num), "pid": pid,
                            "owner": str(w.get("kCGWindowOwnerName") or ""),
                            "name": str(w.get("kCGWindowName") or ""),
                            "layer": layer,
                            "bounds": (bx, by, bw, bh),
                            "alpha": w.get("kCGWindowAlpha")})
                    # 目标 pid 的窗口全量（不过滤 layer/bounds）——条带过滤可能
                    # 把状态项窗口滤没了，先看它名下到底注册了什么
                    if pid in pid_set:
                        pid_all.append({
                            "win": int(num),
                            "name": str(w.get("kCGWindowName") or ""),
                            "layer": layer,
                            "bounds": (bx, by, bw, bh),
                            "alpha": w.get("kCGWindowAlpha"),
                            "onscreen": bool(
                                w.get("kCGWindowIsOnscreen"))})
                    continue
                if pid in pid_set and layer == 25:
                    found.setdefault(pid, []).append({
                        "win": int(num),
                        "bounds": (bx, by, bw, bh),
                        "alpha": w.get("kCGWindowAlpha")})
            except Exception:  # noqa: BLE001
                continue
        if enumerate_all:
            strip_all.sort(key=lambda d: d["bounds"][0])
            out["menu_bar_strip_windows"] = strip_all
            out["target_pid_windows"] = pid_all
        else:
            out["cgs_windows"] = found
        # 2) 加载 SkyLight 私有框架（macOS 27 在 PrivateFrameworks 下）
        sk = None
        last_err = None
        for path in ("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight",
                     "/System/Library/Frameworks/SkyLight.framework/SkyLight"):
            try:
                sk = ctypes.CDLL(path)
                out["skylight_path"] = path
                break
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
        if sk is None and last_err:
            out["skylight_error"] = last_err
        syms = {}
        cid = None
        if sk is not None:
            try:
                sk.CGSMainConnectionID.restype = ctypes.c_int
                cid = sk.CGSMainConnectionID()
            except Exception as exc:  # noqa: BLE001
                out["cgs_cid_error"] = str(exc)
            out["cgs_cid"] = cid
            for name in ("CGSSetWindowAlpha", "CGSMoveWindow",
                         "CGSSetWindowRect", "CGSSetWindowLevel"):
                try:
                    getattr(sk, name)
                    syms[name] = True
                except AttributeError:
                    syms[name] = False
            out["symbols"] = syms
        # 3) 选窗：精确模式用 found；摸底模式按「窗口 bounds 与目标图标重叠」选
        def pick_win(m):
            if not enumerate_all:
                cands = found.get(m.owner_pid) or []
                return (cands[0]["win"] if cands else None)
            fx, fy, fw, fh = m.frame
            for row in strip_all:
                wx, wy, ww, wh = row["bounds"]
                if (row["pid"] == m.owner_pid
                        and wx <= fx + fw and wx + ww >= fx
                        and abs(wy - fy) < 12 and wh <= 60):
                    return row["win"]
            return None

        if sk is not None and cid is not None:
            for m in targets:
                rec = {"target": f"{m.owner_app}/{m.label}",
                       "pid": m.owner_pid, "before_frame": tuple(m.frame)}
                wid = pick_win(m)
                if wid is None:
                    rec["error"] = "没匹配到状态项窗口"
                    out["ops"].append(rec)
                    continue
                rec["win"] = wid
                try:
                    if syms.get("CGSSetWindowAlpha"):
                        sk.CGSSetWindowAlpha.argtypes = [
                            ctypes.c_int, ctypes.c_int, ctypes.c_double]
                        rec["alpha_ret"] = int(sk.CGSSetWindowAlpha(
                            cid, wid, ctypes.c_double(0.0)))
                    if syms.get("CGSMoveWindow"):
                        class _Pt(ctypes.Structure):
                            _fields_ = [("x", ctypes.c_double),
                                        ("y", ctypes.c_double)]
                        sk.CGSMoveWindow.argtypes = [
                            ctypes.c_int, ctypes.c_int, ctypes.POINTER(_Pt)]
                        pt = _Pt(3000.0, 7.0)  # 屏幕外
                        rec["move_ret"] = int(sk.CGSMoveWindow(
                            cid, wid, ctypes.byref(pt)))
                except Exception as exc:  # noqa: BLE001
                    rec["error"] = str(exc)
                out["ops"].append(rec)
        # 4) 1s / 6s 后截菜单栏条带留视觉证据
        for tag, wait in (("shot_1s", 1.0), ("shot_6s", 5.0)):
            _t.sleep(wait)
            try:
                s = NSScreen.mainScreen().frame()
                img = Quartz.CGWindowListCreateImage(
                    Quartz.CGRectMake(0, 0, int(s.size.width), 40),
                    Quartz.kCGWindowListOptionOnScreenOnly,
                    Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault)
                if img is not None:
                    rep = NSBitmapImageRep.alloc().initWithCGImage_(img)
                    if rep is not None:
                        data = rep.representationUsingType_properties_(
                            NSPNGFileType, None)
                        out[tag] = bool(data.writeToFile_atomically_(
                            os.path.expanduser(
                                f"~/Project/PeaseBar/tmp/offscreen_{tag}.png"),
                            True))
            except Exception as exc:  # noqa: BLE001
                out[f"{tag}_error"] = str(exc)
        return out

    @objc.python_method
    def _offscreen_ax_pos_test(self):
        """实验 4：对状态项 AX 元素本身写 AXPosition 移出屏幕。

        实验 3 实证 macOS 27 状态项无独立 CG 窗口（条带里只有 MenuBarAgent
        的全宽容器），CGS 单窗通道没目标；但 AX 能读到状态项元素（inventory
        本就靠它）——试对元素直接写 AXPosition（Ice/Dozer 系手法），回答：
        1) AXPosition 是否可写（settable / err）；
        2) 写后图标是否真的出屏（回读元素位置）；
        3) MenuBarAgent 会不会拉回（1s/6s 后回读 + 条带截图）。
        """
        import time as _t
        import ApplicationServices as AS
        from AppKit import NSScreen, NSBitmapImageRep, NSPNGFileType
        from peasebar import axutil
        items = inventory.list_items()[0]
        cfg = sections.load_config()
        targets = []
        for m in items:
            if m.is_stash_button or getattr(m, "stashed", False) or m.frame is None:
                continue
            sec = sections.section_of(cfg, sections.item_key(m))
            if (sec in (sections.SECTION_HIDDEN, sections.SECTION_ALWAYS_HIDDEN)
                    and menubar_drag.movable(m)):
                targets.append(m)
        out = {"time": _t.strftime("%H:%M:%S"),
               "targets": [f"{m.owner_app}/{m.label}" for m in targets],
               "ops": []}
        for m in targets:
            rec = {"target": f"{m.owner_app}/{m.label}",
                   "before": tuple(m.frame)}
            try:
                rec["settable"] = bool(AS.AXUIElementIsAttributeSettable(
                    m.el, "AXPosition", None))
                rec["err"] = int(axutil.set_position(m.el, 3000.0, 7.0))
                _t.sleep(1.0)
                f1 = axutil.element_frame(m.el)
                rec["after_1s"] = tuple(f1) if f1 else None
                _t.sleep(5.0)
                f6 = axutil.element_frame(m.el)
                rec["after_6s"] = tuple(f6) if f6 else None
            except Exception as exc:  # noqa: BLE001
                rec["error"] = str(exc)
            out["ops"].append(rec)
        # 1s / 6s 条带截图留视觉证据（图标到底还在不在栏上）
        for tag, wait in (("ax4_shot_1s", 1.0), ("ax4_shot_6s", 5.0)):
            _t.sleep(wait)
            try:
                s = NSScreen.mainScreen().frame()
                img = Quartz.CGWindowListCreateImage(
                    Quartz.CGRectMake(0, 0, int(s.size.width), 40),
                    Quartz.kCGWindowListOptionOnScreenOnly,
                    Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault)
                if img is not None:
                    rep = NSBitmapImageRep.alloc().initWithCGImage_(img)
                    if rep is not None:
                        data = rep.representationUsingType_properties_(
                            NSPNGFileType, None)
                        out[tag] = bool(data.writeToFile_atomically_(
                            os.path.expanduser(
                                f"~/Project/PeaseBar/tmp/{tag}.png"),
                            True))
            except Exception as exc:  # noqa: BLE001
                out[f"{tag}_error"] = str(exc)
        return out

    @objc.python_method
    def _apply_hidden_all(self):
        """取证（__APPLYALL__ 触发）：把配置为弹窗显示且仍可见的第三方图标逐枚
        收进真实收纳区，每步落日志——验证「容量随可见区变空自增强」假设。

        与启动同步的悲观护栏不同：一次收不进不算满（hide 内部已带 3 次重试与
        落点重算），连续 2 枚收不进才停。系统项（com.apple.*）对 ⌘-拖抵抗、
        拖不动，单独记 skip，不占失败计数。
        """
        import time
        inventory.set_stash_revealed(False)
        time.sleep(0.5)
        cfg = sections.load_config()
        log, tried = [], set()
        hidden_n = skip_n = fail_n = 0
        consec = 0
        for _round in range(24):
            items = inventory.list_items()[0]
            target = None
            for m in items:
                if m.is_stash_button or getattr(m, "stashed", False):
                    continue
                k = sections.item_key(m)
                if k in tried:
                    continue
                if sections.section_of(cfg, k) in (
                        sections.SECTION_HIDDEN, sections.SECTION_ALWAYS_HIDDEN):
                    target = m
                    break
            if target is None:
                log.append({"step": _round, "result": "done",
                            "note": f"隐藏 {hidden_n}，跳过 {skip_n}，失败 {fail_n}"})
                break
            tried.add(sections.item_key(target))
            if not menubar_drag.movable(target):
                skip_n += 1
                log.append({"step": _round,
                            "skip": f"{target.owner_app}/{target.label}",
                            "why": "系统项对 ⌘-拖抵抗，拖不动"})
                continue
            ok = menubar_drag.hide(target)
            time.sleep(0.5)
            fresh = menubar_drag._find(target)
            now_stashed = bool(getattr(fresh, "stashed", False)) if fresh else False
            log.append({"step": _round,
                        "hide": f"{target.owner_app}/{target.label}",
                        "drag_ok": bool(ok), "verified_stashed": now_stashed})
            if now_stashed:
                hidden_n += 1
                consec = 0
            else:
                fail_n += 1
                consec += 1
                if consec >= 2:
                    log.append({"step": _round, "result": "stopped",
                                "note": "连续 2 枚收不进：溢出区可能真满"})
                    break
        items = inventory.list_items()[0]
        return {"hidden_applied": hidden_n, "skipped": skip_n, "failed": fail_n,
                "log": log,
                "final_stashed": [f"{m.owner_app}/{m.label}" for m in items
                                  if getattr(m, "stashed", False)
                                  and not m.is_stash_button],
                "final_visible_3rd": [f"{m.owner_app}/{m.label}" for m in items
                                      if not getattr(m, "stashed", False)
                                      and not m.is_stash_button
                                      and (m.owner_bundle_id or "")
                                      != "com.apple.MenuBarAgent"]}

    @objc.python_method
    def _park_test(self, bid, spec_weight):
        """停车实验（__PARKTEST__ 触发）：把 bid 的真表权重写成停车值（默认
        50000=HIDDEN_BASE）→ 重启 MenuBarAgent → 观察这枚落点。

        要回答的问题：停车项是「彻底移除」（不占 7 位口袋 → 无限隐藏）
        还是「照样进口袋」（那路就封死了）。spec_weight="restore" 则从
        tmp/park_originals.json 恢复原权重（解除停车）。
        """
        import json as _json
        import subprocess
        import time
        if not bid:
            return {"ok": False, "why": "缺 bid 参数"}
        weights = layout_table.container_read_weights()
        key = None
        for k in weights:
            if k.startswith(f"status:{bid}::"):
                key = k
                break
        if key is None:
            return {"ok": False, "why": f"真表里找不到 {bid} 的键",
                    "known_keys": [k for k in weights if bid.split(".")[-1] in k]}
        orig_file = os.path.expanduser("~/Project/PeaseBar/tmp/park_originals.json")
        origs = {}
        if os.path.exists(orig_file):
            try:
                with open(orig_file, encoding="utf-8") as f:
                    origs = _json.load(f)
            except Exception:  # noqa: BLE001
                origs = {}
        origs.setdefault(key, weights[key])
        if spec_weight == "restore":
            w = origs.get(key)
            action = f"restore->{w}"
        else:
            try:
                w = float(spec_weight) if spec_weight else float(
                    layout_table.HIDDEN_BASE)
            except ValueError:
                w = float(layout_table.HIDDEN_BASE)
            action = f"park->{w}"
        try:
            with open(orig_file, "w", encoding="utf-8") as f:
                _json.dump(origs, f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass
        wr = layout_table.container_write_weights({key: w})
        # 重启 MenuBarAgent 让它重读表（launchd 秒级拉起，不碰任何 App）
        subprocess.run(["killall", "MenuBarAgent"], capture_output=True)
        time.sleep(4.0)
        items = inventory.list_items()[0]
        hit = None
        for m in items:
            if (m.owner_bundle_id or "").lower() == bid.lower():
                hit = m
                break
        obs = None
        if hit is not None:
            obs = {"app": hit.owner_app, "label": hit.label,
                   "stashed": bool(getattr(hit, "stashed", False)),
                   "frame": tuple(hit.frame) if hit.frame else None,
                   "ax_alive": hit.el is not None,
                   "notched": bool(getattr(hit, "notched", False))}
        stashed_n = sum(1 for m in items if getattr(m, "stashed", False)
                        and not m.is_stash_button)
        stash_list = [f"{m.owner_app}/{m.label}" for m in items
                      if getattr(m, "stashed", False) and not m.is_stash_button]
        return {"key": key, "action": action, "write": wr,
                "observed": obs, "stash_count": stashed_n,
                "stash_list": stash_list,
                "table_now": layout_table.container_read_weights().get(key)}

    @objc.python_method
    def _park_restore_all(self):
        """恢复停车实验改过的所有真表权重（tmp/park_originals.json 记录原值），
        并清掉误跑实验写进 controlcenter 的垃圾键，最后重启 Agent 让它重读。
        """
        import json as _json
        import subprocess
        import time
        orig_file = os.path.expanduser("~/Project/PeaseBar/tmp/park_originals.json")
        origs = {}
        if os.path.exists(orig_file):
            try:
                with open(orig_file, encoding="utf-8") as f:
                    origs = _json.load(f)
            except Exception:  # noqa: BLE001
                origs = {}
        upd = {k: v for k, v in origs.items() if v is not None}
        wr = (layout_table.container_write_weights(upd) if upd
              else {"ok": None, "why": "无原值记录"})
        clean = layout_table.clear_table()
        subprocess.run(["killall", "MenuBarAgent"], capture_output=True)
        time.sleep(3.0)
        return {"restored": upd, "write": wr, "cleanup": clean}

    def panelOpen_(self, timer):
        """主线程回调 1（__PANEL__ 取证）：打开救援面板，安排 4s 后截屏落盘。"""
        try:
            from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer
            from AppKit import NSApp
            panel = getattr(NSApp.delegate(), "rescue", None)
            if panel is None:
                print("[PeaseBar] 面板取证：找不到 rescue 控制器")
                return
            panel.show()
            # 第二段：秒开渲染用的是旧快照，后台采集刷新完（就地更新）再截屏，
            # 4s 足够采集+网格重排；期间 runloop 正常空转，不阻塞渲染。
            t2 = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                4.0, self, "panelShot:", None, False)
            NSRunLoop.mainRunLoop().addTimer_forMode_(t2, NSRunLoopCommonModes)
            print("[PeaseBar] 面板取证：已 show，4s 后截屏落盘")
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()

    def panelShot_(self, timer):
        """主线程回调 2（__PANEL__ 取证）：全屏截图+面板格子清单落盘+关面板。

        结果覆盖写 tmp/peasebar_exp_result.json（启动同步先写的是「已调度」占位）。
        面板实际渲染的格子 = rescue._snapshot["group"]，直接抓它核对有没有漏列。
        """
        import json as _json
        import time as _t
        from AppKit import NSScreen, NSBitmapImageRep, NSPNGFileType, NSApp
        r = {"time": _t.strftime("%H:%M:%S"), "panel_opened": True}
        panel = None
        try:
            panel = getattr(NSApp.delegate(), "rescue", None)
            snap = getattr(panel, "_snapshot", None)
            pf = getattr(panel, "panel", None)
            if pf is not None:
                # 面板可见性与位置：定位「截图里没面板」是渲染问题还是时机问题
                r["panel_visible"] = bool(pf.isVisible())
                r["panel_frame"] = str(pf.frame())
            if snap is None:
                r["panel_grid"] = None
                r["panel_grid_why"] = "快照为 None：面板从未采集成功，格子应为空态"
            else:
                r["panel_grid"] = [
                    {"app": m.owner_app, "label": m.label,
                     "stashed": bool(m.stashed), "notched": bool(m.notched)}
                    for m in snap.get("group", [])]
                r["panel_grid_count"] = len(r["panel_grid"])
        except Exception as exc:  # noqa: BLE001
            r["panel_grid_error"] = str(exc)
        # 全屏截图（含菜单栏 + 展开的面板本体；App 有屏幕录制权限）
        try:
            s = NSScreen.mainScreen().frame()
            img = Quartz.CGWindowListCreateImage(
                Quartz.CGRectMake(0, 0, int(s.size.width), int(s.size.height)),
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault)
            if img is not None:
                rep = NSBitmapImageRep.alloc().initWithCGImage_(img)
                if rep is not None:
                    data = rep.representationUsingType_properties_(NSPNGFileType, None)
                    r["shot_ok"] = bool(data.writeToFile_atomically_(
                        os.path.expanduser("~/Project/PeaseBar/tmp/panel_shot.png"),
                        True))
        except Exception as exc:  # noqa: BLE001
            r["shot_error"] = str(exc)
        # 截完关面板，恢复现场（面板 8s 超时也兜底，这里主动关更干净）
        try:
            if panel is not None:
                panel.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            with open(os.path.expanduser(
                    "~/Project/PeaseBar/tmp/peasebar_exp_result.json"),
                    "w", encoding="utf-8") as f:
                _json.dump(r, f, ensure_ascii=False, indent=2, default=str)
            print(f"[PeaseBar] 面板取证：截图={r.get('shot_ok')}，"
                  f"格子数={r.get('panel_grid_count')}")
        except Exception as exc:  # noqa: BLE001
            print(f"[PeaseBar] 面板取证：结果写入失败：{exc}")
        # 第三段：2s 后模拟点击面板格子（ToDesk 优先），真机验证「点击即用」
        try:
            from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer
            t3 = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                2.0, self, "panelClick:", None, False)
            NSRunLoop.mainRunLoop().addTimer_forMode_(t3, NSRunLoopCommonModes)
        except Exception as exc:  # noqa: BLE001
            print(f"[PeaseBar] 面板取证：安排点击段失败：{exc}")

    def panelClick_(self, timer):
        """主线程回调 3（__PANEL__ 取证）：模拟点击面板格子，验证「点击即用」。

        与真实点击完全同路：面板先收 → 后台 trigger 阶梯（AXPress → AXShowMenu
        → 合成右键），done 回调里记录触发方式与「新窗口出现」判据，随后截屏留证。
        """
        from peasebar import trigger as _trigger  # 包内绝对导入：顶层 import 在打包环境必挂
        from AppKit import NSApp
        panel = getattr(NSApp.delegate(), "rescue", None)
        snap = getattr(panel, "_snapshot", None) if panel is not None else None
        group = (snap or {}).get("group", [])
        target = None
        # 优先「原生隐藏」项（新通道核心场景：藏起的图标走显回→触发→收回链路）
        for m in group:
            if getattr(m, "native_hidden", False):
                target = m
                break
        # 次选「被收纳」项（旧机制场景：收纳项只能靠 AX 投递，最该验证）
        if target is None:
            for want in ("com.youqu.todesk.mac", None):
                for m in group:
                    if not m.stashed:
                        continue
                    if want is not None and (m.owner_bundle_id or "") != want:
                        continue
                    target = m
                    break
                if target is not None:
                    break
        if target is None and group:
            target = group[0]
        r = {"click_target": (f"{target.owner_app}/{target.label}"
                              if target is not None else None),
             "click_native": bool(getattr(target, "native_hidden", False))}
        self._panel_click_result = r
        if panel is not None:
            panel.close()  # 忠实模拟真实点击：面板先收再触发
        if target is None:
            print("[PeaseBar] 面板取证：面板无格子可点击")
            return

        def done(how, seen):
            r["trigger_how"] = str(how)
            r["trigger_seen"] = bool(seen)
            print(f"[PeaseBar] 面板取证：触发 {r['click_target']}：{how}，"
                  f"反应={'有' if seen else '无'}")
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "panelShot2:", None, False)

        try:
            if getattr(target, "native_hidden", False):
                # 与 onIconClick_ 同分流：原生隐藏格走显回→触发→收回复合链路
                from peasebar.panel import open_native_hidden_async
                open_native_hidden_async(target.owner_bundle_id, done)
            else:
                _trigger.open_item_async(target, done)
        except Exception as exc:  # noqa: BLE001
            r["click_error"] = str(exc)
            print(f"[PeaseBar] 面板取证：触发异常：{exc}")
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "panelShot2:", None, False)
        # 兜底：done 里 open_item 若崩在子线程不回调，12s 后强制落盘截屏
        try:
            from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer
            t4 = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                12.0, self, "panelShot2:", None, False)
            NSRunLoop.mainRunLoop().addTimer_forMode_(t4, NSRunLoopCommonModes)
        except Exception as exc:  # noqa: BLE001
            print(f"[PeaseBar] 面板取证：安排兑底截屏失败：{exc}")

    def panelShot2_(self, timer):
        """主线程回调 4（__PANEL__ 取证）：触发后截屏（原生菜单应已在屏）+ 落最终结果。"""
        import json as _json
        import time as _t
        from AppKit import NSScreen, NSBitmapImageRep, NSPNGFileType
        r = dict(getattr(self, "_panel_click_result", {}) or {})
        r["time"] = _t.strftime("%H:%M:%S")
        try:
            s = NSScreen.mainScreen().frame()
            img = Quartz.CGWindowListCreateImage(
                Quartz.CGRectMake(0, 0, int(s.size.width), int(s.size.height)),
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault)
            if img is not None:
                rep = NSBitmapImageRep.alloc().initWithCGImage_(img)
                if rep is not None:
                    data = rep.representationUsingType_properties_(NSPNGFileType, None)
                    r["menu_shot_ok"] = bool(data.writeToFile_atomically_(
                        os.path.expanduser(
                            "~/Project/PeaseBar/tmp/panel_menu_shot.png"), True))
        except Exception as exc:  # noqa: BLE001
            r["menu_shot_error"] = str(exc)
        try:
            with open(os.path.expanduser(
                    "~/Project/PeaseBar/tmp/panel_click_result.json"),
                    "w", encoding="utf-8") as f:
                _json.dump(r, f, ensure_ascii=False, indent=2, default=str)
            print(f"[PeaseBar] 面板取证：触发后截图={r.get('menu_shot_ok')}，"
                  f"反应={r.get('trigger_seen')}")
        except Exception as exc:  # noqa: BLE001
            print(f"[PeaseBar] 面板取证：结果写入失败：{exc}")

    @objc.python_method
    def _panel_open_test(self):
        """__PANEL__ 取证入口：只置标志，启动同步全部完成后才开面板（见 reconcile 末尾）。"""
        self._panel_test_armed = True
        return {"panel_test_scheduled": True,
                "note": "启动同步完成后开面板 → 4s 后截屏落盘"}

    @objc.python_method
    def _settings_open_test(self):
        """__SETTINGSWIN__ 取证入口：置标志，启动同步全部完成后开设置窗（布局页）。"""
        self._settings_test_armed = True
        return {"settings_test_scheduled": True,
                "note": "启动同步完成后开设置窗 → 4s 后截屏 + 三区清单落盘"}

    def settingsOpen_(self, timer):
        """主线程回调 1（__SETTINGSWIN__ 取证）：开设置窗（布局页），4s 后截屏。"""
        from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer
        self.show()  # show() 一律从布局页起步
        t = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            4.0, self, "settingsShot:", None, False)
        NSRunLoop.mainRunLoop().addTimer_forMode_(t, NSRunLoopCommonModes)

    def settingsShot_(self, timer):
        """主线程回调 2（__SETTINGSWIN__ 取证）：全屏截图 + 三区清单落盘 + 关窗。"""
        import json as _json
        import time as _t
        from AppKit import NSScreen, NSBitmapImageRep, NSPNGFileType
        r = {"time": _t.strftime("%H:%M:%S")}
        try:
            cfg = sections.load_config()
            buckets = sections.plan_sections(self.items, cfg)
            r["sections"] = {sec: [sections.item_key(m) for m in buckets[sec]]
                              for sec in _SECTION_ORDER}
        except Exception as exc:  # noqa: BLE001
            r["sections_error"] = str(exc)
        try:
            s = NSScreen.mainScreen().frame()
            img = Quartz.CGWindowListCreateImage(
                Quartz.CGRectMake(0, 0, int(s.size.width), int(s.size.height)),
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault)
            if img is not None:
                rep = NSBitmapImageRep.alloc().initWithCGImage_(img)
                if rep is not None:
                    data = rep.representationUsingType_properties_(NSPNGFileType, None)
                    r["shot_ok"] = bool(data.writeToFile_atomically_(
                        os.path.expanduser("~/Project/PeaseBar/tmp/settings_shot.png"),
                        True))
        except Exception as exc:  # noqa: BLE001
            r["shot_error"] = str(exc)
        try:
            if self.window is not None:
                self.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            with open(os.path.expanduser(
                    "~/Project/PeaseBar/tmp/settings_result.json"),
                    "w", encoding="utf-8") as f:
                _json.dump(r, f, ensure_ascii=False, indent=2, default=str)
        except Exception as exc:  # noqa: BLE001
            print(f"[PeaseBar] 设置取证：结果写入失败：{exc}")

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
                desc = err.localizedDescription() if err is not None else str(res)
                # 错误文案存标记而不只靠文本前缀判：切语言后前缀判据会失灵
                self._launch_error = tr("launch.deny", reason=desc)
                self.lbl_launch_status.setStringValue_(self._launch_error)
            else:
                self._launch_error = None
        except Exception as exc:  # noqa: BLE001 — 如实上屏，不假装成功
            sender.setState_(0 if want_on else 1)
            self._launch_error = tr("launch.fail", err=exc)
            self.lbl_launch_status.setStringValue_(self._launch_error)
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
        on, text = _login_status().get(st, (False, tr("login.unknown")))
        if getattr(self, "chk_launch", None) is not None:
            self.chk_launch.setState_(1 if on else 0)
        # 错误文案优先：刚失败过就别用状态码把失败信息盖掉（靠标记判，不靠文案前缀）
        if (getattr(self, "lbl_launch_status", None) is not None and st is not None
                and getattr(self, "_launch_error", None) is None):
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

    # ---------- 块渲染引擎（1:1 对标 Thaw 设置页的 Form / GroupBox / ScrollArea） ----------

    # 行内排版常量（对标 SwiftUI Form 的行距、卡片内边距与分隔线）
    _PAD = 14          # 卡片左右内边距
    _VPAD = 11         # 行上下内边距
    _TITLE_H = 20      # 标题行高
    _HELP_PT = 11      # 副说明字号
    _CARD_VPAD = 8     # 卡片上下留白
    _DIV = 1           # 行分隔线粗

    @objc.python_method
    def _subtab(self, page):
        """某页当前的子页签序号（未记录回 0）。"""
        return getattr(self, "_subtabs", {}).get(page, 0)

    @objc.python_method
    def _wrap_label(self, text, size, color):
        """多行换行的只读标签（labelWithString_ 默认单行，这里改成可换行）。"""
        lab = NSTextField.labelWithString_(text)
        lab.setFont_(NSFont.systemFontOfSize_(size))
        lab.setTextColor_(color)
        lab.setBezeled_(False)
        lab.setDrawsBackground_(False)
        lab.setEditable_(False)
        lab.setSelectable_(False)
        lab.setUsesSingleLineMode_(False)
        lab.setLineBreakMode_(0)  # NSLineBreakByWordWrapping
        cell = lab.cell()
        if cell is not None:
            cell.setWraps_(True)
            cell.setScrollable_(False)
        return lab

    @objc.python_method
    def _measure_h(self, text, width, size):
        """量一段文字在给定宽度下换行后的高（用于卡片随行高）。"""
        import math
        if not text:
            return 0
        font = NSFont.systemFontOfSize_(size)
        opts = NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading
        rect = (NSString.alloc().initWithString_(str(text))
                .boundingRectWithSize_options_attributes_(
                    NSMakeSize(width, 1000000.0), opts, {NSFontAttributeName: font}))
        return int(math.ceil(rect.size.height))

    @objc.python_method
    def _help_on(self):
        """是否渲染每行副说明（受「显示设置描述」偏好控制，即时生效）。"""
        return bool(sections.get_pref(sections.load_config(), "show_help_text"))

    @objc.python_method
    def _render_blocks(self, doc, blocks, start_y=10):
        """把声明式块列表往下排，返回用到的总高（doc 为翻转视图，y 向下）。"""
        y = start_y
        help_on = self._help_on()
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("tabbar"):
                y = self._blk_tabbar(doc, b, y)
            if b.get("heading"):
                y = self._blk_heading(doc, str(b["heading"]), y)
            if b.get("rows"):
                y = self._blk_card(doc, b["rows"], y, help_on)
            if b.get("standalone"):
                y = self._blk_standalone(doc, b["standalone"], y, help_on)
            if b.get("para"):
                y = self._blk_para(doc, str(b["para"]), y)
            y += 8
        return y + 6

    @objc.python_method
    def _blk_heading(self, doc, text, y):
        lab = NSTextField.labelWithString_(text)
        lab.setFont_(NSFont.boldSystemFontOfSize_(13))
        lab.setFrame_(NSMakeRect(EDGE, y, CONTENT_W - 2 * EDGE, 20))
        doc.addSubview_(lab)
        return y + 25

    @objc.python_method
    def _blk_tabbar(self, doc, b, y):
        """子页签条（对标 Thaw 页顶 TabButton 组：诊断/Repair/重置等）。"""
        opts = list(b["options"])
        page = b["page"]
        seg = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(EDGE, y, CONTENT_W - 2 * EDGE, 24))
        seg.setSegmentCount_(len(opts))
        seg.setTrackingMode_(1)  # selectOne
        for i, lab in enumerate(opts):
            seg.setLabel_forSegment_(lab, i)
        seg.setSelectedSegment_(min(self._subtab(page), len(opts) - 1))
        seg.setTarget_(self)
        seg.setAction_("onSubTab:")
        seg.setRepresentedObject_({"page": page})
        seg.setAccessibilityIdentifier_("tabbar-" + page)
        doc.addSubview_(seg)
        return y + 34

    @objc.python_method
    def _row_h(self, row, help_on):
        """算一行需要多高：标题带 + 副说明 + 控制件（宽控件另起一带）。"""
        h = self._TITLE_H + 2 * self._VPAD
        if help_on and row.get("help"):
            w = CONTENT_W - 2 * EDGE - 2 * self._PAD
            h += min(self._measure_h(row["help"], w, self._HELP_PT), 96) + 4
        ctl = row.get("ctl")
        if ctl and ctl[0] in ("toggles", "buttons"):
            h += 34  # 宽控件另起一带放
        # 无标题无说明的按钮行（如关于页「源码」块）：标题带是纯空白，压掉
        if (ctl and ctl[0] == "buttons" and not row.get("title")
                and not (help_on and row.get("help"))):
            h = 6 + 34 + self._VPAD
        return h

    @objc.python_method
    def _blk_card(self, doc, rows, y, help_on):
        """把一组行装进一张圆角卡片（对标 Thaw GroupBox），行间画分隔线。"""
        cw = CONTENT_W - 2 * EDGE
        heights = [self._row_h(r, help_on) for r in rows]
        card_h = sum(heights) + 2 * self._CARD_VPAD + self._DIV * (len(rows) - 1)
        card = NSView.alloc().initWithFrame_(NSMakeRect(EDGE, y, cw, card_h))
        card.setWantsLayer_(True)
        card.layer().setCornerRadius_(8.0)
        card.layer().setBackgroundColor_(
            Quartz.CGColorCreateGenericRGB(0.5, 0.5, 0.5, 0.10))
        doc.addSubview_(card)  # 背景先入，控件后入盖在上层
        ry = y + self._CARD_VPAD
        for i, (row, rh) in enumerate(zip(rows, heights)):
            self._draw_row(doc, row, EDGE + self._PAD, ry, cw - 2 * self._PAD, rh, help_on)
            ry += rh
            if i != len(rows) - 1:
                line = NSView.alloc().initWithFrame_(
                    NSMakeRect(EDGE + self._PAD, ry, cw - 2 * self._PAD, self._DIV))
                line.setWantsLayer_(True)
                line.layer().setBackgroundColor_(
                    Quartz.CGColorCreateGenericRGB(0.5, 0.5, 0.5, 0.25))
                doc.addSubview_(line)
                ry += self._DIV
        return y + card_h

    @objc.python_method
    def _draw_row(self, doc, row, x, y, w, h, help_on):
        """画一行：标题在顶左，副说明在标题下，控制件靠右对齐标题带（宽控件另起带）。"""
        title = row.get("title") or ""
        lab = NSTextField.labelWithString_(title)
        lab.setFont_(NSFont.systemFontOfSize_(12))
        lab.setFrame_(NSMakeRect(x, y + self._VPAD, w - 150, self._TITLE_H))
        doc.addSubview_(lab)
        cy = y + self._VPAD
        if help_on and row.get("help"):
            hh = min(self._measure_h(row["help"], w, self._HELP_PT), 96)
            help_lab = self._wrap_label(row["help"], self._HELP_PT, NSColor.secondaryLabelColor())
            help_lab.setFrame_(NSMakeRect(x, cy + self._TITLE_H + 2, w, hh))
            doc.addSubview_(help_lab)
        ctl = row.get("ctl")
        if ctl:
            self._draw_ctl(doc, ctl, x, cy, w, row)

    @objc.python_method
    def _draw_ctl(self, doc, ctl, x, cy, w, row):
        """按类型画控制件；返回值无关，状态从 cfg 读。"""
        kind = ctl[0]
        cfg = sections.load_config()
        ctl_w = {"switch": 52, "popup": 180, "slider": 200, "status": 96}.get(kind, 150)
        right_x = x + w - ctl_w
        band_y = cy if kind not in ("toggles", "buttons") else cy + self._TITLE_H + 30
        if kind == "buttons" and not (row.get("title") or row.get("help")):
            band_y = cy + 6  # 无标题按钮行：按钮贴行顶，不再给空标题带让位
        if kind == "switch":
            sw = NSSwitch.alloc().initWithFrame_(NSMakeRect(right_x, band_y, 52, 22))
            sw.setState_(1 if self._cfg_get(cfg, ctl[1]) else 0)
            sw.setTarget_(self)
            sw.setAction_("onPrefSwitch:")
            sw.setRepresentedObject_({"key": ctl[1]})
            sw.setAccessibilityIdentifier_("pref-" + ctl[1])
            doc.addSubview_(sw)
        elif kind == "popup":
            pop = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(right_x, band_y, ctl_w, 24), False)
            vals = ctl[2]  # [(value,label),...]
            if ctl[1] == "lang":
                cur = i18n.current_lang()  # 语言存顶层配置，不走 prefs 袋
            else:
                cur = self._cfg_get(cfg, ctl[1])
            for v, name in vals:
                pop.addItemWithTitle_(name)
            idx = next((i for i, (v, _) in enumerate(vals) if v == cur), 0)
            pop.selectItemAtIndex_(idx)
            pop.setTarget_(self)
            pop.setAction_("onPrefPopup:")
            pop.setRepresentedObject_({"key": ctl[1], "values": [v for v, _ in vals]})
            pop.setAccessibilityIdentifier_("pref-" + ctl[1])
            doc.addSubview_(pop)
        elif kind == "segmented":
            vals = ctl[2]
            labels = [lab for _, lab in vals]
            seg = NSSegmentedControl.alloc().initWithFrame_(
                NSMakeRect(right_x, band_y, ctl_w, 22))
            seg.setSegmentCount_(len(vals))
            seg.setTrackingMode_(1)
            for i, lab in enumerate(labels):
                seg.setLabel_forSegment_(lab, i)
            cur = self._cfg_get(cfg, ctl[1])
            seg.setSelectedSegment_(
                next((i for i, (v, _) in enumerate(vals) if v == cur), 0))
            seg.setTarget_(self)
            seg.setAction_("onPrefSegmented:")
            seg.setRepresentedObject_({"key": ctl[1], "values": [v for v, _ in vals]})
            seg.setAccessibilityIdentifier_("pref-" + ctl[1])
            doc.addSubview_(seg)
        elif kind == "slider":
            mn, mx, unit = ctl[2], ctl[3], ctl[4]
            sld = NSSlider.alloc().initWithFrame_(
                NSMakeRect(right_x, band_y + 2, ctl_w, 20))
            sld.setMinValue_(mn)
            sld.setMaxValue_(mx)
            sld.setDoubleValue_(float(self._cfg_get(cfg, ctl[1]) or mn))
            val_lab = NSTextField.labelWithString_(
                f"{int(round(sld.doubleValue()))}{unit}")
            val_lab.setFont_(NSFont.systemFontOfSize_(11))
            val_lab.setTextColor_(NSColor.secondaryLabelColor())
            val_lab.setFrame_(NSMakeRect(right_x, band_y - 14, ctl_w, 14))
            doc.addSubview_(val_lab)
            sld.setTarget_(self)
            sld.setAction_("onPrefSlider:")
            sld.setRepresentedObject_({"key": ctl[1], "label": val_lab, "unit": unit})
            sld.setAccessibilityIdentifier_("pref-" + ctl[1])
            doc.addSubview_(sld)
        elif kind == "text":
            fld = NSTextField.alloc().initWithFrame_(
                NSMakeRect(right_x, band_y, ctl_w, 24))
            fld.setStringValue_(str(self._cfg_get(cfg, ctl[1]) or ""))
            fld.setPlaceholderString_(ctl[2])
            fld.setEditable_(True)
            fld.setTarget_(self)
            fld.setAction_("onPrefText:")
            fld.setAccessibilityIdentifier_("pref-" + ctl[1])
            doc.addSubview_(fld)
        elif kind == "status":
            ok, txt = ctl[1], ctl[2]
            st = NSTextField.labelWithString_(txt)
            st.setFont_(NSFont.systemFontOfSize_(12))
            st.setTextColor_(NSColor.labelColor() if ok else NSColor.systemRedColor())
            st.setAlignment_(2)
            st.setFrame_(NSMakeRect(right_x, band_y, ctl_w, self._TITLE_H))
            doc.addSubview_(st)
        elif kind == "toggles":
            tx = x
            for label, key, _tip in ctl[1]:
                cb = NSButton.alloc().initWithFrame_(NSMakeRect(tx, band_y, 150, 22))
                cb.setButtonType_(3)  # NSButtonTypeSwitch：画成 macOS 原生复选框
                cb.setTitle_(label)
                cb.setFont_(NSFont.systemFontOfSize_(12))
                cb.setState_(1 if self._cfg_get(cfg, key) else 0)
                cb.setTarget_(self)
                cb.setAction_("onPrefSwitch:")
                cb.setRepresentedObject_({"key": key})
                cb.setAccessibilityIdentifier_("pref-" + key)
                doc.addSubview_(cb)
                tx += min(max(self._measure_h(label, 200, 12) + 22, 110), 210)
        elif kind == "buttons":
            bx = x
            for item in ctl[1]:
                label, action = item[0], item[1]
                width = item[2] if len(item) > 2 else 120
                b = NSButton.alloc().initWithFrame_(NSMakeRect(bx, band_y, width, 24))
                b.setTitle_(label)
                b.setBezelStyle_(1)
                b.setFont_(NSFont.systemFontOfSize_(12))
                b.setTarget_(self)
                b.setAction_(action)
                if len(item) > 3 and item[3] is not None:
                    b.setRepresentedObject_(item[3])
                b.setAccessibilityIdentifier_("btn-" + label)
                doc.addSubview_(b)
                bx += width + 8
        elif kind == "launch":
            # 开机自启走 SMAppService，不是普通 pref：建原生开关并接回旧 action，
            # 同时把句柄存回 self.chk_launch，_sync_launch_state 才能回读系统状态
            sw = NSSwitch.alloc().initWithFrame_(NSMakeRect(right_x, band_y, 52, 22))
            sw.setTarget_(self)
            sw.setAction_("onLaunchToggle:")
            sw.setAccessibilityIdentifier_("launch-at-login")
            doc.addSubview_(sw)
            self.chk_launch = sw
            self._sync_launch_state()
        elif kind == "timeout":
            fld = NSTextField.alloc().initWithFrame_(NSMakeRect(right_x, band_y, 90, 24))
            fld.setStringValue_(str(int(cfg.get("panel_timeout", 8))))
            fld.setEditable_(True)
            fld.setTarget_(self)
            fld.setAction_("onTimeoutChanged:")
            fld.setAccessibilityIdentifier_("panel-timeout")
            doc.addSubview_(fld)
            self.field_timeout = fld
        elif kind == "control_icon":
            pop = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(right_x, band_y, ctl_w, 24), False)
            for sym, _name in sections.CONTROL_ICONS:
                pop.addItemWithTitle_(sections.control_icon_label(sym))
            curic = next((i for i, (k, _) in enumerate(sections.CONTROL_ICONS)
                          if k == cfg.get("control_icon")), 0)
            pop.selectItemAtIndex_(curic)
            pop.setTarget_(self)
            pop.setAction_("onControlIconChanged:")
            pop.setAccessibilityIdentifier_("control-icon-picker")
            doc.addSubview_(pop)
            self.popup_icon = pop

    @objc.python_method
    def _cfg_get(self, cfg, key):
        """读偏好，支持点路径取嵌套 dict（如 modules.scripts）。"""
        parts = str(key).split(".")
        val = sections.get_pref(cfg, parts[0])
        for p in parts[1:]:
            val = val.get(p) if isinstance(val, dict) else None
        return val

    @objc.python_method
    def _cfg_set(self, cfg, key, value):
        """写偏好，支持点路径（先把顶层 dict 拷出来改完再写回，不就地改默认表）。"""
        parts = str(key).split(".")
        if len(parts) == 1:
            sections.set_pref(cfg, key, value)
            return
        root = parts[0]
        tree = dict(sections.get_pref(cfg, root) or {})
        cur = tree
        for p in parts[1:-1]:
            nxt = dict(cur.get(p) or {}) if isinstance(cur.get(p), dict) else {}
            cur[p] = nxt
            cur = nxt
        cur[parts[-1]] = value
        sections.set_pref(cfg, root, tree)

    @objc.python_method
    def _blk_para(self, doc, text, y):
        """整宽的段落说明（不受“显示设置描述”开关影响，永远可见）。"""
        w = CONTENT_W - 2 * EDGE
        hh = self._measure_h(text, w, 11)
        lab = self._wrap_label(text, 11, NSColor.secondaryLabelColor())
        lab.setFrame_(NSMakeRect(EDGE, y, w, hh))
        doc.addSubview_(lab)
        return y + hh + 4

    @objc.python_method
    def _blk_standalone(self, doc, items, y, help_on):
        """卡片外的平铺行（如拖拽提示、底部按钮组），不画背景。"""
        for row in items:
            rh = self._row_h(row, help_on)
            self._draw_row(doc, row, EDGE + self._PAD, y,
                           CONTENT_W - 2 * EDGE - 2 * self._PAD, rh, help_on)
            y += rh
        return y

    @objc.python_method
    def _persist(self, key, value, rebuild=True):
        """写一个 pref 并落盘；主题开关顺手应用；默认重建页面回显新状态。"""
        cfg = sections.load_config()
        self._cfg_set(cfg, key, value)
        sections.save_config(cfg)
        if key == "theme":
            self._apply_theme(value)
        if rebuild:
            self._rebuild()
        if self.on_changed:
            self.on_changed()

    @objc.python_method
    def _apply_theme(self, mode):
        """把 theme 偏好映射到 NSApplication.appearance（拿不到就静默跳过）。"""
        try:
            if mode == "light":
                name = "NSAppearanceNameAqua"
            elif mode == "dark":
                name = "NSAppearanceNameDarkAqua"
            elif mode == "black":
                name = "NSAppearanceNameDarkAqua"
            else:
                name = None
            app = NSApplication.sharedApplication()
            if name is None:
                app.setAppearance_(None)
            else:
                app.setAppearance_(NSAppearance.appearanceNamed_(name))
        except Exception as exc:  # noqa: BLE001 — 主题非致命，失败不拦设置窗
            print(f"[PeaseBar] 应用主题失败（忽略）：{exc}")

    # ---------- 偏好控件的 action ----------

    def onPrefSwitch_(self, sender):
        meta = sender.representedObject()
        key = str(meta["key"])
        on = int(sender.state()) == 1
        self._persist(key, on)
        if key == "cc_tick_enabled":
            # 唯一一个需要即时生效的通用开关：停/重挂 app.py 装的 60s 核对定时器
            try:
                self._apply_cc_tick(on)
            except Exception as exc:  # noqa: BLE001
                print(f"[PeaseBar] 设置：自动核对开关生效失败：{exc}")

    @objc.python_method
    def _apply_cc_tick(self, on):
        """「每分钟自动核对显隐」开关即时生效：停掉/重挂 60s 定时器。
        timer 由 app.py 启动时挂到 self.tick_timer；离线（测试）没挂过就只落盘。"""
        t = getattr(self, "tick_timer", None)
        if t is not None:
            t.invalidate()
            self.tick_timer = None
        if not on:
            print("[PeaseBar] 设置：自动核对已停用（60s 定时器已停）")
            return
        from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer
        nt = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            60.0, self, "syncCCTick:", None, True)
        NSRunLoop.mainRunLoop().addTimer_forMode_(nt, NSRunLoopCommonModes)
        self.tick_timer = nt
        print("[PeaseBar] 设置：自动核对已开启（60s 定时器已重挂）")

    def onPrefPopup_(self, sender):
        meta = sender.representedObject()
        key = str(meta["key"])
        values = list(meta["values"])
        i = int(sender.indexOfSelectedItem())
        val = values[i] if 0 <= i < len(values) else values[0]
        if key == "lang":
            # 界面语言：写顶层配置 + 失效词条缓存，整窗重建立即换语言
            if i18n.set_lang(val):
                print(f"[PeaseBar] 设置：界面语言切换为 {val}")
            self._rebuild()
            return
        self._persist(key, val)

    def onPrefSegmented_(self, sender):
        meta = sender.representedObject()
        values = list(meta["values"])
        i = int(sender.selectedSegment())
        self._persist(str(meta["key"]), values[i] if 0 <= i < len(values) else values[0])

    def onPrefSlider_(self, sender):
        meta = sender.representedObject()
        val = float(sender.doubleValue())
        lab = meta.get("label")
        if lab is not None:
            lab.setStringValue_(f"{int(round(val))}{meta.get('unit', '')}")
        self._persist(str(meta["key"]), int(round(val)), rebuild=False)

    def onPrefText_(self, sender):
        meta = sender.representedObject()
        self._persist(str(meta["key"]), str(sender.stringValue()), rebuild=False)

    def onSubTab_(self, sender):
        meta = sender.representedObject()
        page = str(meta["page"])
        if not hasattr(self, "_subtabs"):
            self._subtabs = {}
        self._subtabs[page] = int(sender.selectedSegment())
        self._rebuild()

    # ---------- 各页声明式规格（1:1 对标 Thaw 各设置页的 AX 树） ----------

    @objc.python_method
    def _spec_general(self):
        # 只留接了真后端的控件：开机自启（SMAppService）、面板超时、
        # 显示描述（渲染端读取）、控制图标选择（即时生效）。
        # 精简模式/Dock 图标/语言/主题/收起 App 菜单等无后端的开关已摘除
        # ——宁少勿假，拨了没反应的开关比没有更伤体验。
        return [
            _block(tr("spec.general.app"), [
                _row_launch(help=tr("launch.help")),
                _row_timeout(help=tr("timeout.help")),
                _row_switch("show_help_text", tr("showhelp.title"),
                            help=tr("showhelp.help")),
                _row_popup("lang", tr("lang.title"), i18n.lang_names(),
                           help=tr("lang.help")),
            ]),
            _block(tr("cicon.caption"), [
                _row_cicon(help=tr("cicon.help")),
            ]),
        ]

    @objc.python_method
    def _spec_visibility(self):
        """显隐规则页：只讲 PeaseBar 真有的机制——隐藏通道状态 + 自动核对开关。
        （旧版整页是 Thaw 的「点击/悬停/滚动显示隐藏项」等功能清单，后端从未实现，
        拨了没反应；2026-11-24 起改为真实内容。）"""
        ax_ok = bool(AXIsProcessTrusted())
        writable = ccnative.is_writable()
        n_side = len(ccnative.last_hidden())
        return [
            _para(tr("vis.intro")),
            _block(tr("vis.channel"), [
                _row_status(tr("vis.cc.title"), writable,
                            tr("vis.ok") if writable else tr("vis.bad"),
                            help=tr("vis.cc.help")),
                _row_status(tr("vis.ax.title"), ax_ok,
                            tr("vis.ok2") if ax_ok else tr("vis.bad2"),
                            help=tr("vis.ax.help")),
                _row_status(tr("vis.sidecar.title"), True,
                            tr("vis.sidecar.status", n=n_side),
                            help=tr("vis.sidecar.help")),
            ]),
            _block(tr("vis.tick"), [
                _row_switch("cc_tick_enabled", tr("vis.tick.row"),
                            help=tr("vis.tick.help")),
            ]),
        ]

    # （外观/工具栏/显示器三页已删：这些功能的后端从未实现，摆着只会让用户
    #   拨了没反应；2026-11-24 起 PAGES 与侧栏也不再包含它们。）

    @objc.python_method
    def _spec_shortcuts(self):
        active = self._subtab("shortcuts")
        tabs = [tr("sc.tab.0"), tr("sc.tab.1"), tr("sc.tab.2"), tr("sc.tab.3")]
        blocks = [_tabbar("shortcuts", tabs)]
        rows_map = {
            0: [(tr("sc.showhide"), "⌥⌘B"), ("交换显示与隐藏项", ""), ("切换“再次隐藏”", ""),
                ("切换禅模式", ""), ("隐藏或显示 App 菜单", ""), ("显示菜单栏", "")],
            1: [("下一个项目", ""), ("上一个项目", ""), ("触发选中项", ""), ("重命名选中项", "")],
            2: [(tr("sc.moveto.up"), "⌥↑"), (tr("sc.moveto.down"), "⌥↓"),
                (tr("sc.prev"), "⌥←"), (tr("sc.next"), "⌥→"), (tr("sc.undo"), "⌘Z")],
            3: [("打开工具栏", ""), ("关闭工具栏", "")],
        }
        # 纯速查展示：不放「录制」假按钮（自定义快捷键无后端，宁少勿假）；
        # 布局页那组（⌥↑↓←→ / ⌘Z）是真实内置键位，右键菜单里也有同等操作
        rows = [{"title": f"{label}　{combo}" if combo else label,
                 "help": None, "ctl": None}
                for label, combo in rows_map.get(active, [])
                if combo]  # 没内置键位的项不列（列了就是摆设）
        blocks.append(_block(tabs[active], rows))
        blocks.append(_para(tr("sc.built")))
        return blocks

    @objc.python_method
    def _spec_profiles(self):
        cfg = sections.load_config()
        profs = self._cfg_get(cfg, "profiles") or []
        blocks = [{"heading": tr("prof.saved"), "rows": [
            {"title": tr("prof.empty"), "help": tr("prof.empty.help"), "ctl": None},
        ]}] if not profs else []
        prof_rows = [{"title": str(p.get("name", tr("prof.n", n=i + 1))), "help": None,
                      "ctl": ("buttons", [(tr("prof.apply"), "onApplyProfile:", 70, {"idx": i}),
                                          (tr("prof.delete"), "onDeleteProfile:", 64, {"idx": i})])}
                     for i, p in enumerate(profs)]
        if prof_rows:
            blocks.append({"heading": tr("prof.saved"), "rows": prof_rows})
        blocks.append(_block(tr("prof.new"), [
            _row_text("new_profile_name", tr("prof.name"), tr("prof.name.ph")),
            _row_buttons("", [(tr("prof.save"), "onSaveProfile:", 120)]),
        ]))
        return blocks

    @objc.python_method
    def _spec_privacy(self):
        ax_ok = bool(AXIsProcessTrusted())
        rec_ok = bool(capture.has_screen_permission())
        return [
            _para(tr("priv.intro")),
            _block(tr("priv.perm"), [
                _row_status(tr("priv.ax.title"), ax_ok,
                            tr("vis.ok2") if ax_ok else tr("vis.bad2"),
                            help=tr("priv.ax.help")),
                _row_status(tr("priv.table.title"), True, tr("vis.ok2"),
                            help=tr("priv.table.help")),
                _row_status(tr("priv.screen.title"), rec_ok,
                            tr("vis.ok2") if rec_ok else tr("priv.opt"),
                            help=tr("priv.screen.help")),
                _row_buttons("", [(tr("common.open_settings"), "onOpenAXSettings:", 120)]),
            ]),
            _block(tr("priv.can"), [
                _row_buttons("", [(tr("priv.grab"), "onRecapture:", 100)]),
            ]),
        ]

    @objc.python_method
    def _spec_troubleshoot(self):
        active = self._subtab("troubleshoot")
        tabs = [tr("trb.tab.0"), tr("trb.tab.1"), tr("trb.tab.2")]
        blocks = [_tabbar("troubleshoot", tabs)]
        if active == 0:
            blocks += [
                _block(tr("trb.diag"), [
                    _row_switch("detailed_logging", tr("trb.log.title"),
                                help=tr("trb.log.help")),
                ]),
                _block(tr("trb.report"), [
                    {"title": tr("trb.log.row"), "help": tr("trb.log.row.help"),
                     "ctl": ("buttons", [(tr("trb.log.finder"), "onOpenLog:", 150)])},
                    {"title": tr("trb.items"), "help": tr("trb.items.help", n=len(self.items)),
                     "ctl": ("buttons", [(tr("common.recapture"), "onRecapture:", 120)])},
                ]),
            ]
        elif active == 1:
            blocks += [
                _block(tr("trb.fix"), [
                    _row_buttons(tr("trb.perm"), [(tr("common.ax_settings"), "onOpenAXSettings:", 150),
                                     (tr("trb.screen"), "onRequestPermission:", 150)]),
                    _row_buttons(tr("trb.icon"), [(tr("common.recapture"), "onRecapture:", 120)]),
                ]),
            ]
        else:
            blocks += [
                _block(tr("trb.reset"), [
                    {"title": tr("trb.reset.title"), "help": tr("trb.reset.help"),
                     "ctl": ("buttons", [(tr("trb.reset.btn"), "onResetLayout:", 110)])},
                ]),
            ]
        return blocks

    @objc.python_method
    def _spec_about(self):
        from peasebar import __version__
        return [
            {"heading": "PeaseBar", "rows": [
                {"title": tr("about.version", v=__version__),
                 "help": tr("about.desc"),
                 "ctl": None},
            ]},
            _block(tr("about.src"), [
                _row_buttons("", [(tr("about.copy"), "onCopyVersion:", 120),
                              (tr("about.repo"), "onOpenRepo:", 120)]),
            ]),
            _para(tr("about.copyright")),
        ]

    # ---------- 新增 action：配置管理、间距、诚实占位 ----------

    def onSaveProfile_(self, sender):
        """把当前分区+顺序存为一个命名配置（写入 prefs.profiles）。"""
        cfg = sections.load_config()
        name = str(self._cfg_get(cfg, "new_profile_name") or "").strip()
        if not name:
            print("[PeaseBar] 配置：名称为空，未保存")
            return
        prof = {"name": name, "sections": dict(cfg.get("sections") or {}),
                "order": list(cfg.get("order") or [])}
        profs = [p for p in (self._cfg_get(cfg, "profiles") or []) if p.get("name") != name]
        profs.append(prof)
        self._cfg_set(cfg, "profiles", profs)
        sections.set_pref(cfg, "new_profile_name", "")
        sections.save_config(cfg)
        print(f"[PeaseBar] 配置：已保存配置“{name}”")
        self._rebuild()

    def onApplyProfile_(self, sender):
        """应用一个配置：把它保存的分区/顺序写回主配置。"""
        idx = int(sender.representedObject()["idx"])
        cfg = sections.load_config()
        profs = self._cfg_get(cfg, "profiles") or []
        if not (0 <= idx < len(profs)):
            return
        p = profs[idx]
        cfg["sections"] = dict(p.get("sections") or {})
        cfg["order"] = list(p.get("order") or [])
        sections.save_config(cfg)
        print(f"[PeaseBar] 配置：应用“{p.get('name')}”")
        self._rebuild()
        if self.on_changed:
            self.on_changed()

    def onDeleteProfile_(self, sender):
        """删除一个配置。"""
        idx = int(sender.representedObject()["idx"])
        cfg = sections.load_config()
        profs = list(self._cfg_get(cfg, "profiles") or [])
        if 0 <= idx < len(profs):
            removed = profs.pop(idx)
            self._cfg_set(cfg, "profiles", profs)
            sections.save_config(cfg)
            print(f"[PeaseBar] 配置：删除“{removed.get('name')}”")
            self._rebuild()

    def onResetSpacing_(self, sender):
        """把间距重置为默认值（真实间距重启菜单栏应用排在后续版本）。"""
        self._persist("spacing", 0.0)
        print("[PeaseBar] 显示器：间距重置为默认")

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
        lab = getattr(self, "lbl_about_status", None)
        if lab is not None:
            lab.setStringValue_(tr("about.copied", text=text))
        print(f"[PeaseBar] 设置：已复制版本信息——{text}")

    def onOpenRepo_(self, sender):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(REPO_URL))

    def onOpenLog_(self, sender):
        if not os.path.exists(LOG_PATH):
            print("[PeaseBar] 设置：尚无日志文件")
            return
        NSWorkspace.sharedWorkspace().openFile_(LOG_PATH)
        print(f"[PeaseBar] 设置：已请求打开 {LOG_PATH}")

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
        """弹快照回草稿并重建；栈空时返回 False（让 ⌘Z 响铃，不静默默响）。

        撤销也只回退草稿副本（暂存+应用模式）：应用前的撤销把界面退回去；
        应用后撤销则把盘上配置拍成新草稿退回去——两者都要再点「应用改动」
        才真正落盘生效。"""
        if not self._undo:
            return False
        snap = self._undo.pop()
        self._begin_pending()
        sections.restore_snapshot(self._pending_cfg, snap)
        print("[PeaseBar] 设置：撤销一步（草稿，待应用）")
        self._rebuild()
        return True

    def _commit_order_note(self, buckets, note):
        """把一次编辑（分桶结果）物化成显式顺序写入草稿，再重建界面（不落盘）。"""
        self._begin_pending()
        cfg = self._pending_cfg
        self._push_undo(cfg)
        sections.store_order(cfg, sections.flatten(buckets))
        print(f"[PeaseBar] 设置：{note}（暂存，待应用）")
        self.buckets = buckets  # 先同步状态再重建：持续 ⌥→ 时第二下才不会拿着旧分桶算
        self._rebuild()

    def reorderSelected_by_(self, key, delta):
        """同区内前移/后移一格。返回是否真动了（动不了不记撤销点）。

        重排本体在 `sections.reorder_bucket`（纯函数、单测直接测它），
        这里负责「取位置→写草稿→刷界面」；真实菜单栏的顺序/显隐统一改在
        点「应用改动」时一次对齐（暂存+应用模式，2026-11-24）。
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
        """写草稿 + 刷新（按钮、右键菜单、⌥↑↓、⌘1/2/3 共用的唯一入口）。

        命名注意（PyObjC 的选择子映射，规则来自 objc._transform.default_selector）：
        方法名只带**一个**下划线时会被当成选择子（尾部的 `_` 换成 `:`，
        只有前导 `_` 则当零参选择子），参数对不上就在建类时报 BadPrototypeError
        （启动即死）。所以：带参方法要么写成 `xxx_y_`（冒号数 = 参数数），
        要么名字里至少放两个下划线（`_commit_order_note` 这种就根本不导出）。

        暂存+应用模式：只改草稿副本不落盘；换区的真实菜单栏镜像统一改到
        「应用改动」里一次做完（sync_cc_now + 收纳区放出 + 顺序对齐）。
        """
        if not key or target is None:
            return
        # 原地不动不算改动：不记撤销点也不开草稿（免得 ⌘Z 看起来失灵、标题白挂点）
        if sections.section_of(self._layout_cfg(), key) == target:
            return
        self._begin_pending()
        cfg = self._pending_cfg
        self._push_undo(cfg)
        sections.set_section(cfg, key, target)
        # 换区后抻到目标区末尾：不重排的话新位置由旧 order 位次决定，跳来跳去没规律
        buckets = sections.plan_sections(self.items, cfg)
        item = self._item_by_key(key)
        if item is not None:
            rest = [it for it in buckets[target] if sections.item_key(it) != key]
            buckets[target] = rest + [item]
        sections.store_order(cfg, sections.flatten(buckets))
        print(f"[PeaseBar] 设置：{key}（{item.label if item else '?'}）→ "
              f"{sections.SECTION_LABELS[target]}（暂存，待应用）")
        self.buckets = buckets
        self._rebuild()

    @objc.python_method
    def _mirror_section_move(self, key, target):
        """把「换区」镜像到真实菜单栏（Phase 10）：移进弹窗/永久隐藏 → 系统真收纳（图标从
        菜单栏消失）；移回菜单栏显示 → 从溢出区拖回可见段。只在 real_bar 开、且是可拖的
        第三方图标时动手；苹果系统项对合成 ⌘-拖有抵抗（同 Thaw），一律跳过。"""
        if not self.opt("real_bar"):
            return
        # 关键：真实菜单栏从开窗到现在可能已经移位（时钟/控制中心宽度变化、别的 App 增减图标），
        # 缓存的 frame 早就过期，直接拿旧坐标 ⌘-拖会抓到空白处或别的图标，看起来就是「没反应」。
        # 所以动手前先从实时盘点把坐标刷新一遍，再按 key 找回要拖的那枚。
        self._resync_frames()
        item = self._item_by_key(key)
        if item is None:
            return
        did = False
        try:
            if target in (sections.SECTION_HIDDEN, sections.SECTION_ALWAYS_HIDDEN):
                did = self._real_hide(item, always=(target == sections.SECTION_ALWAYS_HIDDEN))
            elif target == sections.SECTION_VISIBLE:
                did = self._real_reveal(item)
        except Exception as exc:  # 真实菜单栏同步任何异常都不能弄崩设置窗
            print(f"[PeaseBar] 真实菜单栏同步（移区）失败：{exc}")
        if did:
            self._resync_frames()

    @objc.python_method
    def _mirror_section_reorder(self, sec, key):
        """把「同区内前后移」镜像到真实菜单栏：只有「菜单栏显示」区对应真实菜单栏，
        弹窗/永久隐藏区里的项本就被系统收着，没什么可排的。"""
        if not self.opt("real_bar") or sec != sections.SECTION_VISIBLE:
            return
        # 同 _mirror_section_move：拖之前刷新实时坐标，避免拿过期 frame 拖空。
        self._resync_frames()
        group = self.buckets.get(sec) or []
        idx = next((i for i, it in enumerate(group)
                    if sections.item_key(it) == key), None)
        if idx is None:
            return
        src = self._item_by_key(key)
        if src is None or not menubar_drag.movable(src):
            return
        # 落点锚：优先拿它左邻（拖到其右），没左邻就拿右邻（拖到其左）
        after = True
        anchor_item = None
        if idx > 0:
            anchor_item = self._item_by_key(sections.item_key(group[idx - 1]))
        elif idx + 1 < len(group):
            anchor_item = self._item_by_key(sections.item_key(group[idx + 1]))
            after = False
        if anchor_item is None:
            return
        try:
            if menubar_drag.reorder(src, anchor_item, after=after):
                self._resync_frames()
        except Exception as exc:
            print(f"[PeaseBar] 真实菜单栏同步（改序）失败：{exc}")

    @objc.python_method
    def _resync_frames(self):
        """真实 ⌘-拖后系统会重新排布菜单栏，本地缓存的 frame 立刻过期；只按 key 回写
        frame/stashed/notched 三个几何字段，不重截图（快，不影响已显示的图）。"""
        all_items, _ = inventory.list_items()
        fresh = {sections.item_key(m): m for m in all_items if not m.is_stash_button}
        for it in self.items:
            f = fresh.get(sections.item_key(it))
            if f is not None:
                it.frame = f.frame
                it.stashed = f.stashed
                it.notched = f.notched

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
            text = tr("layout.sel.none")
        else:
            owner = tr("common.system") if item.owner_app == "系统" else item.owner_app
            sec, idx = pos
            text = tr("layout.sel.item", label=item.label, owner=owner,
                      sec=sections.section_label(sec), idx=idx + 1,
                      total=len(self.buckets[sec]))
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
        # 应用按钮：有草稿才可点；应用流程后台进行中转忙（标题也换成「应用中…」）
        if getattr(self, "btn_apply", None) is not None:
            applying = getattr(self, "_applying", False)
            self.btn_apply.setTitle_(
                tr("layout.applying") if applying else tr("layout.apply"))
            self.btn_apply.setEnabled_(
                getattr(self, "_pending_cfg", None) is not None and not applying)
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
        if getattr(self, "_pending_cfg", None) is not None:
            # 草稿是整份配置副本：应用时会整份写盘，这里的改动先同步进草稿
            # 才不会被「应用改动」冲掉
            self._pending_cfg["panel_timeout"] = value
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
