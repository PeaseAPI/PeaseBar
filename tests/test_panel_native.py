#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板原生隐藏补格：native_hidden_items 的筛选规则（纯函数，离线单测）。

配置「弹窗显示」的图标被 isAllowed=false 藏掉后不进 AX 盘点，面板必须从
配置反推补格子，否则用户会看到「面板里没有、菜单栏也没有」的凭空消失。
不碰 AppKit 与真实 plist：ccnative 的两个读口打桩。
"""
import unittest
from unittest import mock
from types import SimpleNamespace

from peasebar import ccnative, panel, sections


def _seen_item(bid):
    """盘点里出现的真项（最小字段集，panel._collect 口径）。"""
    return SimpleNamespace(owner_bundle_id=bid, label="x", key_part="x",
                           owner_app="x", owner_pid=1, stashed=False,
                           notched=False, frame=None, el=None,
                           is_stash_button=False)


class TestNativeHiddenItems(unittest.TestCase):
    CFG = {"sections": {
        "com.example.app|main": sections.SECTION_HIDDEN,
        "com.example.app|extra": sections.SECTION_HIDDEN,
        "com.example.gone|main": sections.SECTION_HIDDEN,
        "com.example.live|main": sections.SECTION_ALWAYS_HIDDEN,
        "com.apple.something|main": sections.SECTION_HIDDEN,
        "com.example.visible|main": sections.SECTION_HIDDEN,
    }}

    def _run(self, items, now_hidden):
        """打桩 hidden_bids_now / last_hidden 后跑 native_hidden_items。"""
        with mock.patch.object(ccnative, "hidden_bids_now", return_value=set(now_hidden)), \
             mock.patch.object(ccnative, "last_hidden", return_value=[]):
            return panel.native_hidden_items(items, self.CFG)

    def test_盘点里没有的配置隐藏项被补进面板(self):
        """原生藏起的 App（不在盘点、isAllowed=false）必须出现在面板格子集里。"""
        out = self._run([], {"com.example.app", "com.example.gone"})
        self.assertEqual({m.owner_bundle_id for m in out},
                         {"com.example.app", "com.example.gone"})
        # 伪项自述：点击分流与 tooltip 靠它
        self.assertTrue(all(m.native_hidden for m in out))
        # 同 App 多图标（同 bid 多配置键）各占一格
        self.assertEqual([m.label for m in out if m.owner_bundle_id
                          == "com.example.app"], ["main", "extra"])

    def test_还在盘点里的不补(self):
        """仍画在栏上（⌘-拖回退路径下的 stashed 项）由面板旧逻辑管，不重复补。"""
        out = self._run([_seen_item("com.example.visible")],
                        {"com.example.app", "com.example.gone"})
        self.assertNotIn("com.example.visible", {m.owner_bundle_id for m in out})

    def test_受保护与未藏的不补(self):
        """PeaseBar 自己/com.apple.* 永不触碰；没被藏的（App 没在跑等）无事可做。"""
        out = self._run([], {"com.example.app", "com.example.gone"})
        self.assertNotIn("com.apple.something", {m.owner_bundle_id for m in out})
        self.assertNotIn("com.example.live", {m.owner_bundle_id for m in out})

    def test_侧车记录也算隐藏证据(self):
        """reconcile 中途崩溃没来得及写 isAllowed 时，侧车记录兜底识别。"""
        with mock.patch.object(ccnative, "hidden_bids_now", return_value=set()), \
             mock.patch.object(ccnative, "last_hidden",
                               return_value=["com.example.app"]):
            out = panel.native_hidden_items([], self.CFG)
        self.assertIn("com.example.app", {m.owner_bundle_id for m in out})

    def test_伪项字段满足渲染与触发口径(self):
        """格子渲染要 label/key_part；触发链路要 owner_bundle_id/frame=None。"""
        out = self._run([], {"com.example.app"})
        m = out[0]
        self.assertEqual(sections.item_key(m), "com.example.app|main")
        self.assertIsNone(m.frame)  # capture.image_for_item 对 None frame 走兜底
        self.assertFalse(m.is_stash_button)
        self.assertGreater(len(m.owner_bundle_id.rsplit(".", 1)[-1]), 0)


if __name__ == "__main__":
    unittest.main()
