# -*- coding: utf-8 -*-
"""设置页键盘编辑（Phase 4d，照 Thaw「⌥-arrows to move the selected one」）。

只测「按键 → 语义」这层路由与写入，不碰 AppKit 渲染：
控制器用桩件（`_rebuild` 换成记号、配置指向临时文件），真机一致性由 tmp/t_p4.py 的 P81–P86 取证。
"""
import os
import tempfile
import types
import unittest

from peasebar import sections, settings

KEY_LEFT, KEY_RIGHT, KEY_DOWN, KEY_UP = (
    settings.KEY_LEFT, settings.KEY_RIGHT, settings.KEY_DOWN, settings.KEY_UP)


def item(bid, label):
    return types.SimpleNamespace(owner_bundle_id=bid, label=label, key_part="",
                                 owner_app=label)


def key_event(code, opt=False, cmd=False, ch=""):
    """假 NSEvent：控制器只读 keyCode/modifierFlags/charactersIgnoringModifiers 三样。"""
    flags = ((settings.NSEventModifierFlagOption if opt else 0) |
             (settings.NSEventModifierFlagCommand if cmd else 0))
    return types.SimpleNamespace(
        keyCode=lambda: code,
        modifierFlags=lambda: flags,
        charactersIgnoringModifiers=lambda: ch,
    )


