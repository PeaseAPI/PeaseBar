#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trigger.open_item 的档位顺序（2026-11-25 报障「弹窗里右键图标没反应」配套）。

prefer_menu 只改一件事：AXShowMenu（若元素支持）排到 AXPress 前面。
axutil 全桩：不发真 AX、不等真窗口，只记录投递顺序。
"""
import unittest
from unittest import mock
from types import SimpleNamespace

from peasebar import trigger


def _item(actions, frame=None, stashed=False):
    return SimpleNamespace(el=object(), owner_pid=42, frame=frame,
                           stashed=stashed)


class TestLadderOrder(unittest.TestCase):
    def _run(self, actions, prefer_menu, opens_on=None):
        """跑一次 open_item，返回 perform_action 的投递顺序。

        opens_on：第几个动作"看到新窗口"（None=都没有），用它验证早停。
        """
        tried = []

        def _perform(el, act):
            tried.append(act)
            return 0

        with mock.patch.object(trigger.axutil, "set_messaging_timeout",
                               lambda *a: None), \
             mock.patch.object(trigger.axutil, "element_actions",
                               lambda el: actions), \
             mock.patch.object(trigger.axutil, "perform_action", _perform), \
             mock.patch.object(trigger, "_snapshot", lambda: {}), \
             mock.patch.object(trigger, "_wait_open",
                               lambda base, pid, settle=None:
                               ["win"] if len(tried) == opens_on else []):
            trigger.open_item(_item(actions), prefer_menu=prefer_menu)
        return tried

    def test_左键默认AXPress先行(self):
        tried = self._run(["AXPress", "AXShowMenu"], prefer_menu=False)
        self.assertEqual(tried, ["AXPress", "AXShowMenu"])

    def test_右键支持AXShowMenu时先行(self):
        tried = self._run(["AXPress", "AXShowMenu"], prefer_menu=True)
        self.assertEqual(tried, ["AXShowMenu", "AXPress"])

    def test_托管按钮没有AXShowMenu就只投AXPress(self):
        """T52/T54：托管第三方按钮只 advertise AXPress——右键也没得选，
        但不能因此报错或空投。"""
        for pm in (False, True):
            tried = self._run(["AXPress"], prefer_menu=pm)
            self.assertEqual(tried, ["AXPress"])

    def test_首个动作开窗即早停(self):
        """判据永远是「有没有新窗口」：第一个就成了就不试第二个。"""
        tried = self._run(["AXPress", "AXShowMenu"], prefer_menu=True,
                          opens_on=1)
        self.assertEqual(tried, ["AXShowMenu"])

    def test_异步入口透传prefer_menu(self):
        """open_item_async 的后台线程要把右键语义带到 open_item。"""
        seen = []

        class _SyncThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()

        it = _item(["AXPress"])
        with mock.patch.object(trigger.threading, "Thread", _SyncThread), \
             mock.patch.object(trigger, "open_item",
                               side_effect=lambda m, prefer_menu=False:
                               (seen.append(prefer_menu), ("how", False))[1]):
            trigger.open_item_async(it, None, prefer_menu=True)
        self.assertEqual(seen, [True])


if __name__ == "__main__":
    unittest.main()
