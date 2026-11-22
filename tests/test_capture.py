#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""capture 模块纯像素函数的单测（合成数组，不需要屏幕录制权限）。"""
import unittest

import numpy as np

from peasebar import capture


def tile(bg=(100, 120, 140), size=(24, 48)):
    """造一块「统一背景」的图（不透明）。"""
    arr = np.zeros((size[0], size[1], 4), dtype=np.uint8)
    arr[:, :, 0] = bg[0]
    arr[:, :, 1] = bg[1]
    arr[:, :, 2] = bg[2]
    arr[:, :, 3] = 255
    return arr


def draw_glyph(arr, color=(240, 240, 240)):
    """在中央画一块矩形当作图标字形。"""
    h, w = arr.shape[0], arr.shape[1]
    arr[h // 3 : h // 3 * 2, w // 3 : w // 3 * 2, :3] = color
    return arr


class TestBackground(unittest.TestCase):
    def test_边缘环中位色(self):
        arr = draw_glyph(tile())
        bg = capture.background_color(arr)
        self.assertTrue(np.allclose(bg, [100, 120, 140], atol=1))

    def test_太小返回None(self):
        self.assertIsNone(capture.background_color(np.zeros((4, 4, 4), np.uint8)))
        self.assertIsNone(capture.background_color(None))


class TestKnockout(unittest.TestCase):
    def test_背景置透明_字形保留(self):
        arr = capture.knockout(draw_glyph(tile()))
        # 角落（纯背景）应变透明
        self.assertEqual(arr[0, 0, 3], 0)
        # 中央字形仍不透明
        h, w = arr.shape[0], arr.shape[1]
        self.assertEqual(arr[h // 2, w // 2, 3], 255)

    def test_字形颜色不被破坏(self):
        arr = capture.knockout(draw_glyph(tile()))
        h, w = arr.shape[0], arr.shape[1]
        self.assertEqual(tuple(arr[h // 2, w // 2, :3]), (240, 240, 240))

    def test_阈值内弱差异也算背景(self):
        base = tile(bg=(100, 120, 140))
        base[10, 10] = [105, 122, 138, 255]  # 与背景很近的杂点
        out = capture.knockout(base)
        self.assertEqual(out[10, 10, 3], 0)

    def test_空输入不崩(self):
        self.assertIsNone(capture.knockout(None))


class TestTrim(unittest.TestCase):
    def test_裁掉透明边距(self):
        arr = capture.knockout(draw_glyph(tile()))
        out = capture.trim_transparent(arr, pad=0)
        self.assertEqual(out.shape[0], arr.shape[0] // 3)
        self.assertEqual(out.shape[1], arr.shape[1] // 3)

    def test_全透明原样返回(self):
        arr = np.zeros((10, 10, 4), dtype=np.uint8)
        self.assertEqual(capture.trim_transparent(arr).shape, arr.shape)

    def test_留白按pad扩展(self):
        arr = capture.knockout(draw_glyph(tile()))
        p0 = capture.trim_transparent(arr, pad=0)
        p3 = capture.trim_transparent(arr, pad=3)
        self.assertGreater(p3.shape[0], p0.shape[0])


class TestSingleInk(unittest.TestCase):
    def test_浅色字形是单色(self):
        arr = capture.knockout(draw_glyph(tile()))
        self.assertTrue(capture.is_single_ink(arr))

    def test_彩色图标不是单色(self):
        arr = np.zeros((24, 24, 4), dtype=np.uint8)
        arr[:, :, 0] = 255  # 纯红满幅高饱和
        arr[:, :, 3] = 255
        arr[:8] = 0  # 抠出透明边（否则命中「整块不透明」短路，测不到色度分支）
        arr[-8:] = 0
        self.assertFalse(capture.is_single_ink(arr))

    def test_整块不透明判否(self):
        arr = tile()  # 背景没抠掉的实色贴图
        self.assertFalse(capture.is_single_ink(arr))

    def test_全透明判否(self):
        arr = np.zeros((10, 10, 4), dtype=np.uint8)
        self.assertFalse(capture.is_single_ink(arr))


class TestImageRoundTrip(unittest.TestCase):
    def test_数组转NSImage尺寸按scale还原(self):
        arr = capture.knockout(draw_glyph(tile()))
        img = capture.image_from_array(arr, scale=2.0, template=True)
        self.assertIsNotNone(img)
        size = img.size()
        self.assertAlmostEqual(size.width, arr.shape[1] / 2.0, places=2)
        self.assertAlmostEqual(size.height, arr.shape[0] / 2.0, places=2)
        self.assertTrue(img.isTemplate())

    def test_cgimage往返保形(self):
        arr = draw_glyph(tile())
        cg = capture.cgimage_from_numpy(arr)
        self.assertIsNotNone(cg)
        back = capture.numpy_from_cgimage(cg)
        self.assertEqual(back.shape, arr.shape)


class TestFitBox(unittest.TestCase):
    """宽图标尺寸收口（无边框按钮不执行 imageScaling，溢出只能在这里拦，P42）。"""

    def _img(self, w, h):
        from Foundation import NSSize
        from AppKit import NSImage
        img = NSImage.alloc().initWithSize_(NSSize(w, h))
        return img

    def test宽文字条缩进框内(self):
        img = capture.fit_box(self._img(104, 15))
        s = img.size()
        self.assertLessEqual(s.width, capture.GLYPH_MAX_W + 0.01)
        self.assertLessEqual(s.height, capture.GLYPH_MAX_H + 0.01)
        self.assertAlmostEqual(s.height / s.width, 15 / 104, places=3)  # 保比例

    def test小图不放大(self):
        img = capture.fit_box(self._img(18, 14))
        s = img.size()
        self.assertAlmostEqual(s.width, 18.0, places=2)
        self.assertAlmostEqual(s.height, 14.0, places=2)

    def test无图返回None(self):
        self.assertIsNone(capture.fit_box(None))


class TestPermissionApi(unittest.TestCase):
    def test_预检返回布尔(self):
        self.assertIn(capture.has_screen_permission(), (True, False))


class TestDeadMenuBar(unittest.TestCase):
    """菜单栏此刻没画出图标（被全屏 App 遮住）：绝不给空白格子（T76，P42 实测 16 格空白）。

    那种场景下整条条带都是黑的，按 frame 裁到的是纯背景：抠像后一个像素不剩。
    旧实现把这张全透明图当成「截到了」交给按钮 → 格子什么也不画。
    """

    class Item:
        def __init__(self, frame, label="测试项", bundle="com.example.dead"):
            self.frame = frame
            self.label = label
            self.owner_bundle_id = bundle
            self.stashed = False

    def _strip(self, arr):
        return capture.cgimage_from_numpy(arr)

    def test_纯背景裁图返回None(self):
        strip = self._strip(tile(bg=(0, 0, 0), size=(24, 200)))
        self.assertIsNone(capture.image_for_item(strip, 1.0, self.Item((10, 0, 24, 24))))

    def test_有字形仍能裁到图(self):
        # 画一个近似方形的小图标（纯图标路径，宽条/贴边条会被 T97 拒收）
        arr = tile(bg=(0, 0, 0), size=(24, 200))
        arr[6:18, 100:112, :3] = 240
        arr[6:18, 100:112, 3] = 255
        self.assertIsNotNone(capture.image_for_item(self._strip(arr), 1.0,
                                                    self.Item((96, 0, 20, 24))))

    def test_条带有无内容(self):
        self.assertFalse(capture.strip_has_content(self._strip(tile(bg=(0, 0, 0), size=(24, 200)))))
        self.assertTrue(capture.strip_has_content(self._strip(draw_glyph(tile(size=(24, 200))))))
        self.assertFalse(capture.strip_has_content(None))

    def test_全黑条带下全部走兜底(self):
        """有权限但条带全黑 → 每张图都必须是兜底图，且统计报出「零张真像素」。"""
        strip = self._strip(tile(bg=(0, 0, 0), size=(24, 400)))
        orig_strip, orig_perm = capture.capture_strip, capture.has_screen_permission
        orig_stats = dict(capture.last_stats)
        capture.capture_strip = lambda: (strip, 1.0)
        capture.has_screen_permission = lambda: True
        items = [self.Item((10, 0, 24, 24), label="甲"), self.Item((60, 0, 24, 24), label="乙")]
        try:
            images, no_perm = capture.capture_icons(items, force=True)
            stats = dict(capture.last_stats)
        finally:
            capture.capture_strip, capture.has_screen_permission = orig_strip, orig_perm
            capture.last_stats = orig_stats  # 模块状态不留到下一个用例
        self.assertFalse(no_perm)  # 权限确实有，问题不在权限
        self.assertEqual(stats["cropped"], 0)
        self.assertEqual(stats["fallback"], 2)
        self.assertFalse(stats["bar_drawn"])
        for it in items:
            key = capture.sections.item_key(it)
            got = bytes(images[key].TIFFRepresentation())
            want = bytes(capture.fallback_image_for_item(it).TIFFRepresentation())
            self.assertEqual(got, want)  # 兜底图就是应得的那张，不是一张全透明


class TestSideEdge(unittest.TestCase):
    """贴边判定（T97 半截图标第二类根因）：AX frame 窄于真实绘制宽时，
    裁窗口右沿一定吃到墨迹。Phase 9 起这个信号不再意味着拒收，而是
    「窗口太小、撑宽重试」（image_for_item 里接的 ink_run 会切掉邻居）。"""

    @staticmethod
    def _mask(h, w, spans):
        """按 (列起, 列止, 行起, 止) 列表造 alpha 图（判定只看通道 3）。"""
        arr = np.zeros((h, w, 4), dtype=np.uint8)
        for c0, c1, r0, r1 in spans:
            arr[r0:r1, c0:c1, 3] = 255
        return arr

    def test_居中墨迹不贴边(self):
        self.assertFalse(capture.touches_side_edge(self._mask(20, 40, [(10, 30, 4, 16)])))

    def test_贴左沿判贴边(self):
        self.assertTrue(capture.touches_side_edge(self._mask(20, 40, [(0, 18, 4, 16)])))

    def test_贴右沿判贴边(self):
        # 时钟类：frame 36pt 实画「22:31」约 70pt，墨迹一定顶到裁剪窗口右沿
        self.assertTrue(capture.touches_side_edge(self._mask(20, 40, [(5, 40, 4, 16)])))

    def test_空图判贴边(self):
        # 零宽/零高的退化数组没法当图标，判 True 让调用方走兜底
        self.assertTrue(capture.touches_side_edge(np.zeros((0, 0, 4), dtype=np.uint8)))


class TestInkRun(unittest.TestCase):
    """字形分段（Phase 9 半截图标的根治）：与 frame 相接的那一段整段拿回来，
    隔着空白的邻居自然被剔掉。"""

    @staticmethod
    def _mask(h, w, spans):
        arr = np.zeros((h, w, 4), dtype=np.uint8)
        for c0, c1, r0, r1 in spans:
            arr[r0:r1, c0:c1, 3] = 255
        return arr

    def test_把frame外的自家像素一并拿回(self):
        # frame 只占 10..20 列，墨迹从 4 一路画到 30（典型：时钟 frame 窄于实画）
        arr = self._mask(20, 60, [(4, 30, 4, 16)])
        self.assertEqual(capture.ink_run(arr, 10, 20, 4), (4, 30))

    def test_隔得远的邻居不算同一段(self):
        # 两段墨之间空 18 列（> gap 4）：只取与 frame 相接的那段
        arr = self._mask(20, 80, [(4, 20, 4, 16), (38, 60, 4, 16)])
        self.assertEqual(capture.ink_run(arr, 10, 16, 4), (4, 20))

    def test_数字之间的小空隙算同一段(self):
        # 「22:31」这类：字符间隙 2 列 ≤ gap 4，应该是一整段
        arr = self._mask(20, 40, [(4, 8, 4, 16), (10, 14, 4, 16), (16, 20, 4, 16)])
        self.assertEqual(capture.ink_run(arr, 4, 20, 4), (4, 20))

    def test_无墨与不相交返回None(self):
        blank = np.zeros((20, 40, 4), dtype=np.uint8)
        self.assertIsNone(capture.ink_run(blank, 10, 20, 4))
        arr = self._mask(20, 40, [(30, 36, 4, 16)])
        self.assertIsNone(capture.ink_run(arr, 4, 12, 4))  # frame 里没墨，不猜隔壁


class TestWideGlyph(unittest.TestCase):
    """宽条与超出 frame 的字形（Phase 9 口径）：撑宽窗口 + 整段取回，完整收下、
    同比例缩小，绝不交半截；只有真装不下/离谱比例才走兜底。

    旧版在这里把宽条一律拒收（换成 App 图标），用户看到的是「我的图标怎么不对」；
    Thaw 的做法是整体同比例缩着画（MenuBarItemImage.drawnSize），现在照这个口径。"""

    class Item:
        def __init__(self, frame, label="测试项", bundle="com.example.wide"):
            self.frame = frame
            self.label = label
            self.owner_bundle_id = bundle
            self.stashed = False

    def _strip(self, arr):
        return capture.cgimage_from_numpy(arr)

    def test_图标加数字宽条完整收下(self):
        # 黑底条带上画 12pt 高 × 41pt 宽的「图标+数字」复合横条（frame 50pt 装得下）
        arr = tile(bg=(0, 0, 0), size=(24, 400))
        arr[6:18, 100:141, :3] = 240
        arr[6:18, 100:141, 3] = 255
        img = capture.image_for_item(self._strip(arr), 1.0, self.Item((96, 0, 50, 24)))
        self.assertIsNotNone(img)          # 不再拒收
        s = img.size()
        self.assertGreater(s.width, 35.0)  # 41pt 宽的横条完整保留（+裁边留白）
        self.assertGreater(s.height, 10.0)
        self.assertAlmostEqual(s.width / s.height, 41 / 12, delta=1.0)  # 比例不变

    def test_墨迹超出frame时借宽后完整收下(self):
        # 时钟类：frame 只有 20pt 宽，墨迹从 100 一路画过 116 顶出 frame 与裁窗口
        arr = tile(bg=(0, 0, 0), size=(24, 400))
        arr[6:18, 100:130, :3] = 240
        arr[6:18, 100:130, 3] = 255
        img = capture.image_for_item(self._strip(arr), 1.0, self.Item((96, 0, 20, 24)))
        self.assertIsNotNone(img)
        s = img.size()
        self.assertGreater(s.width, 28.0)  # 拿到完整 30pt 墨迹，而不是被切的 20pt
        self.assertLessEqual(s.width, capture.GLYPH_MAX_W)

    def test_邻居字形不被偷进来(self):
        # 我们的图标 100..112，18pt 外另一个图标 130..150：撑宽窗口也不能把邻居带进来
        arr = tile(bg=(0, 0, 0), size=(24, 400))
        arr[6:18, 100:112, :3] = 240
        arr[6:18, 100:112, 3] = 255
        arr[6:18, 130:150, :3] = 240
        arr[6:18, 130:150, 3] = 255
        img = capture.image_for_item(self._strip(arr), 1.0, self.Item((100, 0, 12, 24)))
        self.assertIsNotNone(img)
        self.assertLess(img.size().width, 30.0)  # 只算上自己的 12pt（+裁边留白）

    def test_离谱比例整条误裁仍拒收(self):
        # 240pt 宽×12pt 高：比例超过 MAX_ASPECT，宁可兜底也不能把整条当一个图标
        arr = tile(bg=(0, 0, 0), size=(24, 400))
        arr[6:18, 100:340, :3] = 240
        arr[6:18, 100:340, 3] = 255
        self.assertIsNone(capture.image_for_item(self._strip(arr), 1.0,
                                                self.Item((96, 0, 250, 24))))

    def test_近方形纯图标仍收下(self):
        # 新口径只修「宽条/贴边条被错杀」，正常纯图标当然还得裁得出来（剪刀/微信这类）
        arr = tile(bg=(0, 0, 0), size=(24, 400))
        arr[5:19, 100:114, :3] = 240
        arr[5:19, 100:114, 3] = 255
        self.assertIsNotNone(capture.image_for_item(self._strip(arr), 1.0,
                                                   self.Item((96, 0, 20, 24))))

    def test_刘海屏两行图标下半行不被裁(self):
        # 刘海屏条带高 39pt，图标居中画在 7.5~31.5（AX frame 就这么报），网速那类
        # 两行文字的下半行落在 24pt 以下；旧口径把 bottom 收口到 24 常量，
        # 第二行就在抓取阶段被切掉（Phase 9 目视取证抓到的真半截）。
        arr = tile(bg=(0, 0, 0), size=(39, 400))
        arr[12:31, 100:160, :3] = 240
        arr[12:31, 100:160, 3] = 255
        img = capture.image_for_item(self._strip(arr), 1.0, self.Item((96, 7.5, 70, 24)))
        self.assertIsNotNone(img)
        s = img.size()
        # 墨迹本身 19pt 高（12~30）：旧口径裁到 24pt 只剩 12pt，加裁边留白也不到 15
        self.assertGreaterEqual(s.height, 19.0)
        # 同比例：宽 60pt 墨全部拿到，宽高比停在墨迹比例附近（只收裁边留白的浮动）
        self.assertGreater(s.width, 55.0)
        self.assertTrue(2.4 <= s.width / s.height <= 3.4, f"比例走形：{s.width}x{s.height}")

    def test_菜单栏分隔线不算字形(self):
        # 条带最底一行是菜单栏分隔线（整行都是墨）。一旦把它当字形，ink_run 会
        # 把整个窗口认成一个字形 → 反过来判「仍被切」→ 所有图标全退到兜底图。
        arr = tile(bg=(100, 120, 140), size=(39, 400))
        arr[38:39, :, :3] = 20
        arr[38:39, :, 3] = 255
        arr[12:26, 100:114, :3] = 240
        arr[12:26, 100:114, 3] = 255
        img = capture.image_for_item(self._strip(arr), 1.0, self.Item((96, 7.5, 24, 24)))
        self.assertIsNotNone(img)
        self.assertLess(img.size().width, 30.0)  # 只算自己的 14pt 图标，不是整窗


class TestScaledCopy(unittest.TestCase):
    """显示端同比例缩放副本：不能去改抓取缓存里那张图的 size（一改全跟着变）。"""

    def _img(self, w, h, template=False):
        from AppKit import NSImage
        from Foundation import NSSize
        img = NSImage.alloc().initWithSize_(NSSize(w, h))
        img.setTemplate_(template)
        return img

    def test_缩副本不动原件(self):
        src = self._img(100, 18, template=True)
        got = capture.scaled_copy(src, 40, 18)
        self.assertAlmostEqual(src.size().width, 100.0, places=2)  # 原件不动
        s = got.size()
        self.assertLessEqual(s.width, 40.01)
        self.assertAlmostEqual(s.height / s.width, 18 / 100, places=3)  # 同比例
        self.assertTrue(got.isTemplate())  # 着色属性跟着副本走

    def test_够小就不复制(self):
        src = self._img(20, 14)
        self.assertIs(capture.scaled_copy(src, 40, 18), src)

    def test_无图返回None(self):
        self.assertIsNone(capture.scaled_copy(None, 40, 18))


class TestMenuBarHeight(unittest.TestCase):
    """菜单栏真实高：刘海屏 32~39pt，非刘海 24~25pt，写死 24 会吃掉两行图标的下半行。"""

    def test_落在合理区间(self):
        h = capture.menu_bar_height()
        self.assertGreaterEqual(h, 20.0)
        self.assertLessEqual(h, 64.0)

    def test_条带高度跟着真实高走(self):
        strip, scale = capture.capture_strip()
        if strip is None:  # 没给屏幕录制权限（CI/新机器）：跳过，不假绿
            self.skipTest("无屏幕录制权限，截不到条带")
        import Quartz
        got = Quartz.CGImageGetHeight(strip) / max(scale, 1.0)
        self.assertAlmostEqual(got, capture.menu_bar_height(), delta=1.5)


if __name__ == "__main__":
    unittest.main()
