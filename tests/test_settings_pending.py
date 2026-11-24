#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""布局页「暂存 + 应用」模式单测（2026-11-24 用户定调：编辑完点应用才生效）。

覆盖三层：
- 编辑入口（拖拽落位/换区/排序开关/重置）只改草稿副本，盘上配置不动；
- 「应用改动」一次性写盘（real_bar 关时后台链路只做收尾刷新，不碰 CC/拖拽）；
- 应用前快照进撤销栈：应用后 ⌘Z 回滚成草稿，再应用才真正落盘回退；
- 关窗（windowWillClose_）时未应用的草稿自动应用（宁多勿丢）。

真实 CC 写表 / 合成 ⌘-拖能否改系统菜单栏由 tmp/ 探针 + 真机取证，不在这里测。
"""
import os
import tempfile
import types
import unittest

from peasebar import sections, settings


def item(bid, label):
    return types.SimpleNamespace(owner_bundle_id=bid, label=label, key_part="",
                                 owner_app=label)


class PendingCase(unittest.TestCase):
    """公共脚手架：三个可见项 + 一份临时配置，应用流程全程同步化。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "config.json")
        self._real_path = sections.config_path
        sections.config_path = lambda: self.path
        self.ctrl = settings.SettingsController.alloc().init()
        self.ctrl.items = [item("a", "A"), item("b", "B"), item("c", "C")]
        self.ctrl.buckets = sections.plan_sections(self.ctrl.items,
                                                   sections.load_config(self.path))
        self.ctrl._rebuild = lambda: None
        self.reloaded = []
        self.ctrl._reload_items = lambda: self.reloaded.append(True)
        # 后台生效部分同步执行：real_bar=False 已不碰 CC/拖拽，applyDone 直调
        self.ctrl.performSelectorOnMainThread_withObject_waitUntilDone_ = (
            lambda sel, obj, wait: self.ctrl.applyDone_(obj))

    def tearDown(self):
        sections.config_path = self._real_path
        self.dir.cleanup()

    def cfg(self):
        return sections.load_config(self.path)

    def edit(self, key, target):
        """制造一次编辑（换区唯一入口），返回控制器。"""
        self.ctrl.applyMove_to_(key, target)
        return self.ctrl


class TestDraftOnly(PendingCase):
    def test_换区只改草稿不落盘(self):
        key = "b|B"
        self.edit(key, sections.SECTION_HIDDEN)
        self.assertIsNone(self.cfg()["sections"].get(key))   # 盘上没动
        self.assertEqual(self.ctrl._pending_cfg["sections"].get(key),
                         sections.SECTION_HIDDEN)            # 草稿动了
        self.assertEqual(self.reloaded, [])                  # 不刷面板（未生效）

    def test_拖拽落位只改草稿(self):
        self.ctrl.applyDrop_key_toSection_atIndex_(
            "a|A", sections.SECTION_HIDDEN, 0)
        self.assertIsNone(self.cfg()["sections"].get("a|A"))
        self.assertEqual(self.ctrl._pending_cfg["sections"].get("a|A"),
                         sections.SECTION_HIDDEN)

    def test_布局选项开关只改草稿(self):
        sw = types.SimpleNamespace(representedObject=lambda: "use_captured",
                                   state=lambda: 1)
        self.ctrl.onOptionSwitch_(sw)
        self.assertFalse(self.cfg().get("use_captured", False))
        self.assertTrue(self.ctrl._pending_cfg["use_captured"])

    def test_原地不动不产生草稿(self):
        self.edit("a|A", sections.SECTION_VISIBLE)
        self.assertIsNone(self.ctrl._pending_cfg)
        self.assertEqual(self.ctrl._undo, [])


class TestApply(PendingCase):
    def test_应用写盘并清草稿(self):
        self.edit("b|B", sections.SECTION_HIDDEN)
        self.ctrl.real_bar = False
        self.ctrl.onApplyLayout_(None)
        self.assertEqual(self.cfg()["sections"].get("b|B"), sections.SECTION_HIDDEN)
        self.assertIsNone(self.ctrl._pending_cfg)
        self.assertFalse(self.ctrl._applying)  # 同步链路里 applyDone 已收尾
        self.assertEqual(self.reloaded, [True])  # 生效后重盘点刷面板

    def test_real_bar开时应用只做CC静默同步(self):
        """real_bar 开：应用后台链路只调 sync_cc_now（打桩计数）。

        拖拽镜像（收纳区放出/顺序对齐）已按用户要求彻底停用（2026-11-24），
        应用流程不再碰任何鼠标控制。"""
        calls = []
        self.edit("b|B", sections.SECTION_HIDDEN)
        self.ctrl.real_bar = True
        self.ctrl.sync_cc_now = lambda: calls.append("cc") or {"writable": True}
        self.ctrl.onApplyLayout_(None)
        self.assertEqual(calls, ["cc"])  # 只剩静默 CC 同步
        self.assertEqual(self.cfg()["sections"].get("b|B"), sections.SECTION_HIDDEN)

    def test_real_bar关时应用不碰真实菜单栏(self):
        calls = []
        self.edit("b|B", sections.SECTION_HIDDEN)
        self.ctrl.real_bar = False
        self.ctrl.sync_cc_now = lambda: calls.append("cc")
        self.ctrl.onApplyLayout_(None)
        self.assertEqual(calls, [])  # 同步到真实菜单栏=关：只写盘

    def test_无草稿时应用是空操作(self):
        self.ctrl.real_bar = False
        before = self.cfg()
        self.ctrl.onApplyLayout_(None)
        self.assertEqual(self.cfg(), before)

    def test_关窗时未应用草稿自动应用(self):
        self.edit("b|B", sections.SECTION_HIDDEN)
        self.ctrl.real_bar = False
        self.ctrl.windowWillClose_(None)
        self.assertEqual(self.cfg()["sections"].get("b|B"), sections.SECTION_HIDDEN)

    def test_应用后撤销回滚成草稿再应用才落盘(self):
        self.edit("b|B", sections.SECTION_HIDDEN)
        self.ctrl.real_bar = False
        self.ctrl.onApplyLayout_(None)
        self.assertTrue(self.ctrl.onUndo())
        self.assertEqual(self.cfg()["sections"].get("b|B"),
                         sections.SECTION_HIDDEN)            # 盘上还是应用后的
        self.assertEqual(self.ctrl._pending_cfg["sections"].get("b|B"),
                         None)                               # 草稿回滚到应用前
        self.ctrl.real_bar = False
        self.ctrl.onApplyLayout_(None)
        self.assertIsNone(self.cfg()["sections"].get("b|B"))  # 再应用才真正回退


if __name__ == "__main__":
    unittest.main()
