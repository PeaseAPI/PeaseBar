#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实菜单栏镜像接线单测（Phase 10，2026-11-24 鼠标停用后语义）。

验证「设置里的编辑动作到真实菜单栏这一层接缝」在新语义下的行为：
- real_bar 关 → 一律不调；
- 移区：只走 CC 静默通道（set_apps_allowed），**任何情况下都不再碰拖拽原语**
  （用户定调：合成 ⌘-拖会控制鼠标，已彻底停用）；
- CC 管不了/写失败 → 明确失败，不回退拖拽；
- 同区改序：镜像逻辑仍只对「菜单栏显示」区调 reorder（生产代码里
  movable 被总闸挡死→实为早退；_Rec 桩掉 movable 仅为钉住接线逻辑本身）。

menubar_drag 的三个原语与 movable、ccnative 的查态/写表全部打桩，
因此不碰真鼠标、不碰真 CC plist、不需要辅助功能/录屏权限。
"""
import types
import unittest

from peasebar import ccnative, menubar_drag, sections
from peasebar import panel, settings


def fake(bid="com.tencent.qq", label="QQ", key_part="", frame=(100.0, 0.0, 24.0, 24.0)):
    return types.SimpleNamespace(
        owner_bundle_id=bid, owner_app=label, label=label, role="AXMenuBarItem",
        frame=frame, notched=False, is_stash_button=False, stashed=False,
        key_part=key_part, el=object())


class _Rec:
    """把 menubar_drag 三原语 + movable、ccnative 查态/写表换成记录器。

    cc=None 模拟「CC 通道管不了」（is_app_hidden 恒 None）——新语义下
    上层应明确失败而**不是**回退拖拽；传 callable 则模拟 CC 可管，
    验证走 set_apps_allowed 且拖拽原语同样不被碰。
    """

    def __init__(self, movable=True, cc=None):
        self.calls = []
        self._movable = movable
        self._cc = cc

    def __enter__(self):
        self._orig = (menubar_drag.hide, menubar_drag.reveal,
                      menubar_drag.reorder, menubar_drag.movable,
                      ccnative.is_app_hidden, ccnative.set_apps_allowed,
                      ccnative.record_hidden)
        menubar_drag.hide = lambda it: self.calls.append(("hide", it)) or True
        menubar_drag.reveal = lambda it: self.calls.append(("reveal", it)) or True
        menubar_drag.reorder = lambda s, d, after=True: (
            self.calls.append(("reorder", s, d, after)) or True)
        menubar_drag.movable = lambda it: self._movable
        if self._cc is None:
            ccnative.is_app_hidden = lambda bid: None
        else:
            ccnative.is_app_hidden = self._cc
            ccnative.set_apps_allowed = (
                lambda bids, allowed:
                self.calls.append(("cc_set", tuple(bids), allowed)) or set(bids))
            ccnative.record_hidden = lambda bids: (
                self.calls.append(("cc_rec", tuple(sorted(bids)))))
        return self

    def __exit__(self, *exc):
        (menubar_drag.hide, menubar_drag.reveal,
         menubar_drag.reorder, menubar_drag.movable,
         ccnative.is_app_hidden, ccnative.set_apps_allowed,
         ccnative.record_hidden) = self._orig

    def names(self):
        return [c[0] for c in self.calls]


class TestWiring(unittest.TestCase):
    def setUp(self):
        self.ctrl = settings.SettingsController.alloc().init()
        self.ctrl.real_bar = True
        self.ctrl._resync_frames = lambda: None  # 别在离线里真去 list_items（会碰 AX）
        self.item = fake()
        self.ctrl.items = [self.item]

    def _only(self, rec, kind):
        return [c for c in rec.calls if c[0] == kind]

    def test_real_bar关闭时什么都不调(self):
        self.ctrl.real_bar = False
        with _Rec() as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_HIDDEN)
            self.ctrl._mirror_section_reorder(sections.SECTION_VISIBLE, "com.tencent.qq|QQ")
        self.assertEqual(rec.calls, [])

    def test_移到弹窗显示不触发拖拽(self):
        # 新语义：CC 管不了（cc=None）时明确失败，绝不回退到 hide 拖拽
        with _Rec() as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_HIDDEN)
        self.assertEqual(rec.calls, [])

    def test_移到永久隐藏不触发拖拽(self):
        with _Rec() as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_ALWAYS_HIDDEN)
        self.assertEqual(rec.calls, [])

    def test_移回菜单栏显示不触发拖拽(self):
        with _Rec() as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_VISIBLE)
        self.assertEqual(rec.calls, [])

    def test_不可拖项不动真实菜单栏(self):
        with _Rec(movable=False) as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_HIDDEN)
        self.assertEqual(rec.calls, [])  # hide 前先被 movable 拦下

    def test_可见区改序调reorder并带锚点(self):
        a = fake(bid="com.a", label="A", frame=(100.0, 0.0, 24.0, 24.0))
        b = fake(bid="com.b", label="B", frame=(130.0, 0.0, 24.0, 24.0))
        self.ctrl.items = [a, b]
        self.ctrl.buckets = {
            sections.SECTION_VISIBLE: [b, a],   # 目标：B 在前，A 在后
            sections.SECTION_HIDDEN: [],
            sections.SECTION_ALWAYS_HIDDEN: [],
        }
        with _Rec() as rec:
            self.ctrl._mirror_section_reorder(sections.SECTION_VISIBLE, "com.b|B")
        self.assertEqual(rec.names(), ["reorder"])
        _k, src, anchor, after = rec.calls[0]
        self.assertIs(src, b)
        # B 在 index0，无左邻 → 拿右邻 A 作锚，拖到其左（after=False）
        self.assertIs(anchor, a)
        self.assertFalse(after)

    def test_非可见区改序不碰真实菜单栏(self):
        self.ctrl.buckets = {
            sections.SECTION_VISIBLE: [],
            sections.SECTION_HIDDEN: [self.item],
            sections.SECTION_ALWAYS_HIDDEN: [],
        }
        with _Rec() as rec:
            self.ctrl._mirror_section_reorder(sections.SECTION_HIDDEN, "com.tencent.qq|QQ")
        self.assertEqual(rec.calls, [])


class TestCCPreferred(unittest.TestCase):
    """CC 通道优先：is_app_hidden 非 None 时走 set_apps_allowed，不碰拖拽原语。"""

    def setUp(self):
        self.ctrl = settings.SettingsController.alloc().init()
        self.ctrl.real_bar = True
        self.ctrl._resync_frames = lambda: None
        self.item = fake()
        self.ctrl.items = [self.item]

    def test_CC可管时隐藏走CC并记侧车(self):
        with _Rec(cc=lambda bid: False) as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_HIDDEN)
        self.assertEqual(rec.names(), ["cc_set", "cc_rec"])
        _k, bids, allowed = rec.calls[0]
        self.assertEqual(bids, ("com.tencent.qq",))
        self.assertIs(allowed, False)

    def test_CC已是隐藏态时幂等不动作(self):
        with _Rec(cc=lambda bid: True) as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_HIDDEN)
        self.assertEqual(rec.calls, [])

    def test_CC可管时显示走CC不拖拽(self):
        with _Rec(cc=lambda bid: False) as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_VISIBLE)
        self.assertEqual(rec.names(), ["cc_set"])
        self.assertIs(rec.calls[0][2], True)

    def test_CC失败时不回退拖拽hide(self):
        # set_apps_allowed 抛异常（如 TCC 拒绝写盘）→ except → 明确失败，不碰鼠标
        def boom(bids, allowed):
            raise PermissionError("Operation not permitted")
        with _Rec(cc=lambda bid: False) as rec:
            ccnative.set_apps_allowed = boom
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_HIDDEN)
        self.assertEqual(rec.calls, [])  # hide 拖拽原语不得被调

    def test_CC失败时不回退拖拽reveal(self):
        def boom(bids, allowed):
            raise PermissionError("Operation not permitted")
        with _Rec(cc=lambda bid: False) as rec:
            ccnative.set_apps_allowed = boom
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_VISIBLE)
        self.assertEqual(rec.calls, [])


class TestInputMenuSync(unittest.TestCase):
    """sync_cc_now 的输入法菜单通道：配置 hidden → visible=0；
    CC 通道不可用（is_writable=False）也照样管（通道各自独立，
    搜狗通道只写普通偏好域不依赖 CC plist 写权）。"""

    def setUp(self):
        self.ctrl = settings.SettingsController.alloc().init()
        self.calls = []
        self.cfg_sections = {}
        self._orig = (sections.load_config, ccnative.is_writable,
                      ccnative.set_input_menu_visible)
        sections.load_config = lambda: {"sections": self.cfg_sections}
        ccnative.is_writable = lambda: False  # CC 通道故意摆烂
        ccnative.set_input_menu_visible = (
            lambda show: self.calls.append(show) or True)
        self.addCleanup(self._restore)

    def _restore(self):
        (sections.load_config, ccnative.is_writable,
         ccnative.set_input_menu_visible) = self._orig

    def test_配置隐藏则关输入法菜单(self):
        """搜狗标到隐藏区：写 visible=0（CC 不可用也管）。"""
        self.cfg_sections = {"com.apple.TextInputMenuAgent|TextInputMenuAgent":
                             sections.SECTION_HIDDEN}
        out = self.ctrl.sync_cc_now()
        self.assertEqual(out.get("input_menu"), "hide")
        self.assertEqual(self.calls, [False])

    def test_配置显示则开输入法菜单(self):
        self.cfg_sections = {"com.apple.TextInputMenuAgent|TextInputMenuAgent":
                             sections.SECTION_VISIBLE}
        out = self.ctrl.sync_cc_now()
        self.assertEqual(out.get("input_menu"), "show")
        self.assertEqual(self.calls, [True])

    def test_用户没管就不动系统现状(self):
        """两区都没标输入法菜单：不写不重启（尊重系统默认与手动选择）。"""
        self.cfg_sections = {}
        out = self.ctrl.sync_cc_now()
        self.assertNotIn("input_menu", out)
        self.assertEqual(self.calls, [])


class TestTriggerConflictSync(unittest.TestCase):
    """sync_cc_now 全量对齐不得跟面板触发流程打架（2026-11-24 闪断真凶）。

    真机日志铁证：60s tick/启动同步撞进面板「显回→触发」窗口，把临时
    显回的 bid 硬收回——多闪一次栏还抽走菜单点击窗口；另 PeaseBar 自己
    配置标隐藏但 protected 永写不进，实效自检每轮空转点名它。
    修复：全程避开 panel._inflight，自检剔除 protected。"""

    def setUp(self):
        self.ctrl = settings.SettingsController.alloc().init()
        self.cfg = {"sections": {"com.acme.todesk|ToDesk": sections.SECTION_HIDDEN,
                                 "com.pease.peasebar|PeaseBar":
                                     sections.SECTION_HIDDEN}}
        self.set_calls = []   # set_apps_allowed(bids, allowed) 记录
        self.applied = []     # apply_now 触发记录
        self.online = []      # 模拟盘上栏内实况
        self._orig = (sections.load_config, ccnative.is_writable,
                      ccnative.last_hidden, ccnative.record_hidden,
                      ccnative.set_apps_allowed, ccnative.apply_now,
                      settings.inventory.list_items, settings.time)
        sections.load_config = lambda: self.cfg
        ccnative.is_writable = lambda: True
        ccnative.last_hidden = lambda: set()
        ccnative.record_hidden = lambda bids: None
        ccnative.set_apps_allowed = (
            lambda bids, allowed, hard=True:
            self.set_calls.append((frozenset(bids), allowed)) or set())
        ccnative.apply_now = lambda: self.applied.append(True)
        settings.inventory.list_items = lambda: (list(self.online), [])
        settings.time = types.SimpleNamespace(sleep=lambda _s: None)
        panel._inflight.clear()
        self.addCleanup(panel._inflight.clear)
        self.addCleanup(self._restore)

    def _restore(self):
        (sections.load_config, ccnative.is_writable,
         ccnative.last_hidden, ccnative.record_hidden,
         ccnative.set_apps_allowed, ccnative.apply_now,
         settings.inventory.list_items, settings.time) = self._orig

    def _hide_bids(self):
        # 第一次调用即收回写（out["hide"]）
        return self.set_calls[0][0]

    def test_inflight显回项不被同步硬收回(self):
        """todesk 在触发窗口里（inflight）：收回写不碰它，自检也不点名。"""
        self.online = [fake(bid="com.acme.todesk", label="ToDesk"),
                       fake(bid="com.pease.peasebar", label="PeaseBar")]
        panel._inflight.add("com.acme.todesk")
        out = self.ctrl.sync_cc_now()
        self.assertNotIn("com.acme.todesk", self._hide_bids())
        self.assertEqual(self.applied, [])       # 零强制重画：不闪
        self.assertNotIn("still_visible", out)

    def test_protected永不进实效自检空转(self):
        """peasebar 配置标隐藏但永远在线且写不进：自检不得点名它；
        真漂移的 todesk 照常收回（自检补漏硬 apply 是预期行为）。"""
        self.online = [fake(bid="com.acme.todesk", label="ToDesk"),
                       fake(bid="com.pease.peasebar", label="PeaseBar")]
        out = self.ctrl.sync_cc_now()
        self.assertEqual(out.get("still_visible"), ["com.acme.todesk"])
        self.assertEqual(len(self.applied), 1)   # 漂移项强制重画一次收回

    def test_无漂移时自检零动作(self):
        """栏上只剩 protected：幂等，不写不重画（钉住旧空转回归）。"""
        self.online = [fake(bid="com.pease.peasebar", label="PeaseBar")]
        out = self.ctrl.sync_cc_now()
        self.assertNotIn("still_visible", out)
        self.assertEqual(self.applied, [])


if __name__ == "__main__":
    unittest.main()
