#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""菜单栏图标位图抓取（F3 只显示图标 / 设置窗口图标化的基础）。

业务参照 Thaw（tmp/Thaw-app）：它同样**截菜单栏条带再按 AX frame 裁剪**
（DisplayStripCaptureSession + AXBoundsCropper），因为 macOS 27 上单个状态项
窗口不暴露给 CGWindowList（取证：25 项全部匹配不到窗口）。Thaw 的完整管线
还有磁盘缓存、重捕获调度、污染判定，我们 v1 只做必要四步：

    截条带 → 按 frame 裁剪（裁进条带高度）→ 抠掉近似统一的背景 → 裁掉透明边距
      → 贴边条（AX frame 窄于真实绘制宽）先向邻居借空白把窗口撑大再裁一次；
      宽条（图标+数字/文字复合）不拒收，整体同比例收进显示框（Thaw
      MenuBarItemRowImage.drawnSize 的做法：宽超上限就连带高度一起缩）
    → 单色字形判定，成立则标记 template（跟随界面明暗着色）

    Phase 9 口径变更（用户定调：「显示一半图标的，就完整显示同比例缩小」）：
    旧版把宽条一律拒收换成 App 图标兜底，用户看到的是「我的图标没了/半截」，
    现在宁可图小一点，也要把抓到的像素完整地按比例画出来。

权限：截屏需「屏幕录制」授权（与辅助功能相互独立，同 T16 按 bundle 记账）。
无权限时截不到像素，但 UI 不能因此显示名字——本模块提供**图标兜底链**
（系统模块 SF 符号 → 归属 App 图标 → 通用占位符号），保证每个格子永远是图标。

