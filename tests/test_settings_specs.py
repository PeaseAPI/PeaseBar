#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 11：12 页设置规格的结构性冒烟测试。

只做纯逻辑校验（不调 AppKit 建视图），守住「按 Thaw 截图 1:1 重写」的骨架：
- 每个非布局页都有 _spec_<key>；
- _spec_* 返回块列表，块键与行/控制件结构合法；
- 侧栏分组覆盖全部 12 页，且分组名已中文化（首组空、模块、管理）。
"""
import unittest

from peasebar import settings


VALID_BLOCK_KEYS = {"heading", "rows", "tabbar", "para", "standalone", "options", "page"}
VALID_CTL_KINDS = {"switch", "popup", "segmented", "toggles", "slider",
                   "text", "buttons", "status", "launch", "timeout", "control_icon"}
# 每种控制件元组的期望长度（kind + 参数）；buttons/toggles 变长按首元素判。
CTL_MIN_ARITY = {"switch": 2, "popup": 3, "segmented": 3, "toggles": 2,
                 "slider": 5, "text": 3, "buttons": 2, "status": 3,
                 "launch": 1, "timeout": 1, "control_icon": 1}


def _make_controller():
    ctrl = settings.SettingsController.alloc().init()
    ctrl.items = []  # 疑难解答/隐私页会读 self.items 计数，给个空列表
    ctrl.no_permission = False
    return ctrl


def _iter_rows(block):
    for key in ("rows", "standalone"):
        for row in block.get(key) or []:
            yield row


class TestSidebarStructure(unittest.TestCase):
    def test_pages_are_real_eight(self):
        """只留真实生效的页（外观/工具栏/显示器/模块四页后端从未实现，已摘）。"""
        keys = [k for k, _l, _s in settings.PAGES]
        self.assertEqual(keys, ["general", "layout", "visibility", "shortcuts",
                                "profiles", "privacy", "troubleshoot", "about"])

    def test_sidebar_groups_cover_every_page(self):
        listed = [k for _g, keys in settings._SIDEBAR_GROUPS for k in keys]
        self.assertEqual(sorted(listed), sorted(k for k, _l, _s in settings.PAGES))

    def test_sidebar_group_labels_chinese(self):
        labels = [g for g, _k in settings._SIDEBAR_GROUPS]
        self.assertEqual(labels, ["", "管理"])

    def test_ui_strings_no_english(self):
        """用户定调全中文：页名/副标题/分组标题不得再出现英文文案（品牌名除外）。"""
        import re
        allowed = re.compile(r"^(PeaseBar[\u4e00-\u9fff（）/、， ]*)$")
        for _k, label, sub in settings.PAGES:
            if not allowed.match(label):
                self.assertIsNone(re.search(r"[A-Za-z]{2,}", label), f"页名仍有英文：{label}")
            if not allowed.match(sub):
                self.assertIsNone(re.search(r"[A-Za-z]{2,}", sub), f"副标题仍有英文：{sub}")
        for g, _keys in settings._SIDEBAR_GROUPS:
            if g:
                self.assertIsNone(re.search(r"[A-Za-z]{2,}", g), f"分组标题仍有英文：{g}")


class TestPageSpecs(unittest.TestCase):
    def setUp(self):
        self.ctrl = _make_controller()

    def test_every_static_page_has_spec(self):
        for key, _label, _sub in settings.PAGES:
            if key == "layout":
                continue
            self.assertTrue(hasattr(self.ctrl, "_spec_" + key), f"缺 _spec_{key}")

    def test_specs_return_wellformed_blocks(self):
        for key, _label, _sub in settings.PAGES:
            if key == "layout":
                continue
            blocks = getattr(self.ctrl, "_spec_" + key)()
            self.assertIsInstance(blocks, list, f"{key} 页规格不是列表")
            for block in blocks:
                self.assertIsInstance(block, dict)
                self.assertTrue(set(block).issubset(VALID_BLOCK_KEYS),
                                f"{key} 页出现未知块键：{set(block) - VALID_BLOCK_KEYS}")
                for row in _iter_rows(block):
                    self._check_row(key, row)

    def _check_row(self, page, row):
        self.assertIsInstance(row, dict, f"{page} 页的行不是 dict")
        ctl = row.get("ctl")
        if ctl is None:
            return
        self.assertIsInstance(ctl, tuple, f"{page} 页 ctl 不是元组")
        kind = ctl[0]
        self.assertIn(kind, VALID_CTL_KINDS, f"{page} 页出现未知控件：{kind}")
        self.assertGreaterEqual(len(ctl), CTL_MIN_ARITY[kind],
                                f"{page} 页控件 {kind} 参数不足：{ctl}")
        if kind in ("popup", "segmented"):
            for opt in ctl[2]:
                self.assertEqual(len(opt), 2, f"{page} 页 {kind} 选项需 (value,label)：{opt}")
        if kind == "buttons":
            for item in ctl[1]:
                self.assertGreaterEqual(len(item), 2,
                                        f"{page} 页按钮项至少 (label,action)：{item}")

    def test_tabbar_specs_switch_content(self):
        # 有子页签的页：切不同子页都应产出合法块，不抛异常
        for key in ("shortcuts", "troubleshoot"):
            for idx in range(4):
                if not hasattr(self.ctrl, "_subtabs"):
                    self.ctrl._subtabs = {}
                self.ctrl._subtabs[key] = idx
                blocks = getattr(self.ctrl, "_spec_" + key)()
                self.assertIsInstance(blocks, list)


class TestReorderMenu(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.ctrl = _make_controller()
        self.item = SimpleNamespace(owner_bundle_id="com.example.app",
                                    label="示例", key_part="示例")

    def test_menu_has_move_and_reorder_items(self):
        """右键菜单 = 三区移区（⌘1/2/3）+ 分隔线 + 前移/后移（同区改序）。"""
        from peasebar import sections
        menu = self.ctrl._menu_for(self.item, sections.SECTION_VISIBLE)
        items = [menu.itemAtIndex_(i) for i in range(menu.numberOfItems())]
        self.assertEqual(len(items), 6)  # 3 移区 + 分隔线 + 前移 + 后移
        self.assertTrue(items[3].isSeparatorItem())
        for i, tag in ((0, 0), (1, 1), (2, 2)):
            self.assertEqual(str(items[i].action()), "onMoveSection:")
            self.assertEqual(items[i].tag(), tag)
        for i, delta in ((4, -1), (5, 1)):
            self.assertEqual(str(items[i].action()), "onMenuReorder:")
            self.assertEqual(items[i].tag(), delta)
            self.assertEqual(str(items[i].representedObject()),
                             sections.item_key(self.item))

    def test_move_items_reflect_current_section(self):
        """当前区那一项打勾，其余不勾。"""
        from peasebar import sections
        menu = self.ctrl._menu_for(self.item, sections.SECTION_HIDDEN)
        states = [menu.itemAtIndex_(i).state() for i in range(3)]
        self.assertEqual(states, [0, 1, 0])


if __name__ == "__main__":
    unittest.main()
