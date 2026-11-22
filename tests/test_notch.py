#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""遮挡判定纯逻辑单测：rect_intersects（刘海横向区间相交）+ notch_region（刘海区间提取）。

运行：项目根目录下 `python3 -m unittest discover -s tests -t .`
不碰真实 AX/屏幕（screen 用 SimpleNamespace 桩模拟 auxiliaryTop*Area）。
"""
import types
import unittest

from peasebar import axutil


class TestRectIntersects(unittest.TestCase):
    NOTCH = (100.0, 200.0)  # 刘海横向区间 [x0, x1)

    def test相交(self):
        self.assertTrue(axutil.rect_intersects((150, 0, 30, 24), *self.NOTCH))

    def test完全在区间内(self):
        self.assertTrue(axutil.rect_intersects((120, 0, 10, 24), *self.NOTCH))

    def test完全包含区间(self):
        self.assertTrue(axutil.rect_intersects((50, 0, 200, 24), *self.NOTCH))

    def test右侧不相交(self):
        self.assertFalse(axutil.rect_intersects((210, 0, 30, 24), *self.NOTCH))

    def test左侧不相交(self):
        self.assertFalse(axutil.rect_intersects((60, 0, 30, 24), *self.NOTCH))

    def test左贴边不相交(self):
        # 区间语义 [x0, x1)：右边缘恰好压在 x0 上不算相交
        self.assertFalse(axutil.rect_intersects((70, 0, 30, 24), *self.NOTCH))

    def test右贴边不相交(self):
        # 左边缘恰好压在 x1 上不算相交
        self.assertFalse(axutil.rect_intersects((200, 0, 30, 24), *self.NOTCH))

    def test零宽图标不相交(self):
        self.assertFalse(axutil.rect_intersects((150, 0, 0, 24), *self.NOTCH))

    def test无坐标返回False(self):
        self.assertFalse(axutil.rect_intersects(None, *self.NOTCH))


def _rect(x, y, w, h):
    """构造 NSScreen 几何桩（notch_region 只读 origin/size）。"""
    return types.SimpleNamespace(origin=types.SimpleNamespace(x=x, y=y),
                                 size=types.SimpleNamespace(width=w, height=h))


def _screen(aux_left, aux_right, frame):
    return types.SimpleNamespace(auxiliaryTopLeftArea=lambda: aux_left,
                                 auxiliaryTopRightArea=lambda: aux_right,
                                 frame=lambda: frame)


class TestNotchRegion(unittest.TestCase):
    def test有刘海返回区间(self):
        # 屏宽 2560，左辅助区 [0, 1225)，右辅助区 [1335, 2560) → 刘海 [1225, 1335)
        screen = _screen(_rect(0, 0, 1225, 24), _rect(1335, 0, 1225, 24),
                         _rect(0, 0, 2560, 1440))
        self.assertEqual(axutil.notch_region(screen), (1225.0, 1335.0))

    def test无刘海返回None(self):
        # 左右辅助区相接（无缝隙）= 无刘海机型
        screen = _screen(_rect(0, 0, 1280, 24), _rect(1280, 0, 1280, 24),
                         _rect(0, 0, 2560, 1440))
        self.assertIsNone(axutil.notch_region(screen))

    def test微小缝隙仍算刘海(self):
        # 0.5pt 容差：缝隙 > 0.5 判刘海，<= 0.5 视为渲染误差判无
        screen = _screen(_rect(0, 0, 1225, 24), _rect(1225.6, 0, 1334.4, 24),
                         _rect(0, 0, 2560, 1440))
        self.assertEqual(axutil.notch_region(screen), (1225.0, 1225.6))


if __name__ == "__main__":
    unittest.main()
