#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拖拽插入位算法（settings.drop_index_in_rows）单测。

Phase 9 真机踩到的两个坑都在这里钉死：
① 只按 x 排会串行 —— 换行开时第二行的 x 与第一行重复，第 3 格拖过去落到第 5 格；
② 同一行的 y 不是完全相等 —— 个别格子（Wi-Fi 那种小图标）会被报高/低 1~2pt。
"""
import unittest

from peasebar.settings import ROW_TOL, drop_index_in_rows, list_drop_target

W, H, GAP = 40.0, 38.0, 4.0


def rects(cols, rows, w=W, h=H, gap=GAP, pad=6.0, y0=4.0):
    """造 rows×cols 的格子矩形：行间距取 42（比 ROW_TOL 大，确保不会被归成一行）。"""
    out = []
    for r in range(rows):
        x = pad
        for _c in range(cols):
            out.append((x, y0 + r * (h + 4.0), w, h))
            x += w + gap
    return out


class TestDropIndexRows(unittest.TestCase):
    def test_单行按中心计数(self):
        rs = rects(4, 1)
        self.assertEqual(drop_index_in_rows(rs, 0, 20), 0)          # 最左：插到第 0 格前
        self.assertEqual(drop_index_in_rows(rs, 25, 20), 0)         # 第 1 格中心（26）左边
        self.assertEqual(drop_index_in_rows(rs, 27, 20), 1)         # 刚过第 1 格中心
        self.assertEqual(drop_index_in_rows(rs, 1000, 20), 4)       # 最右：挂尾

    def test_多行不串行(self):
        rs = rects(3, 2)
        # 第二行第 2 格中心右边：应当是 3（第一行整行）+ 2（本行已过两格）= 5，
        # 而不是只按 x 排出来的数（那样第二行会和第一行的 x 搅在一起串行）
        x = 6.0 + (W + GAP) * 1 + W / 2.0 + 1
        self.assertEqual(drop_index_in_rows(rs, x, 42 + 20), 5)

    def test_落点在所有行下面挂尾(self):
        rs = rects(3, 2)
        self.assertEqual(drop_index_in_rows(rs, 20, 999), 6)

    def test_落点在第一行上面归本行末尾(self):
        rs = rects(3, 2)
        self.assertEqual(drop_index_in_rows(rs, 0, -50), 0)     # 上面且靠左：回到最前
        self.assertEqual(drop_index_in_rows(rs, 1000, -50), 3)  # 上面但靠右：算第一行末尾

    def test_同行y抖动算一行(self):
        rs = rects(3, 1)
        jittered = [(x, y + ROW_TOL / 2.0, w, h) for x, y, w, h in rs]
        self.assertEqual(drop_index_in_rows(jittered, 1000, 20), 3)

    def test_空条返回零(self):
        self.assertEqual(drop_index_in_rows([], 10, 10), 0)

    def test_宽格子按各自宽度定位(self):
        rs = [(6.0, 4.0, 96.0, H), (106.0, 4.0, 32.0, H)]
        self.assertEqual(drop_index_in_rows(rs, 60, 20), 1)    # 落在宽格中心左边→1 个已过
        self.assertEqual(drop_index_in_rows(rs, 130, 20), 2)   # 已过窄格中心（122）→ 挂在窄格后面
        self.assertEqual(drop_index_in_rows(rs, 140, 20), 2)


class TestListDropTarget(unittest.TestCase):
    """单列清单落点（2026-11-24 对标竞品改版）：区的归属跟着落点旁的行走，
    区内序号只数同区的行——拖进别的区行段即换区。纯函数，不碰 AppKit。"""

    V, H, A = "visible", "hidden", "always"
    RH = 40

    def _rows(self):
        seq = [(self.V, "v1"), (self.V, "v2"), (self.H, "h1"),
               (self.H, "h2"), (self.A, "a1")]
        return [(sec, k, (0, i * self.RH, 600, self.RH))
                for i, (sec, k) in enumerate(seq)]

    def test_首行上方插本区最前(self):
        self.assertEqual(list_drop_target(self._rows(), -10), (self.V, 0))

    def test_行中心之上插该行前(self):
        # v2 中60；y=50 在它中心之上 → 插在 v2 前，V 区已有 1 行在前 → (V, 1)
        self.assertEqual(list_drop_target(self._rows(), 50), (self.V, 1))

    def test_跨区边界落新区段首(self):
        # y=70 过了 v2 中心、在 h1 中心（100）之上 → 归 H 区、前面同区 0 行
        self.assertEqual(list_drop_target(self._rows(), 70), (self.H, 0))

    def test_区内序号只数同区行(self):
        # y=150 过了 h2 中心（140）、在 a1 中心（180）之上 → 归 A 区插最前
        self.assertEqual(list_drop_target(self._rows(), 150), (self.A, 0))

    def test_末行之下挂末区末尾(self):
        self.assertEqual(list_drop_target(self._rows(), 9999), (self.A, 1))

    def test_没有行没得落(self):
        self.assertIsNone(list_drop_target([], 10))


if __name__ == "__main__":
    unittest.main()
