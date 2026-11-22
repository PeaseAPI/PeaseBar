#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sections 纯逻辑单测：分区键、查询、移区、分桶、持久化往返。

运行：项目根目录下 `python3 -m unittest discover -s tests -t .`
不依赖 AppKit/AX 权限，item 用 SimpleNamespace 桩（只需 owner_bundle_id/label）。
"""
import json
import os
import tempfile
import types
import unittest

from peasebar import sections


def item(bid, label, key_part=""):
    return types.SimpleNamespace(owner_bundle_id=bid, label=label, key_part=key_part)


class TestItemKey(unittest.TestCase):
    def test_key拼接(self):
        self.assertEqual(sections.item_key(item("com.qq", "QQ")), "com.qq|QQ")

    def test_key区分双图标同名标签(self):
        # 同 bundleId 不同 label → 不同键（双图标消歧靠 inventory._dedup_keys 的 #rank）
        self.assertNotEqual(sections.item_key(item("com.x", "A")),
                            sections.item_key(item("com.x", "B")))

    def test_稳定键优先用_key_part(self):
        # 实测教训（T55）：label 常是活文本（温度/未读数），key_part 才是稳定身份
        it = item("com.tgpro", "Performance Core 3: 57°C", key_part="com.tgpro.fan")
        self.assertEqual(sections.item_key(it), "com.tgpro|com.tgpro.fan")

    def test_无_key_part时回落_label(self):
        self.assertEqual(sections.item_key(item("com.a", "A", key_part="")), "com.a|A")


class TestSectionOf(unittest.TestCase):
    def setUp(self):
        self.cfg = sections.load_config(":nonexistent:")  # 纯默认

    def test无记录默认可见区(self):
        self.assertEqual(sections.section_of(self.cfg, "com.qq|QQ"),
                         sections.SECTION_VISIBLE)

    def test显式隐藏区(self):
        self.cfg["sections"]["com.qq|QQ"] = sections.SECTION_HIDDEN
        self.assertEqual(sections.section_of(self.cfg, "com.qq|QQ"),
                         sections.SECTION_HIDDEN)

    def test显式永久隐藏区(self):
        self.cfg["sections"]["com.qq|QQ"] = sections.SECTION_ALWAYS_HIDDEN
        self.assertEqual(sections.section_of(self.cfg, "com.qq|QQ"),
                         sections.SECTION_ALWAYS_HIDDEN)

    def test脏值回可见区(self):
        self.cfg["sections"]["com.qq|QQ"] = "bogus"
        self.assertEqual(sections.section_of(self.cfg, "com.qq|QQ"),
                         sections.SECTION_VISIBLE)


class TestSetSection(unittest.TestCase):
    def test移入隐藏区写键(self):
        cfg = {"sections": {}}
        sections.set_section(cfg, "com.qq|QQ", sections.SECTION_HIDDEN)
        self.assertEqual(cfg["sections"]["com.qq|QQ"], sections.SECTION_HIDDEN)

    def test移入永久隐藏区写键(self):
        cfg = {"sections": {}}
        sections.set_section(cfg, "com.qq|QQ", sections.SECTION_ALWAYS_HIDDEN)
        self.assertEqual(cfg["sections"]["com.qq|QQ"], sections.SECTION_ALWAYS_HIDDEN)

    def test回可见区删键(self):
        cfg = {"sections": {"com.qq|QQ": sections.SECTION_HIDDEN}}
        sections.set_section(cfg, "com.qq|QQ", sections.SECTION_VISIBLE)
        self.assertNotIn("com.qq|QQ", cfg["sections"])

    def test回可见区对无记录项是幂等no_op(self):
        cfg = {"sections": {}}
        sections.set_section(cfg, "com.qq|QQ", sections.SECTION_VISIBLE)
        self.assertEqual(cfg["sections"], {})


class TestPlanSections(unittest.TestCase):
    def test三区分桶保持顺序(self):
        cfg = {"sections": {
            "b|hb": sections.SECTION_HIDDEN,
            "b|ah": sections.SECTION_ALWAYS_HIDDEN,
        }}
        items = [item("b", "v1"), item("b", "hb"), item("b", "v2"), item("b", "ah")]
        buckets = sections.plan_sections(items, cfg)
        self.assertEqual([i.label for i in buckets[sections.SECTION_VISIBLE]], ["v1", "v2"])
        self.assertEqual([i.label for i in buckets[sections.SECTION_HIDDEN]], ["hb"])
        self.assertEqual([i.label for i in buckets[sections.SECTION_ALWAYS_HIDDEN]], ["ah"])

    def test空清单返回三个空桶(self):
        buckets = sections.plan_sections([], {"sections": {}})
        for s in (sections.SECTION_VISIBLE, sections.SECTION_HIDDEN,
                  sections.SECTION_ALWAYS_HIDDEN):
            self.assertEqual(buckets[s], [])


class TestPersist(unittest.TestCase):
    def test保存再加载往返(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            cfg = {"sections": {"com.qq|QQ": sections.SECTION_HIDDEN,
                                "com.wc|微信": sections.SECTION_ALWAYS_HIDDEN},
                   "panel_timeout": 0}
            sections.save_config(cfg, path)
            loaded = sections.load_config(path)
            self.assertEqual(loaded["sections"], cfg["sections"])
            self.assertEqual(loaded["panel_timeout"], 0)

    def test无文件回默认(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "missing.json")
            cfg = sections.load_config(path)
            self.assertEqual(cfg, {"sections": {}, "panel_timeout": 8})

    def test损坏文件回默认(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{不是json")
            self.assertEqual(sections.load_config(path),
                             {"sections": {}, "panel_timeout": 8})

    def test加载丢弃脏分区值(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"sections": {"a|A": "bogus", "b|B": "hidden"},
                           "panel_timeout": -3}, f)
            cfg = sections.load_config(path)
            self.assertEqual(cfg["sections"], {"b|B": sections.SECTION_HIDDEN})
            self.assertEqual(cfg["panel_timeout"], 8)  # 负数非法 → 回默认

    def test保存自动建目录且无半截文件(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "dir", "config.json")
            sections.save_config({"sections": {}, "panel_timeout": 8}, path)
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(os.path.exists(path + ".tmp"))


if __name__ == "__main__":
    unittest.main()