纯函数（背景色/抠像/裁边/单色判定）只吃 numpy 数组，可离线单测。
"""
import Quartz
from AppKit import (
    NSBitmapImageRep,
    NSImage,
    NSRunningApplication,
    NSScreen,
    NSWorkspace,
)
from Foundation import NSSize

from peasebar import sections

# 菜单栏逻辑高度兜底值（非刘海屏的老尺寸）；真实高度一律走 menu_bar_height()
MENU_BAR_HEIGHT = 24.0

# 抠像阈值：与 Thaw separatedFromNearUniformBackground(maxColorDistance: 36) 一致
MAX_COLOR_DISTANCE = 36.0
# 单色字形判定阈值：与 Thaw isSingleInkGlyph(vividChroma: 0.3, maximumVividShare: 0.02) 一致
VIVID_CHROMA = 0.3
MAX_VIVID_SHARE = 0.02
# 裁边后保留的留白（点，按 scale 换算成像素）
TRIM_PAD = 2
# 裁图抠像后至少要剩这么多像素，否则视为「这一格根本没画上图标」。
# 菜单栏被全屏 App 遮住时整条条带都是黑的，裁出来是纯背景 → 抠像后一个不剩，
# 那种全透明图交给按钮就是空白格子（P42 实测 16 格空白），必须当成截不到走兜底。
MIN_GLYPH_PIXELS = 20

# 离谱宽高比上限：超过它说明裁窗口串到了别的图标（整条误裁），才拒收走兜底。
# 注意这不再是「宽图标拒收」的阈值——Phase 9 起宽条照样收，只是同比例缩小。
MAX_ASPECT = 10.0

# 贴边时向邻居借空白的上下限（点）：AX frame 常窄于真实绘制宽，邻居左边界以内的
# 像素必然不属于邻居，借过来重裁就能拿到完整图标（借太多会裁进邻居字形）。
ROOM_MAX = 90.0
# 拿不到邻居信息时的保底借宽：就算 frame 紧挨着也总能借到几个像素的空白
ROOM_MIN = 12.0
# 同一字形内部允许的最大空白（点）：小于图标间距，大于数字/字符间隙
INK_GAP_PT = 4.0

# 抓取结果缓存：{item_key: (NSImage, 代际)}；盘点刷新时代际递增使旧缓存失效
_cache = {}
_generation = 0

# 最近一次 capture_icons 的取图构成（设置页提示用，只读不参与决策）。
# 初值按「还没截过」给：cropped/fallback 为 0，bar_drawn 乐观假定为 True。
last_stats = {"cropped": 0, "fallback": 0, "permission": True, "bar_drawn": True}

# ---------- 图标兜底（参照 Thaw OverflowFallbackIcon：永远给图，不给字） ----------

# App 图标绘制上限（Thaw MenuBarItemDisplayImage.appIconHeight = 18pt）
APP_ICON_MAX_H = 18.0
# 裁图点尺寸上限（比菜单栏字形略高，宽度对齐 Thaw MenuBarItemRowImage.maxWidth
# 120pt）：宽高各自收口、比例不变（fit_box），显示端再按格子大小二次同比例缩放。
GLYPH_MAX_H = 18.0
GLYPH_MAX_W = 120.0
# 抓取像素的高度上限：比兜底符号的 18pt 宽松，给两行文字图标（网速那类）留出可读尺寸；
# 显示端（面板格/布局条）再按自己格子用 scaled_copy 同比例二次收小
CAPTURE_MAX_H = 28.0
# 谁都对不上时的占位符号（Thaw MenuBarItemPlaceholderStyle.symbolName）
GENERIC_SYMBOL = "menubar.rectangle"

# 系统模块关键词 → SF Symbol（有序匹配：标签里出现任一关键词即命中）。
# 我们的标签来自 AXDescription（跟随系统语言，中文系统里是「控制中心」「时钟」等），
# 与 Thaw 用 tag.title 匹配英文目录不同，因此这里按中英关键词匹配。
SYSTEM_GLYPHS = (
    (("wi-fi", "wi‑fi", "wifi", "无线局域网", " WLAN"), "wifi"),
    (("蓝牙", "bluetooth"), "bluetooth"),
    (("隔空投送", "airdrop"), "airdrop"),
    (("电池", "battery"), "battery.100"),
    (("电源适配器", "power"), "powerplug"),
    (("声音", "音量", "sound", "volume"), "speaker.wave.2.fill"),
    (("键盘", "keyboard"), "keyboard"),
    (("显示器", "屏幕亮度", "display"), "display"),
    (("屏幕镜像", "screen mirroring"), "rectangle.on.rectangle"),
    (("专注", "勿扰", "focus"), "moon.fill"),
    (("定时器", "倒计时", "timer"), "timer"),
    (("正在播放", "now playing", "媒体"), "play.circle"),
    (("用户", "切换", "user"), "person.crop.circle"),
    (("时钟", "clock", "时间机器"), "clock"),
    (("siri",), "siri"),
    (("聚焦", "spotlight"), "magnifyingglass"),
    (("控制中心", "control center", "controlcenter", "bentobox"), "square.grid.2x2"),
    (("隐藏菜单栏项目", "显示隐藏"), "chevron.left"),
    (("麦克风", "摄像头", "audiovideo"), "video"),
)

# 兜底图缓存：按 pid / bundle 记账（Thaw 同法：反复取值会不停分配对象）
_symbol_cache = {}
_app_icon_by_pid = {}
_app_icon_by_bundle = {}
_controlcenter_icon = None


def _symbol_image(name):
    """SF Symbol → template NSImage（公开符号找不到时试私有符号集）。

    蓝牙/AirDrop 只存在于 macOS 私有符号集（Thaw SystemModuleGlyph 同法）。
    """
    if name in _symbol_cache:
        return _symbol_cache[name]
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if img is None:
        # 私有符号加载器（蓝牙/AirDrop 只在私有集里），PyObjC 下按同名选择子暴露
        loader = getattr(NSImage, "imageWithPrivateSystemSymbolName_accessibilityDescription_", None)
        if loader is not None:
            try:
                img = loader(name, None)
            except Exception:
                img = None
    if img is not None:
        img.setTemplate_(True)
    _symbol_cache[name] = img
    return img


def _fit_height(img, max_h):
    """按高度上限等比缩放（只缩不放），返回副本，不改缓存里的原图。"""
    if img is None:
        return None
    size = img.size()
    w, h = float(size.width), float(size.height)
    if h <= 0 or w <= 0:
        return img
    scale = min(1.0, max_h / h)
    out = img.copy()
    out.setSize_(NSSize(w * scale, h * scale))
    return out


def system_glyph_for_item(item):
    """系统图标（MenuBarAgent/控制中心宿主）按标签匹配 SF 符号；对不上返回 None。"""
    label = (item.label or "").lower()
    for keywords, symbol in SYSTEM_GLYPHS:
        if any(k.lower() in label for k in keywords):
            img = _symbol_image(symbol)
            if img is not None:
                return _fit_height(img, GLYPH_MAX_H)
    return None


def _controlcenter_icon_image():
    """控制中心 App 图标（Thaw ControlCenterIcon：宿主进程没有自己的字形时用它）。"""
    global _controlcenter_icon
    if _controlcenter_icon is None:
        apps = NSWorkspace.sharedWorkspace().runningApplications()
        host = next((a for a in apps
                     if (a.bundleIdentifier() or "") == "com.apple.controlcenter"), None)
        _controlcenter_icon = host.icon() if host is not None else False
    if _controlcenter_icon is False:
        return None
    return _fit_height(_controlcenter_icon, APP_ICON_MAX_H)


def app_icon_for_item(item):
    """归属 App 的图标：先按 pid（进程还活着），再按 bundle id 查安装位置。"""
    pid = int(getattr(item, "owner_pid", -1) or -1)
    if pid > 0:
        if pid not in _app_icon_by_pid:
            host = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            _app_icon_by_pid[pid] = host.icon() if host is not None else None
        icon = _app_icon_by_pid[pid]
        if icon is not None:
            return _fit_height(icon, APP_ICON_MAX_H)
    bid = item.owner_bundle_id or ""
    if bid and bid not in _app_icon_by_bundle:
        ws = NSWorkspace.sharedWorkspace()
        url = ws.URLForApplicationWithBundleIdentifier_(bid)
        _app_icon_by_bundle[bid] = ws.iconForFile_(url.path()) if url is not None else None
        if _app_icon_by_bundle[bid] is not None:
            # iconForFile: 给的是 512pt 大图，缓存原始尺寸副本按需缩放
            _app_icon_by_bundle[bid] = _app_icon_by_bundle[bid].copy()
    icon = _app_icon_by_bundle.get(bid)
    if icon is not None:
        return _fit_height(icon, APP_ICON_MAX_H)
    return None


def fallback_image_for_item(item):
    """截取失败/无权限时的替代图标：系统符号 → 控制中心 → App 图标 → 通用占位。

    永远返回一个 NSImage（占位符号一定存在），UI 因此不再需要显示名字。
    """
    if item.owner_bundle_id == "com.apple.controlcenter":
        img = _controlcenter_icon_image()
        if img is not None:
            return img
    img = system_glyph_for_item(item)
    if img is not None:
        return img
    img = app_icon_for_item(item)
    if img is not None:
        return img
    if item.owner_bundle_id == "com.apple.MenuBarAgent":
        img = _controlcenter_icon_image()
        if img is not None:
            return img
    return _fit_height(_symbol_image(GENERIC_SYMBOL), GLYPH_MAX_H)


def forget_icon_cache():
    """进程退出/App 重启后清缓存（Thaw forgetIcon(forPID:) 同法，防缓存无限增长）。"""
    _app_icon_by_pid.clear()
    _app_icon_by_bundle.clear()


def has_screen_permission():
    """是否已有「屏幕录制」权限（不弹窗，仅查询）。"""
    preflight = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
    if preflight is None:  # 极老系统没有该 API，交给截图结果判断
        return True
    return bool(preflight())


def request_screen_permission():
    """触发系统「屏幕录制」授权弹窗。授权后通常需重启进程才生效（T16 同类）。"""
    request = getattr(Quartz, "CGRequestScreenCaptureAccess", None)
    if request is None:
        return False
    return bool(request())


# ---------- 纯像素处理（可单测，不依赖权限与 GUI） ----------

def numpy_from_cgimage(cgimg):
    """CGImage → (H, W, 4) uint8（premultiplied RGBA，内存序与位图上下文一致）。"""
    import numpy as np

    w, h = Quartz.CGImageGetWidth(cgimg), Quartz.CGImageGetHeight(cgimg)
    if w <= 0 or h <= 0:
        return None
    bpr = w * 4
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, bpr, cs,
                                       Quartz.kCGImageAlphaPremultipliedLast)
    if ctx is None:
        return None
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, w, h), cgimg)
    buf = Quartz.CGBitmapContextGetData(ctx).as_buffer(bpr * h)
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, bpr)[:, : w * 4].reshape(h, w, 4)
    return arr.copy()  # 复制出来，脱离上下文生命周期


def cgimage_from_numpy(arr):
    """(H, W, 4) uint8 → CGImage（带 alpha）。"""
    import numpy as np

    h, w = arr.shape[0], arr.shape[1]
    bpr = w * 4
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, bpr, cs,
                                       Quartz.kCGImageAlphaPremultipliedLast)
    if ctx is None:
        return None
    buf = Quartz.CGBitmapContextGetData(ctx).as_buffer(bpr * h)
    view = np.frombuffer(buf, dtype=np.uint8, count=bpr * h).reshape(h, bpr)
    view[:, : w * 4] = np.ascontiguousarray(arr).reshape(h, bpr)
    return Quartz.CGBitmapContextCreateImage(ctx)


def background_color(arr):
    """取边缘环（上下左右各 2 像素）的中位色作为背景色；空数组返回 None。"""
    import numpy as np

    if arr is None or arr.shape[0] < 5 or arr.shape[1] < 5:
        return None
    ring = np.concatenate([
        arr[0:2].reshape(-1, 4), arr[-2:].reshape(-1, 4),
        arr[:, 0:2].reshape(-1, 4), arr[:, -2:].reshape(-1, 4)])
    return np.median(ring[:, :3].astype(np.float32), axis=0)


def knockout(arr, max_distance=MAX_COLOR_DISTANCE):
    """把与背景色足够接近的像素置为透明（色键去背）。返回新数组。"""
    import numpy as np

    bg = background_color(arr)
    if bg is None:
        return arr.copy() if arr is not None else None
    dist = np.abs(arr[:, :, :3].astype(np.float32) - bg).sum(axis=2)
    out = arr.copy()
    out[dist < max_distance, 3] = 0
    return out


def trim_transparent(arr, pad=TRIM_PAD):
    """裁掉四周全透明的边距，留下 pad 像素。无可见像素时原样返回。"""
    import numpy as np

    alpha = arr[:, :, 3]
    rows = np.where((alpha > 0).any(axis=1))[0]
    cols = np.where((alpha > 0).any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return arr
    h, w = arr.shape[0], arr.shape[1]
    y0 = max(0, int(rows[0]) - pad)
    y1 = min(h - 1, int(rows[-1]) + pad)
    x0 = max(0, int(cols[0]) - pad)
    x1 = min(w - 1, int(cols[-1]) + pad)
    return arr[y0 : y1 + 1, x0 : x1 + 1]


def touches_side_edge(arr):
    """抠像后的墨迹是否贴到裁剪窗口的左/右沿：贴沿 = 这个窗口没装下整个图标。

    Phase 9 起 image_for_item 不再靠它直接拒收（它改成「撑宽窗口重试」的信号），
    留下它供单测与诊断使用；判据本身仍成立：AX frame 宽常小于真实绘制宽
    （时钟 frame 36pt、实际画「22:31」约 70pt），贴沿就是还能被裁出半截。
    """
    import numpy as np

    alpha = arr[:, :, 3]
    if alpha.size == 0:
        return True
    cols = (alpha > 0).any(axis=0)
    return bool(cols[0] or cols[-1])


def ink_run(arr, lo, hi, gap):
    """在抠好像的数组里找出与列区间 [lo,hi) 相交的字形段，返回 (起列, 止列开区间)。

    菜单栏图标之间总有几列空白，字形内部空隙（数字之间、冒号两侧）又小得多，
    于是「空隙 ≤ gap 列就算同一段」把墨迹拼成段。没相交时返回 None（不猜隔壁），
    让调用方走兜底，而不是把邻居的图标当成自己的（Phase 9：半截图标根治点）。
    """
    import numpy as np

    if arr is None or arr.size == 0:
        return None
    ink = (arr[:, :, 3] > 0).any(axis=0)
    idx = np.where(ink)[0]
    if idx.size == 0:
        return None
    runs, start, prev = [], int(idx[0]), int(idx[0])
    for col in (int(c) for c in idx[1:]):
        if col - prev > gap:
            runs.append((start, prev + 1))
            start = col
        prev = col
    runs.append((start, prev + 1))
    hit = [(a, b) for (a, b) in runs if b > lo and a < hi]
    if not hit:
        return None
    return (min(a for a, _ in hit), max(b for _, b in hit))


def is_single_ink(arr):
    """是否为「单色字形」图标（菜单栏绝大多数是），成立则适合标 template 着色。
    判据同 Thaw：可见像素里高饱和色占比 ≤ MAX_VIVID_SHARE，且不是一整块不透明贴图。
    """
    import numpy as np

    alpha = arr[:, :, 3].astype(np.float32) / 255.0
    visible = alpha >= 0.5
    n_visible = int(visible.sum())
    if n_visible == 0:
        return False
    if float((alpha > 0.98).mean()) >= 0.9:  # 整块不透明 = 背景没抠掉，判否
        return False
    rgb = arr[:, :, :3].astype(np.float32)
    a = np.where(alpha > 0, alpha, 1.0)[:, :, None]
    rgb = np.clip(rgb / a, 0, 1)  # 解除预乘再比色度
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    vivid = int(((chroma > VIVID_CHROMA) & visible).sum())
    return (vivid / n_visible) <= MAX_VIVID_SHARE


def image_from_array(arr, scale, template):
    """numpy → NSImage（点尺寸按 scale 还原，避免 Retina 下图过大）。"""
    cg = cgimage_from_numpy(arr)
    if cg is None:
        return None
    h, w = arr.shape[0], arr.shape[1]
    img = NSImage.alloc().initWithCGImage_size_(
        cg, NSSize(w / max(scale, 1.0), h / max(scale, 1.0)))
    if img is None:
        return None
    img.setTemplate_(bool(template))
    return img


# ---------- 面向盘点的抓取入口 ----------

def menu_bar_height():
    """菜单栏实际逻辑高度（点）：拿带菜单栏那块屏的 frame 高减 visibleFrame 高。

    非刘海屏 24~25pt，刘海屏 32~39pt。早先到处写死 24 这个常量，刘海屏上
    两行文字的图标（网速那类）下半行就被这个常量裁掉了 —— Phase 9 目视取证
    抓到的「显示一半图标」真根因（不是格子裁的，是抓取阶段就没截到）。
    """
    try:
        screens = NSScreen.screens()
        # 全局原点 (0,0) 所在的那块屏就是带菜单栏的屏；找不到就用第一块（AppKit 约定）
        screen = next((s for s in screens
                       if s.frame().origin.x == 0.0 and s.frame().origin.y == 0.0),
                      screens[0] if len(screens) else None)
        if screen is not None:
            f, vf = screen.frame(), screen.visibleFrame()
            h = float(f.size.height) - float(vf.origin.y) - float(vf.size.height)
            if 20.0 <= h <= 64.0:
                return h
    except Exception:
        pass
    return MENU_BAR_HEIGHT


def capture_strip():
    """截整条菜单栏顶部条带。返回 (CGImage, scale)，无权限/失败返回 (None, 1.0)。"""
    bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    full = Quartz.CGWindowListCreateImage(
        bounds, Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID,
        Quartz.kCGWindowImageDefault)
    if full is None:
        return None, 1.0
    px_w = Quartz.CGImageGetWidth(full)
    scale = px_w / bounds.size.width if bounds.size.width else 1.0
    strip = Quartz.CGImageCreateWithImageInRect(
        full, Quartz.CGRectMake(0, 0, px_w, int(menu_bar_height() * scale)))
    return strip, scale


def fit_box(img, max_w=GLYPH_MAX_W, max_h=GLYPH_MAX_H):
    """把 NSImage 的点尺寸限进 max_w×max_h（只缩不放）。

    只改 size 不改位图分辨率：Retina 下裁图像素是点尺寸的 2 倍，缩小点尺寸反而更清。
    必须在抓取端做：无边框 NSButton 不执行 imageScaling，宽图标（网速/温度这类
    文字条，裁出来 80–104pt 宽）会直接溢出格子压到邻居（P42/t72 像素定位实测）。
    """
    if img is None:
        return None
    s = img.size()
    k = min(1.0, max_w / max(s.width, 1.0), max_h / max(s.height, 1.0))
    if k < 1.0:
        img.setSize_(NSSize(s.width * k, s.height * k))
    return img


def scaled_copy(img, max_w, max_h):
    """同一张图的同比例缩小副本（收进 max_w×max_h，只缩不放，小图直接回原件）。

    显示端专用：抓取缓存里那张图尺寸是共享的，谁也不能为了自己格子去改它的
    size_（一改就把面板、布局条、缓存里的图全改了），所以拿副本再缩。
    副本只新建 NSImage 外壳、位图表示与原件共用，不费内存也不走 CPU 重绘。
    """
    if img is None:
        return None
    s = img.size()
    k = min(1.0, max_w / max(s.width, 1.0), max_h / max(s.height, 1.0))
    if k >= 1.0:
        return img
    dup = NSImage.alloc().initWithSize_(NSSize(s.width * k, s.height * k))
    if dup is None:
        return img
    dup.addRepresentations_(list(img.representations()))
    dup.setTemplate_(bool(img.isTemplate()))
    return dup


def _crop_strip(strip, scale, x, w, top, bottom):
    """从条带裁一块（点坐标 → 像素）；拿不到像素返回 None。"""
    px_w = Quartz.CGImageGetWidth(strip) / scale
    x0 = max(0.0, float(x))
    x1 = min(px_w, float(x) + float(w))
    if x1 - x0 < 2:
        return None
    rect = Quartz.CGRectMake(int(x0 * scale), int(top * scale),
                             max(1, int((x1 - x0) * scale)),
                             max(1, int((bottom - top) * scale)))
    return numpy_from_cgimage(Quartz.CGImageCreateWithImageInRect(strip, rect))


def _crop_glyph(strip, scale, x, w, top, bottom, left, right):
    """按撑宽的窗口裁一次字形；返回 NSImage，或 None（装不下/无墨/离谱比例）。

    None 只说明「这个窗口不行」，能不能补救由调用方决定（它会换更大的窗口重试）。
    """
    wx, ww = float(x) - left, float(w) + left + right
    arr = _crop_strip(strip, scale, wx, ww, top, bottom)
    if arr is None:
        return None
    px_w = Quartz.CGImageGetWidth(strip) / max(scale, 1.0)
    arr = knockout(arr)
    # frame 在撑大的窗口里的列区间（像素），拿它去认「哪一段墨是我们的图标」
    lo = int((x - wx) * scale)
    hi = max(lo + 1, int((x + w - wx) * scale))
    run = ink_run(arr, lo, hi, max(2, int(INK_GAP_PT * scale)))
    if run is None:
        return None  # 这个 frame 里没画上图标（全黑条带/被遮）→ 兜底
    cropped_left = run[0] <= 0 and wx > 0.0
    cropped_right = run[1] >= arr.shape[1] and (wx + ww) < px_w - 1.0
    if cropped_left or cropped_right:
        return None  # 还贴沿且不是屏幕边 = 这个窗口仍装不下（换大窗口再试）
    arr = trim_transparent(arr[:, run[0]:run[1], :])
    if int((arr[:, :, 3] > 0).sum()) < MIN_GLYPH_PIXELS:
        return None  # 无墨 = 这里没画上图标，不是「图标是透明的」→ 交给兜底链
    h, w = arr.shape[:2]
    if h <= 0 or w > h * MAX_ASPECT:
        return None  # 离谱比例：多半是把整条/多个图标拼进来了，不是单个图标
    return fit_box(image_from_array(arr, scale, is_single_ink(arr)), GLYPH_MAX_W, CAPTURE_MAX_H)


def image_for_item(strip, scale, item, room=None):
    """按 item.frame 从条带裁出单个图标并处理成 NSImage；失败返回 None。

    Phase 9 重写「半截图标」两处口径（用户定调：显示一半的，就同比例缩着完整显示）：

    1. 不再只裁 AX frame：先把窗口左右各撑宽 room（点），再用 ink_run 把与 frame
       相接的那一段字形整段取回来——画到 frame 外的像素不再被切掉，邻居的图形
       隔着空白自然被剔掉；第一轮回提（邻居 frame 算出的借宽）不够就再撑到
       ROOM_MAX 重试一次，宁多裁一点也不交半截；
    2. 宽条（图标+数字/文字复合）不再一律拒收：取到的像素整体同比例收进
       fit_box，宁可小一点也不剥切。

    只有「撑到 ROOM_MAX 仍被切」与「无墨/离谱比例」才交给兜底链
    （T97：宁可换一个完整可辨识的兜底图，也不给半截）。
    """
    if strip is None or item.frame is None:
        return None
    x, y, w, h = item.frame
    if w <= 0 or h <= 0:
        return None
    # 纵向按 AX frame（刘海屏上它报 y=7.5/h=24，正是图标居中绘制的那 24pt），
    # 但收口必须按条带真实高而不是 24 常量：从 7.5 起算时 24 常量只能裁到 24pt，
    # 两行文字图标的下半行（第二行）刚好被吃掉 —— Phase 9 目视取证的真半截根因。
    # 条带最底下 1pt 是菜单栏分隔线（整行都是墨），留着会让 ink_run 把整个窗口
    # 当成一个字形，反过来判「仍被切」→ 全部退到兜底图（改第一版就踩过这个）。
    strip_h = max(0.0, Quartz.CGImageGetHeight(strip) / max(scale, 1.0) - 1.0)
    top = max(0.0, min(float(y), strip_h - 1))
    bottom = min(strip_h, float(y) + float(h))
    if bottom - top < 2:
        return None
    left, right = room if room else (ROOM_MIN, ROOM_MIN)
    windows = [(max(0.0, float(left)), max(0.0, float(right)))]
    if windows[0] < (ROOM_MAX, ROOM_MAX):
        windows.append((ROOM_MAX, ROOM_MAX))  # 借不够就撑满再试（ink_run 会切掉邻居）
    for (l, r) in windows:
        img = _crop_glyph(strip, scale, x, w, top, bottom, l, r)
        if img is not None:
            return img
    return None


def strip_has_content(strip):
    """条带里到底画没画东西：全屏 App 遮住菜单栏时系统给的是纯黑条带。

    与「有没有屏幕录制权限」是两件事：权限有、preflight 返回 True，照样可能
    截到一张全黑（菜单栏此刻不可见）。UI 要据此告诉用户「现在不是真实图标」。
    """
    import numpy as np

    arr = numpy_from_cgimage(strip) if strip is not None else None
    if arr is None:
        return False
    rgb = arr.reshape(-1, arr.shape[2])[:, :3].astype(int)
    return int(rgb.max() - rgb.min()) > 8


def neighbour_room(items, target):
    """目标图标左右各能借多少空白（点）：邻居 frame 边界以内的像素不属于邻居。

    AX 报的宽常小于真实绘制宽（时钟 frame 36pt、实际画「22:31」约 70pt），
    不借宽就永远裁成半截。只用「同样画在菜单栏上、且 frame 能用」的项算邻居；
    邻居紧贴着没间隙时也给保底借宽（frame 挨着不代表图形挨着，隔开的活由
    ink_run 干）。上限 ROOM_MAX，下限 ROOM_MIN。
    """
    tf = getattr(target, "frame", None)
    if not tf:
        return (ROOM_MIN, ROOM_MIN)
    tx, tw = float(tf[0]), float(tf[2])
    left, right = 0.0, 0.0
    for it in items:
        if it is target or getattr(it, "stashed", False):
            continue
        f = getattr(it, "frame", None)
        if not f or float(f[2]) <= 0:
            continue
        x0, x1 = float(f[0]), float(f[0]) + float(f[2])
        if x1 <= tx:
            left = max(left, min(ROOM_MAX, tx - x1))
        elif x0 >= tx + tw:
            right = max(right, min(ROOM_MAX, x0 - tx - tw))
    return (max(ROOM_MIN, left), max(ROOM_MIN, right))


def capture_icons(items, force=False):
    """批量取图标位图：截到的像素优先，截不到的用兜底图（App 图标/系统符号）。

    返回 ({item_key: NSImage}, 是否因缺屏幕录制权限而截不到像素)。
    字典一定覆盖每一个 item——UI 不再有「没图就显示名字」的分支。
    被收纳（item.stashed）的项不参与裁图：它根本不在可见条带上。

    截取结果按代际缓存：同一批图标重复调用只回读缓存，force=True 或盘点刷新
    （invalidate_cache）后重新截图。
    """
    global _generation, last_stats
    no_permission = not has_screen_permission()
    bar_drawn = last_stats["bar_drawn"]  # 本轮没重截条带时沿用上次的判断
    if no_permission:
        captures = {}
    else:
        if force:
            _cache.clear()
        captures = {}
        missing = []
        for it in items:
            # 被系统收纳的图标没画在菜单栏可见段上（槽位挤在收纳按钮口），
            # 按它的 frame 裁只会裁到邻居的像素，直接走兜底图标（T55）
            if getattr(it, "stashed", False):
                continue
            cached = _cache.get((sections.item_key(it), _generation))
            if cached is not None:
                captures[sections.item_key(it)] = cached
            else:
                missing.append(it)
        if missing:
            strip, scale = capture_strip()
            if strip is None:
                no_permission = True
                missing = []
            else:
                bar_drawn = strip_has_content(strip)
            for it in missing:
                img = (image_for_item(strip, scale, it, neighbour_room(items, it))
                       if strip is not None else None)
                if img is not None:
                    _cache[(sections.item_key(it), _generation)] = img
                    captures[sections.item_key(it)] = img
    out = {}
    for it in items:
        key = sections.item_key(it)
        out[key] = captures.get(key) or fallback_image_for_item(it)
    # 取图构成只供 UI 说明「现在是真实像素还是兜底图标」，不参与任何决策
    last_stats = {
        "cropped": len(captures),
        "fallback": len(items) - len(captures),
        "permission": not no_permission,
        "bar_drawn": bar_drawn,
    }
    return out, no_permission


def invalidate_cache():
    """图标位置/内容变化后使缓存失效（面板刷新、设置窗口重抓时调用）。"""
    global _generation
    _cache.clear()
    _generation += 1
