#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""layout_table 纯逻辑单测：状态键匹配、停车权重、批量计划。

全程 monkeypatch read_positions/write_positions/relayout/原权重存档，绝不碰
真实文件、不需要辅助功能或布局表授权。运行：项目根 `python3 -m unittest discover -s tests -t .`
"""
import unittest

from peasebar import layout_table as L


class Item:
    def __init__(self, bid, part="", label=""):
        self.owner_bundle_id = bid
        self.key_part = part
        self.label = label


TABLE = {
    "status:com.tencent.qq::Item": 120,
    "status:com.henrikruscon.Alcove::Alcove": 200,
    "status:com.apple.menuextra.clock::clock": 300,
    "status:com.sogou.inputmethod::搜狗拼音": 150,
}


class Base(unittest.TestCase):
    def setUp(self):
        self._read = L.read_positions
        self._write = L.write_positions
        self._relayout = L.relayout
        self._rem = L._remember_original
        self._pop = L._pop_original
        self.last = {}
        L.read_positions = lambda: dict(TABLE)
        L.write_positions = lambda pos: (self.last.__setitem__("p", dict(pos)), True)[1]
        L.relayout = lambda: None
        L._remember_original = lambda *a, **k: None
        L._pop_original = lambda k: None

    def tearDown(self):
        L.read_positions = self._read
        L.write_positions = self._write
        L.relayout = self._relayout
        L._remember_original = self._rem
        L._pop_original = self._pop


class TestResolve(Base):
    def test_单命中按owner(self):
        keys = list(TABLE.keys())
        self.assertEqual(
            L.resolve_key(Item("com.tencent.qq", "Item", "QQ"), keys),
            "status:com.tencent.qq::Item")

    def test_中文稳定名命中(self):
        keys = list(TABLE.keys())
        self.assertEqual(
            L.resolve_key(Item("com.sogou.inputmethod", "搜狗拼音", "搜狗拼音"), keys),
            "status:com.sogou.inputmethod::搜狗拼音")

    def test_owner不在表返回None(self):
        self.assertIsNone(L.resolve_key(Item("com.none.app", "X", "X"), list(TABLE.keys())))

    def test_无owner返回None(self):
        self.assertIsNone(L.resolve_key(Item("", "", ""), list(TABLE.keys())))


class TestWeights(Base):
    def test_hide写停车权重(self):
        self.assertTrue(L.hide(Item("com.henrikruscon.Alcove", "Alcove", "Alcove")))
        w = self.last["p"]["status:com.henrikruscon.Alcove::Alcove"]
        self.assertGreaterEqual(w, L.HIDDEN_BASE)
        self.assertTrue(L.is_parked(w))

    def test_always_hide更高基准(self):
        L.hide(Item("com.tencent.qq", "Item", "QQ"), always=True)
        w = self.last["p"]["status:com.tencent.qq::Item"]
        self.assertGreaterEqual(w, L.ALWAYS_BASE)

    def test_apply_plan批量(self):
        L.apply_plan({
            "status:com.tencent.qq::Item": "hidden",
            "status:com.sogou.inputmethod::搜狗拼音": "always_hidden",
            "status:com.apple.menuextra.clock::clock": "visible",
        })
        p = self.last["p"]
        self.assertTrue(L.is_parked(p["status:com.tencent.qq::Item"]))
        self.assertGreaterEqual(p["status:com.sogou.inputmethod::搜狗拼音"], L.ALWAYS_BASE)
        self.assertFalse(L.is_parked(p["status:com.apple.menuextra.clock::clock"]))

    def test_is_parked边界(self):
        self.assertFalse(L.is_parked(49999))
        self.assertTrue(L.is_parked(50000))
        self.assertTrue(L.is_parked(60000))


if __name__ == "__main__":
    unittest.main()
