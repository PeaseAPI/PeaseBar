#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""菜单栏图标位图抓取（F3 只显示图标 / 设置窗口图标化的基础）。

业务参照 Thaw（tmp/Thaw-app）：它同样**截菜单栏条带再按 AX frame 裁剪**
（DisplayStripCaptureSession + AXBoundsCropper），因为 macOS 27 上单个状态项
窗口不暴露给 CGWindowList（取证：25 项全部匹配不到窗口）。Thaw 的完整管线
还有磁盘缓存、重捕获调度、污染判定，我们 v1 只做必要四步：

    截条带 → 按 frame 裁剪（裁进条带高度）→ 抠掉近似统一的背景 → 裁掉透明边距
    → 单色字形判定，成立则标记 template（跟随界面明暗着色）

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
    NSWorkspace,
)
from Foundation import NSSize

from peasebar import sections

# 菜单栏逻辑高度（27 上仍为 24pt）；AX frame 常报 h=24 且 y=7.5，超出条带
MENU_BAR_HEIGHT = 24.0

# 抠像阈值：与 Thaw separatedFromNearUniformBackground(maxColorDistance: 36) 一致
MAX_COLOR_DISTANCE = 36.0
# 单色字形判定阈值：与 Thaw isSingleInkGlyph(vividChroma: 0.3, maximumVividShare: 0.02) 一致
VIVID_CHROMA = 0.3
MAX_VIVID_SHARE = 0.02
# 裁边后保留的留白（点，按 scale 换算成像素）
TRIM_PAD = 2

# 抓取结果缓存：{item_key: (NSImage, 代际)}；盘点刷新时代际递增使旧缓存失效
_cache = {}
_generation = 0

# ---------- 图标兜底（参照 Thaw OverflowFallbackIcon：永远给图，不给字） ----------

# App 图标绘制上限（Thaw MenuBarItemDisplayImage.appIconHeight = 18pt）
APP_ICON_MAX_H = 18.0
# 系统模块符号的绘制上限（比 App 图标略高，贴近菜单栏字形）
GLYPH_MAX_H = 18.0
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
        full, Quartz.CGRectMake(0, 0, px_w, int(MENU_BAR_HEIGHT * scale)))
    return strip, scale


def image_for_item(strip, scale, item):
    """按 item.frame 从条带裁出单个图标并处理成 NSImage；失败返回 None。"""
    if strip is None or item.frame is None:
        return None
    x, y, w, h = item.frame
    if w <= 0 or h <= 0:
        return None
    # 只裁条带范围内的像素（AX 的 y/h 常超出菜单栏实际高度）
    top = max(0.0, min(float(y), MENU_BAR_HEIGHT - 1))
    bottom = min(MENU_BAR_HEIGHT, float(y) + float(h))
    if bottom - top < 2:
        return None
    rect = Quartz.CGRectMake(int(x * scale), int(top * scale),
                             max(1, int(w * scale)), max(1, int((bottom - top) * scale)))
    cg = Quartz.CGImageCreateWithImageInRect(strip, rect)
    arr = numpy_from_cgimage(cg)
    if arr is None:
        return None
    arr = trim_transparent(knockout(arr))
    return image_from_array(arr, scale, is_single_ink(arr))


def capture_icons(items, force=False):
    """批量取图标位图：截到的像素优先，截不到的用兜底图（App 图标/系统符号）。

    返回 ({item_key: NSImage}, 是否因缺屏幕录制权限而截不到像素)。
    字典一定覆盖每一个 item——UI 不再有「没图就显示名字」的分支。
    被收纳（item.stashed）的项不参与裁图：它根本不在可见条带上。

    截取结果按代际缓存：同一批图标重复调用只回读缓存，force=True 或盘点刷新
    （invalidate_cache）后重新截图。
    """
    global _generation
    no_permission = not has_screen_permission()
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
            for it in missing:
                img = image_for_item(strip, scale, it) if strip is not None else None
                if img is not None:
                    _cache[(sections.item_key(it), _generation)] = img
                    captures[sections.item_key(it)] = img
    out = {}
    for it in items:
        key = sections.item_key(it)
        out[key] = captures.get(key) or fallback_image_for_item(it)
    return out, no_permission


def invalidate_cache():
    """图标位置/内容变化后使缓存失效（面板刷新、设置窗口重抓时调用）。"""
    global _generation
    _cache.clear()
    _generation += 1
