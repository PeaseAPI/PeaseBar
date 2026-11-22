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
        strip = self._strip(draw_glyph(tile(bg=(0, 0, 0), size=(24, 200))))
        self.assertIsNotNone(capture.image_for_item(strip, 1.0, self.Item((0, 0, 200, 24))))

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


if __name__ == "__main__":
    unittest.main()
