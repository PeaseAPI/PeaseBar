#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实菜单栏镜像接线单测（Phase 10）。

只验证「设置里的编辑动作是否把对的 ⌘-拖原语调起来」这一层接缝：
- real_bar 关 → 一律不调；
- 移区：进弹窗/永久隐藏调 hide，回菜单栏显示调 reveal；
- 同区改序：只有「菜单栏显示」区调 reorder，其余区不动；
- 不可拖项（movable=False）→ 不调。

menubar_drag 的三个原语与 movable 全打桩成记录器，_resync_frames 打桩成空操作，
因此不碰真鼠标、不需要辅助功能/录屏权限。真实 ⌘-拖能否改系统菜单栏由
tmp/ 探针 + 本机截图取证，不在这里测。
"""
import types
import unittest

from peasebar import menubar_drag, sections
from peasebar import settings


def fake(bid="com.tencent.qq", label="QQ", key_part="", frame=(100.0, 0.0, 24.0, 24.0)):
    return types.SimpleNamespace(
        owner_bundle_id=bid, owner_app=label, label=label, role="AXMenuBarItem",
        frame=frame, notched=False, is_stash_button=False, stashed=False,
        key_part=key_part, el=object())


class _Rec:
    """把 menubar_drag 的三原语 + movable 换成记录器。"""

    def __init__(self, movable=True):
        self.calls = []
        self._movable = movable

    def __enter__(self):
        self._orig = (menubar_drag.hide, menubar_drag.reveal,
                      menubar_drag.reorder, menubar_drag.movable)
        menubar_drag.hide = lambda it: self.calls.append(("hide", it)) or True
        menubar_drag.reveal = lambda it: self.calls.append(("reveal", it)) or True
        menubar_drag.reorder = lambda s, d, after=True: (
            self.calls.append(("reorder", s, d, after)) or True)
        menubar_drag.movable = lambda it: self._movable
        return self

    def __exit__(self, *exc):
        (menubar_drag.hide, menubar_drag.reveal,
         menubar_drag.reorder, menubar_drag.movable) = self._orig

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

    def test_移到弹窗显示调hide(self):
        with _Rec() as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_HIDDEN)
        self.assertEqual(rec.names(), ["hide"])

    def test_移到永久隐藏也调hide(self):
        with _Rec() as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_ALWAYS_HIDDEN)
        self.assertEqual(rec.names(), ["hide"])

    def test_移回菜单栏显示调reveal(self):
        with _Rec() as rec:
            self.ctrl._mirror_section_move("com.tencent.qq|QQ", sections.SECTION_VISIBLE)
        self.assertEqual(rec.names(), ["reveal"])

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


if __name__ == "__main__":
    unittest.main()
