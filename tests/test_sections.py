#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sections 纯逻辑单测：分区键、查询、移区、分桶、顺序、持久化往返。

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
            self.assertEqual(cfg, dict(sections.DEFAULT_CONFIG))

    def test损坏文件回默认(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{不是json")
            self.assertEqual(sections.load_config(path),
                             dict(sections.DEFAULT_CONFIG))

    def test加载丢弃脏分区值(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"sections": {"a|A": "bogus", "b|B": "hidden"},
                           "panel_timeout": -3}, f)
            cfg = sections.load_config(path)
            self.assertEqual(cfg["sections"], {"b|B": sections.SECTION_HIDDEN})
            self.assertEqual(cfg["panel_timeout"], 8)  # 负数非法 → 回默认

    def test_control_icon往返与脏值回默认(self):
        # 触发图标预设：表内的存得住，表外/非字符串一律回默认（渲染端不二次校验）
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            cfg = dict(sections.load_config(path), control_icon="eye")
            sections.save_config(cfg, path)
            self.assertEqual(sections.load_config(path)["control_icon"], "eye")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"control_icon": "not-a-symbol"}, f)
            self.assertEqual(sections.load_config(path)["control_icon"],
                             sections.DEFAULT_CONFIG["control_icon"])

    def test保存自动建目录且无半截文件(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "dir", "config.json")
            sections.save_config({"sections": {}, "panel_timeout": 8}, path)
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_order去重保序且丢非字符串(self):
        # 脏数据里的重复键会让位次计算自相矛盾（同一个键两个位置），加载时就清掉
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"order": ["a|A", "b|B", "a|A", 7, None, "c|C"]}, f)
            self.assertEqual(sections.load_config(path)["order"],
                             ["a|A", "b|B", "c|C"])

    def test_旧配置没order字段(self):
        # 升级前的 config.json 里没有 order，不能因此报错或打乱盘点顺序
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"sections": {"a|A": "hidden"}, "panel_timeout": 3}, f)
            cfg = sections.load_config(path)
            self.assertEqual(cfg["order"], [])
            items = [item("a", "A"), item("b", "B")]
            self.assertEqual([sections.item_key(i) for i in sections.apply_order(items, cfg)],
                             ["a|A", "b|B"])


