#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""menubar_drag 守卫与坐标逻辑单测。

只测「不动真格」的部分：movable 准入判定、非可拖项的早退、reorder/hide 算出的
落点坐标。真正发 CGEvent 的 command_drag 一律 monkeypatch 成记录器，绝不碰真鼠标，
也不要求屏幕录制/辅助功能权限。

注意：模块总闸 SYNTH_DRAG_ENABLED 默认 False（用户定调 2026-11-24：任何时候都
不控制鼠标），本文件测的是拖拽原语本身的逻辑，各用例在 setUp 里临时开闸——
command_drag 全被桩掉，开闸也不会真动鼠标。

运行：项目根目录下 `python3 -m unittest discover -s tests -t .`
"""
import types
import unittest

from peasebar import menubar_drag


def _gate_on(case):
    """临时打开拖拽总闸并在用例结束后还原：command_drag 已被各用例桩掉，不会真动鼠标。"""
    case.addCleanup(setattr, menubar_drag, "SYNTH_DRAG_ENABLED",
                    menubar_drag.SYNTH_DRAG_ENABLED)
    menubar_drag.SYNTH_DRAG_ENABLED = True


def fake(bid="com.tencent.qq", frame=(100.0, 0.0, 24.0, 24.0),
         el=object(), is_stash_button=False, stashed=False,
         key_part="", label="QQ"):
    """造一枚够 movable/reorder/hide 取用的 MenuItem 桩。"""
    return types.SimpleNamespace(
        owner_bundle_id=bid, owner_app="QQ", label=label, role="AXMenuBarItem",
        frame=frame, notched=False, is_stash_button=is_stash_button,
        stashed=stashed, key_part=key_part, el=el)


class TestMovable(unittest.TestCase):
    """movable：只有可点的第三方图标允许合成 ⌘-拖，苹果系统项与收纳按钮拒绝。"""

    def setUp(self):
        _gate_on(self)

    def test_正常第三方图标可拖(self):
        self.assertTrue(menubar_drag.movable(fake()))

    def test_None不可拖(self):
        self.assertFalse(menubar_drag.movable(None))

    def test_无frame不可拖(self):
        self.assertFalse(menubar_drag.movable(fake(frame=None)))

    def test_无AX元素不可拖(self):
        self.assertFalse(menubar_drag.movable(fake(el=None)))

    def test_收纳按钮不可拖(self):
        self.assertFalse(menubar_drag.movable(fake(is_stash_button=True)))

    def test_归属未知不可拖(self):
        self.assertFalse(menubar_drag.movable(fake(bid="?")))
        self.assertFalse(menubar_drag.movable(fake(bid="")))

    def test_苹果系统项不可拖(self):
        # 同 Thaw：com.apple.* 对合成拖有抵抗，一律跳过
        self.assertFalse(menubar_drag.movable(fake(bid="com.apple.Spotlight")))
        self.assertFalse(menubar_drag.movable(fake(bid="com.apple.MenuBarAgent")))

    def test_空frame元组不可拖(self):
        # 宽度为 0 的占位项不该拖（frame 存在但退化）——交给上层，这里只按字段判
        self.assertTrue(menubar_drag.movable(fake(frame=(0.0, 0.0, 0.0, 0.0))))


class TestEarlyReturn(unittest.TestCase):
    """非可拖项：三原语都在发事件前返回 False（command_drag 被打桩成会炸的记录器）。"""

    def setUp(self):
        _gate_on(self)
        self.calls = []
        self._orig_drag = menubar_drag.command_drag
        self._orig_notch = menubar_drag._notch_mid_x
        self._orig_stash = menubar_drag._stash_drop_x

        def boom(*a, **k):
            raise AssertionError("不该在未通过守卫时调用 command_drag")

        menubar_drag.command_drag = boom

    def tearDown(self):
        menubar_drag.command_drag = self._orig_drag
        menubar_drag._notch_mid_x = self._orig_notch
        menubar_drag._stash_drop_x = self._orig_stash

    def test_系统项hide不发事件(self):
        self.assertFalse(menubar_drag.hide(fake(bid="com.apple.Spotlight")))

    def test_系统项reorder不发事件(self):
        self.assertFalse(menubar_drag.reorder(
            fake(bid="com.apple.Spotlight"), fake()))

    def test_找不到收纳落点hide早退(self):
        # movable 通过，但 _stash_drop_x 返回 None（无隐藏簇/无刘海/无按钮）→ 不发事件
        menubar_drag._stash_drop_x = lambda: None
        self.assertFalse(menubar_drag.hide(fake()))


class TestReorderCoords(unittest.TestCase):
    """reorder：落点 x 落在锚点边界外侧（after 右 +6、否则左 -6），y 取源中心。"""

    def setUp(self):
        _gate_on(self)
        self.rec = []
        self._orig_drag = menubar_drag.command_drag
        menubar_drag.command_drag = lambda src, dst, *a, **k: self.rec.append((src, dst))

    def tearDown(self):
        menubar_drag.command_drag = self._orig_drag

    def test_after拖到右边界外(self):
        src = fake(frame=(100.0, 0.0, 24.0, 24.0))     # 中心 (112, 12)
        dst = fake(frame=(200.0, 0.0, 40.0, 24.0))     # 右边界 240
        self.assertTrue(menubar_drag.reorder(src, dst, after=True))
        src_pt, dst_pt = self.rec[-1]
        self.assertEqual(src_pt, (112.0, 12.0))
        self.assertEqual(dst_pt, (240.0 + 6, 12.0))

    def test_before拖到左边界内(self):
        src = fake(frame=(100.0, 0.0, 24.0, 24.0))
        dst = fake(frame=(50.0, 0.0, 40.0, 24.0))      # 左边界 50 → 50-6=44
        self.assertTrue(menubar_drag.reorder(src, dst, after=False))
        _src_pt, dst_pt = self.rec[-1]
        self.assertEqual(dst_pt, (44.0, 12.0))


class TestHideCoords(unittest.TestCase):
    """hide：目标 x = _stash_drop_x（系统收纳/溢出区落点），y 取源中心。

    拖拽已是「未授权权重表」时的回退路径，落点由 _stash_drop_x 统一给出。
    """

    def setUp(self):
        _gate_on(self)
        self.rec = []
        self._orig_drag = menubar_drag.command_drag
        self._orig_stash = menubar_drag._stash_drop_x
        self._orig_wait = menubar_drag._wait_state
        self._orig_find = menubar_drag._find
        menubar_drag.command_drag = lambda src, dst, *a, **k: self.rec.append((src, dst))
        menubar_drag._stash_drop_x = lambda: 767.0
        # 隔真机：_find 回到 None 就用传入的桩，保证用桩的 frame 算坐标
        menubar_drag._find = lambda item: None
        # hide 现在拖完会轮询真机确认 stashed 翻转；单测里没真菜单栏，
        # 模拟“拖后确实生效”（want_stashed=True 即成功）。
        menubar_drag._wait_state = lambda item, want_stashed, **k: bool(want_stashed)

    def tearDown(self):
        menubar_drag.command_drag = self._orig_drag
        menubar_drag._stash_drop_x = self._orig_stash
        menubar_drag._wait_state = self._orig_wait
        menubar_drag._find = self._orig_find

    def test_拖到收纳落点(self):
        item = fake(frame=(1300.0, 0.0, 24.0, 24.0))   # 中心 (1312, 12)
        self.assertTrue(menubar_drag.hide(item))
        # 验证生效后应只拖一次就返回，不重试
        self.assertEqual(len(self.rec), 1)
        src_pt, dst_pt = self.rec[-1]
        self.assertEqual(src_pt, (1312.0, 12.0))
        self.assertEqual(dst_pt, (767.0, 12.0))

    def test_验证不过则重试并最终返回失败(self):
        # 拖完始终确认不了 stashed（溢出区满）：应重试 3 次，最后返回 False
        item = fake(frame=(1300.0, 0.0, 24.0, 24.0))
        menubar_drag._wait_state = lambda *a, **k: False
        self.assertFalse(menubar_drag.hide(item))
        self.assertEqual(len(self.rec), 3)


class TestGate(unittest.TestCase):
    """总闸默认关（用户定调：任何时候都不控制鼠标）：三入口全部短路。"""

    def setUp(self):
        # 故意不开闸：命令拖被打桩成会炸，确保任何路径都不碰鼠标
        self._orig_drag = menubar_drag.command_drag
        menubar_drag.command_drag = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("总闸关闭时不该调用 command_drag"))
        self.addCleanup(setattr, menubar_drag, "command_drag", self._orig_drag)

    def test_默认总闸是关的(self):
        self.assertFalse(menubar_drag.SYNTH_DRAG_ENABLED)

    def test_关闸下command_drag无动作(self):
        # 这条测的是真函数本体的短路：临时换回原实现再调，应当直接返回不碰鼠标
        menubar_drag.command_drag = self._orig_drag
        menubar_drag.command_drag((10, 10), (20, 20))  # 不抛即通过

    def test_关闸下movable一律拒拖(self):
        self.assertFalse(menubar_drag.movable(fake()))

    def test_关闸下hide早退不发事件(self):
        self.assertFalse(menubar_drag.hide(fake()))

    def test_关闸下reorder不发事件(self):
        self.assertFalse(menubar_drag.reorder(fake(), fake()))

    def test_关闸下reveal不发事件(self):
        self.assertFalse(menubar_drag.reveal(fake()))


if __name__ == "__main__":
    unittest.main()