class KeyCase(unittest.TestCase):
    """公共脚手架：三个可见项 + 一份临时配置，用例之间互不影响。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "config.json")
        self._real_path = sections.config_path
        sections.config_path = lambda: self.path
        self.ctrl = settings.SettingsController.alloc().init()
        self.ctrl.items = [item("a", "A"), item("b", "B"), item("c", "C")]
        self.ctrl.buckets = sections.plan_sections(self.ctrl.items,
                                                   sections.load_config(self.path))
        # 不建窗口：把重建换成记号，既能验「改一次刷一次」，也不会碰 AppKit
        self.rebuilt = []
        self.ctrl._rebuild = lambda: self.rebuilt.append(True)

    def tearDown(self):
        sections.config_path = self._real_path
        self.dir.cleanup()

    def cfg(self):
        return sections.load_config(self.path)

    def draft(self):
        """当前草稿（无编辑时等同盘上配置）：暂存+应用模式下编辑先落草稿。"""
        if self.ctrl._pending_cfg is not None:
            return self.ctrl._pending_cfg
        return self.cfg()

    def apply_now(self):
        """同步跑完「应用改动」：后台生效部分打桩成立即执行，不碰真 AX/拖拽。"""
        self.ctrl.real_bar = False  # real_bar 关时应用流程不碰 CC/拖拽
        self.ctrl._reload_items = lambda: None
        self.ctrl.performSelectorOnMainThread_withObject_waitUntilDone_ = (
            lambda sel, obj, wait: self.ctrl.applyDone_(obj))
        self.ctrl.onApplyLayout_(None)

    def keys_of(self, sec):
        return [sections.item_key(i) for i in self.ctrl.buckets[sec]]

    def select(self, label):
        key = f"{label.lower()}|{label}"
        self.ctrl.selected_key = key
        return key


class TestArrowEdit(KeyCase):
    def test_alt_right_moves_within_section(self):
        """⌥→/⌥←：同区内前后移一格（暂存+应用模式：先落草稿，应用才写盘）。"""
        self.select("A")
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_RIGHT, opt=True)))
        self.assertEqual(self.draft()["order"], ["b|B", "a|A", "c|C"])
        self.assertEqual(self.keys_of(sections.SECTION_VISIBLE), ["b|B", "a|A", "c|C"])
        self.assertEqual(self.rebuilt, [True])  # 每次真改动都刷一次界面
        self.assertEqual(self.cfg()["order"], [])  # 盘上未动：还没点应用
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_LEFT, opt=True)))
        self.assertEqual(self.draft()["order"], ["a|A", "b|B", "c|C"])
        self.apply_now()
        self.assertEqual(self.cfg()["order"], ["a|A", "b|B", "c|C"])  # 应用后落盘

    def test_alt_at_border_is_not_an_edit(self):
        """末格再 ⌥→ 不算改动：不写盘、不记撤销点（否则 ⌘Z 会被无效按键填满）。"""
        self.select("C")
        self.assertFalse(self.ctrl.handleKey_(key_event(KEY_RIGHT, opt=True)))
        self.assertEqual(self.ctrl._undo, [])
        self.assertEqual(self.rebuilt, [])
        self.assertEqual(self.cfg()["order"], [])

    def test_alt_up_down_changes_section(self):
        """⌥↓：可见区 → 隐藏区 → 永久隐藏；到底不给动，⌥↑ 原路回来（草稿）。"""
        key = self.select("B")
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_DOWN, opt=True)))
        self.assertEqual(self.draft()["sections"].get(key), sections.SECTION_HIDDEN)
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_DOWN, opt=True)))
        self.assertEqual(self.draft()["sections"].get(key), sections.SECTION_ALWAYS_HIDDEN)
        self.assertFalse(self.ctrl.handleKey_(key_event(KEY_DOWN, opt=True)))
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_UP, opt=True)))
        self.assertEqual(self.draft()["sections"].get(key), sections.SECTION_HIDDEN)

    def test_换区后落在目标区末尾(self):
        """不物化顺序的话，新位置由旧 order 位次决定，跳来跳去没规律。"""
        self.select("C")
        self.ctrl.handleKey_(key_event(KEY_DOWN, opt=True))
        self.assertEqual(self.keys_of(sections.SECTION_HIDDEN), ["c|C"])
        self.select("A")
        self.ctrl.handleKey_(key_event(KEY_DOWN, opt=True))
        self.assertEqual(self.keys_of(sections.SECTION_HIDDEN), ["c|C", "a|A"])

    def test_原地不动不算改动(self):
        """已在可见区再按「移到可见区」→ 不写盘、不记撤销点。"""
        key = self.select("A")
        self.ctrl.applyMove_to_(key, sections.SECTION_VISIBLE)
        self.assertEqual(self.ctrl._undo, [])
        self.assertEqual(self.rebuilt, [])

    def test_选中项消失后按键不炸(self):
        """App 退出让选中项蒸发时，⌥→ 应安静地不动，而不是拿 None 去解坐标。"""
        self.ctrl.selected_key = "gone|Gone"
        self.assertFalse(self.ctrl.handleKey_(key_event(KEY_RIGHT, opt=True)))
        self.assertFalse(self.ctrl.handleKey_(key_event(KEY_DOWN, opt=True)))


class TestFocusMove(KeyCase):
    def test_arrows_move_selection_only(self):
        """不带 ⌥ 的方向键只移动选中焦点，绝不碰配置。"""
        self.select("A")
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_RIGHT)))
        self.assertEqual(self.ctrl.selected_key, "b|B")
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_RIGHT)))
        self.assertEqual(self.ctrl.selected_key, "c|C")
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_RIGHT)))  # 末格夹住
        self.assertEqual(self.ctrl.selected_key, "c|C")
        self.assertEqual(self.rebuilt, [])  # 换选不重建界面
        self.assertEqual(self.cfg()["order"], [])

    def test_跳区落在目标区夹住的位置(self):
        """↑/↓ 跳区：目标区是空的就跳不过去（不丢选中），非空则按位次夹住落位。"""
        self.select("C")  # 可见区第 3 格
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_DOWN)))
        self.assertEqual(self.ctrl.selected_key, "c|C")  # 隐藏区为空 → 原地
        # 造一个只有一格的隐藏区：从第 3 格 ↓ 应夹到那唯一一格
        self.ctrl.handleKey_(key_event(KEY_DOWN, opt=True))  # C → 隐藏区
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_UP)))
        self.assertEqual(self.ctrl.selected_key, "a|A")
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_DOWN)))
        self.assertEqual(self.ctrl.selected_key, "c|C")

    def test_selection_starts_somewhere(self):
        """没选中时按一下方向键就有的选（照 select_neighbour 的兜底）。"""
        self.ctrl.selected_key = None
        self.assertTrue(self.ctrl.handleKey_(key_event(KEY_LEFT)))
        self.assertEqual(self.ctrl.selected_key, "a|A")

    def test_arrow_without_items_is_not_consumed(self):
        """一个图标都没有 → 返回 False，让系统该响铃响铃，不静默吞键。"""
        self.ctrl.buckets = {s: [] for s in settings._SECTION_ORDER}
        self.ctrl.selected_key = None
        self.assertFalse(self.ctrl.handleKey_(key_event(KEY_LEFT)))

    def test_unrelated_key_passes_through(self):
        self.select("A")
        self.assertFalse(self.ctrl.handleKey_(key_event(0, ch="a")))


class TestCommandKeys(KeyCase):
    def test_cmd_number_moves_to_section(self):
        """⌘2 移到隐藏区（暂存+应用模式：落草稿待应用）。"""
        key = self.select("A")
        self.assertTrue(self.ctrl.handleKey_(key_event(0, cmd=True, ch="2")))
        self.assertEqual(self.draft()["sections"].get(key), sections.SECTION_HIDDEN)

    def test_cmd_without_selection(self):
        self.ctrl.selected_key = None
        self.assertFalse(self.ctrl.handleKey_(key_event(0, cmd=True, ch="3")))

    def test_undo_逐步回退(self):
        """⌘Z 逐步回退顺序与分区改动（回草稿）；栈空时返回 False（让系统响铃）。"""
        self.select("A")
        self.ctrl.handleKey_(key_event(KEY_RIGHT, opt=True))   # 改动 1：顺序
        self.ctrl.handleKey_(key_event(KEY_DOWN, opt=True))    # 改动 2：换区
        self.assertEqual(len(self.ctrl._undo), 2)
        self.assertTrue(self.ctrl.handleKey_(key_event(0, cmd=True, ch="z")))
        self.assertIsNone(self.draft()["sections"].get("a|A"))   # 改动 2 已回退
        self.assertTrue(self.ctrl.handleKey_(key_event(0, cmd=True, ch="z")))
        self.assertEqual(self.draft()["order"], [])              # 改动 1 已回退
        self.assertFalse(self.ctrl.handleKey_(key_event(0, cmd=True, ch="z")))

    def test_撤销按钮与快捷键同路(self):
        """撤销也只回退草稿（应用才落盘）：盘上配置在撤销前后都不动。"""
        self.select("B")
        self.ctrl.handleKey_(key_event(KEY_LEFT, opt=True))
        before = self.draft()["order"]
        self.ctrl.onUndo()
        self.assertNotEqual(self.draft()["order"], before)
        self.assertEqual(self.cfg()["order"], [])  # 盘上从未动过

    def test_撤销栈有上限(self):
        """手滑按到底也不能无限吃内存（栈深 UNDO_LIMIT，超出丢最老的）。"""
        self.select("A")
        for _ in range(settings.UNDO_LIMIT + 5):
            self.ctrl._push_undo({"sections": {}, "order": []})
        self.assertEqual(len(self.ctrl._undo), settings.UNDO_LIMIT)


class TestRowCheck(KeyCase):
    """单列清单行首复选框（2026-11-24 对标竞品）：勾选态驱动显隐，
    走 applyMove_to_ 同一条链 —— 进草稿不落盘、⌘Z 可撤、应用才生效。"""

    class _Sender:
        """假 NSButton：控制器只读 representedObject()/state() 两样。"""

        def __init__(self, key, state):
            self._key, self._state = key, state

        def representedObject(self):
            return self._key

        def state(self):
            return self._state

    def test_取消勾选收进弹窗进草稿(self):
        self.ctrl.onRowCheck_(self._Sender("a|A", 0))
        self.assertEqual(self.draft()["sections"].get("a|A"), sections.SECTION_HIDDEN)
        self.assertEqual(self.cfg()["sections"].get("a|A"), None)  # 盘上未动
        self.assertEqual(self.rebuilt, [True])  # 改一次刷一次

    def test_再勾选移回菜单栏显示(self):
        self.ctrl.onRowCheck_(self._Sender("a|A", 0))   # 先收进弹窗
        self.ctrl.onRowCheck_(self._Sender("a|A", 1))   # 再勾回来
        self.assertEqual(sections.section_of(self.draft(), "a|A"),
                         sections.SECTION_VISIBLE)
        # 两次都是真改动：撤销栈里应有两个快照（⌘Z 能逐步回退）
        self.assertEqual(len(self.ctrl._undo), 2)

    def test_勾选态与现状一致不算改动(self):
        """a 本来就在可见区，再勾一次=没改：不开草稿、不记撤销点。"""
        self.ctrl.onRowCheck_(self._Sender("a|A", 1))
        self.assertIsNone(self.ctrl._pending_cfg)
        self.assertEqual(self.ctrl._undo, [])
        self.assertEqual(self.rebuilt, [])

    def test_应用后落盘(self):
        """草稿链不变：勾选改动要等「应用改动」才写盘。"""
        self.ctrl.onRowCheck_(self._Sender("b|B", 0))
        self.assertEqual(self.cfg()["sections"].get("b|B"), None)
        self.apply_now()
        self.assertEqual(self.cfg()["sections"].get("b|B"), sections.SECTION_HIDDEN)


class TestTileIdentity(KeyCase):
    """定调钉桩：格子上只有图标，身份 = 配置键（取证脚本靠 AXIdentifier 认位，T77）。"""

    def make_tile(self, it):
        from peasebar import capture
        self.ctrl.images = {}
        self.ctrl.tiles = {}
        self.ctrl._paint_tile = lambda btn, sel: None   # 不碰图层绘制
        orig = capture.fallback_image_for_item
        capture.fallback_image_for_item = lambda item: None
        try:
            return self.ctrl._make_tile(it, sections.SECTION_VISIBLE, 0, 0)
        finally:
            capture.fallback_image_for_item = orig

    def test_格子身份是配置键且无标题(self):
        btn = self.make_tile(item("a", "A"))
        self.assertEqual(btn.accessibilityIdentifier(), "a|A")
        self.assertEqual(btn.title(), "")               # 绝不显示名字
        self.assertIn("A", btn.toolTip() or "")         # 名字只进 tooltip

    def test_活文本改名不改身份(self):
        """温度/网速这类图标名随时会变；键由 key_part 生成，与活文本无关。"""
        hot = types.SimpleNamespace(owner_bundle_id="tg", label="Core 8: 59°C",
                                    key_part="Performance Core", owner_app="TG Pro")
        self.assertEqual(sections.item_key(hot), "tg|Performance Core")
        btn = self.make_tile(hot)
        self.assertEqual(btn.accessibilityIdentifier(), "tg|Performance Core")


if __name__ == "__main__":
    unittest.main()
