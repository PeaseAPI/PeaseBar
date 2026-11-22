# -*- coding: utf-8 -*-
"""设置页「挤不下 / 够不着」提示行（Phase 4a，照 Thaw 把这类信息放设置页，T72）。

只测纯逻辑：文案计数、行数为 0 时不占高度、提示里不出现任何图标名字（用户定调「只显示图标」）。
渲染与真机一致性由 tmp/t_p4.py 的 P61/P62/P63 取证。
"""
import unittest

from peasebar import settings

# 默认取图构成：能截到真像素（不往提示行里掺「菜单栏没画出来」那条）。
# 不拿 capture.last_stats 的现值做默认——那个模块状态会被 test_capture 的用例改写，
# 用例之间因此串味。
LIVE = {"cropped": 16, "fallback": 9, "permission": True, "bar_drawn": True}


def controller(stashed=0, notched=0, stats=None):
    ctrl = settings.SettingsController.alloc().init()
    ctrl.stashed_count = stashed
    ctrl.notched_count = notched
    ctrl.stats = dict(stats or LIVE)
    return ctrl


class TestHints(unittest.TestCase):
    def test_no_hint_when_everything_fits(self):
        """挤得下也没遮挡 → 一行都不给，别在设置页里制造噪音。"""
        self.assertEqual(controller(0, 0)._hints(), [])

    def test_stashed_hint_carries_count(self):
        hints = controller(9, 0)._hints()
        self.assertEqual(len(hints), 1)
        self.assertIn("9 项被系统收纳", hints[0])
        self.assertIn("展开收纳区", hints[0])   # 必须给操作指引，不能只报问题

    def test_notched_hint_separate_line(self):
        hints = controller(3, 2)._hints()
        self.assertEqual(len(hints), 2)
        self.assertTrue(any("3 项被系统收纳" in h for h in hints))
        self.assertTrue(any("2 项被刘海遮挡" in h for h in hints))

    def test_hints_never_carry_names(self):
        """提示行只有计数与指引，绝不列名字——名字只允许出现在「已选：」行。"""
        for n in (0, 1, 7):
            for h in controller(n, n)._hints():
                for name in ("微信", "OneDrive", "com.", "TG Pro"):
                    self.assertNotIn(name, h)


class TestBarNotDrawnHint(unittest.TestCase):
    """有权限但一张真像素都没截到（菜单栏被全屏 App 遮住）也要说清楚（T76）。"""

    DEAD = {"cropped": 0, "fallback": 25, "permission": True, "bar_drawn": False}

    def test_全兜底时给一条说明(self):
        hints = controller(0, 0, self.DEAD)._hints()
        self.assertEqual(len(hints), 1)
        self.assertIn("菜单栏当前没画出图标", hints[0])
        self.assertIn("重新抓取图标", hints[0])  # 必须给恢复动作，不能只报现象

    def test_截到真像素就不啰嗦(self):
        self.assertEqual(controller(0, 0, LIVE)._hints(), [])

    def test_缺权限时不重复说(self):
        """缺权限时红色提醒在「疑难解答」页，布局页提示行不叠第三条。"""
        no_perm = {"cropped": 0, "fallback": 25, "permission": False, "bar_drawn": False}
        self.assertEqual(controller(0, 0, no_perm)._hints(), [])

    def test_这条也不带名字(self):
        for h in controller(3, 2, self.DEAD)._hints():
            for name in ("微信", "OneDrive", "com.", "TG Pro"):
                self.assertNotIn(name, h)


class TestHintHeight(unittest.TestCase):
    def _height(self, ctrl, stashed, notched):
        ctrl.stashed_count = stashed
        ctrl.notched_count = notched
        ctrl.stats = dict(LIVE)  # 只算「挤不下/够不着」的行数，不掺遮挡提示
        return ctrl._page_height("layout", {sec: [] for sec in settings._SECTION_ORDER})

    def test_each_hint_costs_one_row(self):
        """提示行必须按行占高度：不占就会把底部按钮裁掉，占多了会留大片空白。"""
        ctrl = settings.SettingsController.alloc().init()
        ctrl.no_permission = False
        base = self._height(ctrl, 0, 0)
        one = self._height(ctrl, 3, 0)
        two = self._height(ctrl, 3, 2)
        self.assertEqual(one - base, settings.ROW_H + 8)
        self.assertEqual(two - base, 2 * (settings.ROW_H + 8))


if __name__ == "__main__":
    unittest.main()