class TestOrder(unittest.TestCase):
    """区内顺序（设置页 ⌥←/→ 与前移/后移的读侧与写侧）。"""

    def setUp(self):
        self.items = [item("a", "A"), item("b", "B"), item("c", "C")]

    def keys(self, cfg):
        return [sections.item_key(i) for i in sections.apply_order(self.items, cfg)]

    def test_没记过名时保持盘点顺序(self):
        self.assertEqual(self.keys({"order": []}), ["a|A", "b|B", "c|C"])

    def test_显式顺序接管排列(self):
        self.assertEqual(self.keys({"order": ["c|C", "a|A", "b|B"]}),
                         ["c|C", "a|A", "b|B"])

    def test_新图标排在末尾不插队(self):
        # order 里只有 a/b（c 是刚出现的 App）→ c 补位到末尾，不能顶掉用户调好的顺序
        self.assertEqual(self.keys({"order": ["b|B", "a|A"]}), ["b|B", "a|A", "c|C"])

    def test_move_in_list前后移(self):
        keys = ["a|A", "b|B", "c|C"]
        self.assertEqual(sections.move_in_list(keys, "c|C", -1),
                         (["a|A", "c|C", "b|B"], True))
        self.assertEqual(sections.move_in_list(keys, "a|A", 1),
                         (["b|B", "a|A", "c|C"], True))

    def test_move_in_list边界与未知键不算改动(self):
        # 返回 changed=False 才能让调用方跳过写盘与记撤销点（否则 ⌘Z 会被无效按键填满）
        keys = ["a|A", "b|B"]
        self.assertEqual(sections.move_in_list(keys, "a|A", -1), (keys, False))
        self.assertEqual(sections.move_in_list(keys, "b|B", 1), (keys, False))
        self.assertEqual(sections.move_in_list(keys, "z|Z", 1), (keys, False))
        self.assertEqual(keys, ["a|A", "b|B"])  # 不就地改入参

    def test_plan_sections桶内也按顺序(self):
        cfg = {"sections": {"a|A": "hidden"}, "order": ["c|C", "b|B", "a|A"]}
        buckets = sections.plan_sections(self.items, cfg)
        self.assertEqual([sections.item_key(i) for i in buckets[sections.SECTION_VISIBLE]],
                         ["c|C", "b|B"])
        self.assertEqual([sections.item_key(i) for i in buckets[sections.SECTION_HIDDEN]],
                         ["a|A"])

    def test_store_order与flatten往返(self):
        cfg = {"sections": {}, "order": []}
        buckets = sections.plan_sections(self.items, cfg)
        buckets[sections.SECTION_VISIBLE] = list(reversed(buckets[sections.SECTION_VISIBLE]))
        sections.store_order(cfg, sections.flatten(buckets))
        self.assertEqual(cfg["order"], ["c|C", "b|B", "a|A"])
        again = sections.plan_sections(self.items, cfg)
        self.assertEqual([sections.item_key(i) for i in again[sections.SECTION_VISIBLE]],
                         ["c|C", "b|B", "a|A"])

    def test_快照与恢复(self):
        cfg = {"sections": {"a|A": "hidden"}, "order": ["b|B", "a|A"], "panel_timeout": 9}
        snap = sections.snapshot(cfg)
        cfg["sections"]["c|C"] = "always_hidden"
        cfg["order"] = ["c|C"]
        self.assertTrue(sections.restore_snapshot(cfg, snap))
        self.assertEqual(cfg["sections"], {"a|A": "hidden"})
        self.assertEqual(cfg["order"], ["b|B", "a|A"])
        self.assertEqual(cfg["panel_timeout"], 9)  # 行为配置不参与撤销
        snap["sections"]["a|A"] = "bogus"  # 快照与 cfg 必须解耦
        self.assertEqual(cfg["sections"]["a|A"], "hidden")


class TestSortAndReset(unittest.TestCase):
    """Phase 4e：每区「按名称排序」与「重置布局」（对应 Thaw Sort by Name / Reset Layout）。"""

    def setUp(self):
        self.items = [item("com.b", "Beta"), item("com.a", "alpha"),
                      item("com.c", "Gamma")]
        self.buckets = {sections.SECTION_VISIBLE: self.items,
                        sections.SECTION_HIDDEN: [], sections.SECTION_ALWAYS_HIDDEN: []}

    def test_按名称排序大小写不敏感(self):
        out, changed = sections.sort_bucket_by_name(self.buckets, sections.SECTION_VISIBLE)
        self.assertTrue(changed)
        self.assertEqual([it.label for it in out[sections.SECTION_VISIBLE]],
                         ["alpha", "Beta", "Gamma"])
        self.assertEqual([it.label for it in self.buckets[sections.SECTION_VISIBLE]],
                         ["Beta", "alpha", "Gamma"])  # 入参不被改

    def test_已有序时不算改动(self):
        # 排完一次再排一次：已经有序就不报 changed（调用方据此不写盘、不留撤销点）
        out, _ = sections.sort_bucket_by_name(self.buckets, sections.SECTION_VISIBLE)
        _, again = sections.sort_bucket_by_name(out, sections.SECTION_VISIBLE)
        self.assertFalse(again)

    def test_单元素与空区(self):
        for sec, group in ((sections.SECTION_VISIBLE, [self.items[0]]),
                           (sections.SECTION_HIDDEN, [])):
            out, changed = sections.sort_bucket_by_name({sec: group}, sec)
            self.assertEqual(out[sec], group)
            self.assertFalse(changed)

    def test_重置只动分区与顺序(self):
        cfg = {"sections": {"a|A": "hidden", "c|C": "always_hidden"},
               "order": ["c|C", "a|A"], "panel_timeout": 5}
        sections.reset_layout(cfg)
        self.assertEqual(cfg["sections"], {})
        self.assertEqual(cfg["order"], [])
        self.assertEqual(cfg["panel_timeout"], 5)  # 行为配置不归布局重置管


if __name__ == "__main__":
    unittest.main()
