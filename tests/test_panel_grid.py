#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板网格尺寸（Phase 9「弹框那么大」的修法）：宽度必须跟着内容走。

只测纯函数 grid_layout——它决定面板多宽多高、几列几行，不碰 AppKit，可离线跑。
"""
import unittest

from peasebar import panel


class TestGridLayout(unittest.TestCase):
    def test_宽度跟着图标数收缩(self):
        """7 个图标不该摊在 468 宽里（两侧各空 60pt 就是用户抱怨的「那么大」）。"""
        w7, *_ = panel.grid_layout(7)
        w3, *_ = panel.grid_layout(3)
        row = panel.CELL_W + panel.CELL_GAP
        self.assertEqual(w7, 2 * panel.EDGE + 7 * row - panel.CELL_GAP)
        self.assertEqual(w3, 2 * panel.EDGE + 3 * row - panel.CELL_GAP)
        self.assertLess(w3, w7)
        self.assertLessEqual(w7, panel.PANEL_MAX_W)

    def test_首格贴边与面板宽(self):
        """探针据此验「没有大片空白」：x0 = (宽-行宽)/2 必须恒等于 EDGE。"""
        for n in (1, 2, 5, 9, 25):
            width, _h, cell_w, cols, _rows = panel.grid_layout(n)
            grid_w = cols * (cell_w + panel.CELL_GAP) - panel.CELL_GAP
            self.assertEqual((width - grid_w) / 2, panel.EDGE, f"{n} 项时没贴边")

    def test_列数上限(self):
        """窄图标一排最多 GRID_COLS 个，多的往下面排。"""
        width, height, cell_w, cols, rows = panel.grid_layout(25)
        self.assertEqual(cols, panel.GRID_COLS)
        self.assertEqual(rows, 3)
        self.assertLessEqual(width, panel.PANEL_MAX_W)
        self.assertEqual(height, 2 * panel.EDGE + rows * (panel.CELL_H + panel.CELL_GAP)
                         - panel.CELL_GAP)

    def test_宽图标把列宽撑起来但列数变少(self):
        """网速/温度这类宽条：格子按图宽伸缩，装不下的列数自然减下来，总宽不越界。"""
        width, _h, cell_w, cols, rows = panel.grid_layout(25, [60] * 25)
        self.assertEqual(cell_w, 60 + 2 * panel.CELL_PAD)
        self.assertLess(cols, panel.GRID_COLS)
        self.assertGreater(rows, 1)
        self.assertLessEqual(width, panel.PANEL_MAX_W)

    def test_列宽有上下限(self):
        """再宽也不超过 CELL_MAX_W（不然一格吃掉整屏），再窄也不小于 CELL_W（整齐）。"""
        self.assertEqual(panel.grid_layout(4, [2])[2], panel.CELL_W)
        self.assertEqual(panel.grid_layout(4, [500])[2], panel.CELL_MAX_W)

    def test_空态给固定小尺寸(self):
        width, height, _cell_w, cols, rows = panel.grid_layout(0)
        self.assertEqual((width, height), (panel.EMPTY_W, 2 * panel.EDGE + panel.EMPTY_H))
        self.assertEqual((cols, rows), (0, 1))

    def test_脏宽度值不参与算列宽(self):
        """None/0/负数都当「没图」，按默认列宽走，不抛也不塌成零宽。"""
        for bad in ([None, 0, -5], []):
            width, _h, cell_w, cols, _rows = panel.grid_layout(3, bad)
            self.assertEqual(cell_w, panel.CELL_W)
            self.assertEqual(cols, 3)
            self.assertGreater(width, 0)


if __name__ == "__main__":
    unittest.main()
