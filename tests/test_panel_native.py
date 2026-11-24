#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板原生隐藏补格：native_hidden_items 的筛选规则（纯函数，离线单测）。

配置「弹窗显示」的图标被 isAllowed=false 藏掉后不进 AX 盘点，面板必须从
配置反推补格子，否则用户会看到「面板里没有、菜单栏也没有」的凭空消失。
不碰 AppKit 与真实 plist：ccnative 的两个读口打桩。
"""
import unittest
from unittest import mock
import types
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

    def _run(self, items, now_hidden, unman=()):
        """打桩 hidden_bids_now / last_hidden / unmanageable_set 后跑补格。"""
        with mock.patch.object(ccnative, "hidden_bids_now", return_value=set(now_hidden)), \
             mock.patch.object(ccnative, "last_hidden", return_value=[]), \
             mock.patch.object(ccnative, "unmanageable_set",
                               return_value=set(unman)):
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
                               return_value=["com.example.app"]), \
             mock.patch.object(ccnative, "unmanageable_set", return_value=set()):
            out = panel.native_hidden_items([], self.CFG)
        self.assertIn("com.example.app", {m.owner_bundle_id for m in out})
    
    def test_不可控项已被系统藏掉必须补进弹窗(self):
        """报障（2026-11-24 OneDrive/ToDesk/Synology）：名单里若有项其实
        已被系统藏掉（不在栏上），它就不再「不可控」，必须补回弹窗，否则
        「既不在栏上、又进不了弹窗」两头消失。旧代码无条件减名单正犯了这条。"""
        out = self._run([], {"com.example.app", "com.example.gone"},
                        unman={"com.example.gone"})
        # gone 虽在不可控名单，但此刻不在盘点（items=[]）→ 仍要补
        self.assertEqual({m.owner_bundle_id for m in out},
                         {"com.example.app", "com.example.gone"})

    def test_不可控项真在栏上不补伪项(self):
        """QQ 案例（2026-11-24）：系统藏不掉的 bid 真项就在盘点里，
        再补伪项就是「栏上有、格子却标成原生隐藏」的鬼影——靠 seen 实况去重挡掉。"""
        out = self._run([_seen_item("com.example.gone")],
                        {"com.example.app", "com.example.gone"},
                        unman={"com.example.gone"})
        self.assertEqual({m.owner_bundle_id for m in out}, {"com.example.app"})

    def test_伪项按配置order排序(self):
        """布局页拖完的顺序要立刻在面板生效（2026-11-25 用户反馈「顺序没变」的
        真根因：伪项原先按 sections 字典插入序输出，而拖动写的是 order）。"""
        cfg = {"sections": {"com.example.app|main": sections.SECTION_HIDDEN,
                            "com.example.gone|main": sections.SECTION_HIDDEN},
               "order": ["com.example.gone|main", "com.example.app|main"]}
        with mock.patch.object(ccnative, "hidden_bids_now",
                               return_value={"com.example.app", "com.example.gone"}), \
             mock.patch.object(ccnative, "last_hidden", return_value=[]), \
             mock.patch.object(ccnative, "unmanageable_set", return_value=set()):
            out = panel.native_hidden_items([], cfg)
        self.assertEqual([sections.item_key(m) for m in out],
                         ["com.example.gone|main", "com.example.app|main"])

    def test_伪项字段满足渲染与触发口径(self):
        """格子渲染要 label/key_part；触发链路要 owner_bundle_id/frame=None。"""
        out = self._run([], {"com.example.app"})
        m = out[0]
        self.assertEqual(sections.item_key(m), "com.example.app|main")
        self.assertIsNone(m.frame)  # capture.image_for_item 对 None frame 走兜底
        self.assertFalse(m.is_stash_button)
        self.assertGreater(len(m.owner_bundle_id.rsplit(".", 1)[-1]), 0)


class TestNativeTileClickGuards(unittest.TestCase):
    """点「原生隐藏」格的守门：不该闪菜单栏的情形绝不进显回链路
    （2026-11-24 用户报障：点格子菜单栏白闪两下、图标还不回去）。"""

    BID = "com.example.app"

    def _click(self, online, running, found=None):
        """同步跑 open_native_hidden_async，返回 (写盘调用, 触发项)。"""
        calls, trig = [], []
        # 假时钟：每次 time() 走 1s，保证空等循环能自然结束
        clock = {"t": 0.0}

        def _list_items():
            # 守门①先拿一次（看图标在不在栏上），进入显回后的轮询才拿 found
            _list_items.n += 1
            return (found or [], []) if _list_items.n > 1 else (online, [])

        _list_items.n = 0

        class _SyncThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()

        def _allowed(bids, allowed, hard=True):
            calls.append((tuple(bids), allowed, hard))
            return set(bids)

        with mock.patch.object(panel.inventory, "list_items", _list_items), \
             mock.patch.object(panel, "_app_running", return_value=running), \
             mock.patch.object(panel.ccnative, "set_apps_allowed", _allowed), \
             mock.patch.object(panel.ccnative, "schedule_hard_apply",
                               lambda *a: calls.append(("兜底",))), \
             mock.patch.object(panel.trigger, "open_item",
                               side_effect=lambda m: (trig.append(m),
                                                      ("AXPress", True))[1]), \
             mock.patch.object(panel.threading, "Thread", _SyncThread), \
             mock.patch.object(panel, "time", types.SimpleNamespace(
                 sleep=lambda _s: None,
                 time=lambda: clock.__setitem__("t", clock["t"] + 1.0)
                 or clock["t"])):
            panel.open_native_hidden_async(self.BID)
        return calls, trig

    def test_图标就在栏上时直接触发零闪断(self):
        """不可控名单/快照过期：真项就在盘点里 → 不碰 plist、不重启 Agent。"""
        calls, trig = self._click([_seen_item(self.BID)], running=True)
        self.assertEqual(calls, [])            # 零写盘 = 零闪断
        self.assertEqual(len(trig), 1)          # 但图标照样能触发

    def test_App没在跑时不白闪(self):
        """显回变不出不存在的图标（实测空等 8s）：直接告知，零写盘。"""
        calls, trig = self._click([], running=False)
        self.assertEqual(calls, [])
        self.assertEqual(trig, [])

    def test_真藏着的显回与收回都是硬生效(self):
        """只有这种才付闪断：显回 hard，收回也 hard（图标当场回去，
        不再软写赖到 15s 兜底），也不另排兜底定时器。"""
        calls, trig = self._click([], running=True,
                                  found=[_seen_item(self.BID)])
        self.assertEqual([(c[1], c[2]) for c in calls],
                         [(True, True), (False, True)])
        self.assertNotIn(("兜底",), calls)
        self.assertEqual(len(trig), 1)


if __name__ == "__main__":
    unittest.main()
