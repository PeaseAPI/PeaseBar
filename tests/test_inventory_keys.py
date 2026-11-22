#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inventory 纯逻辑单测：稳定键消歧（同 App 双图标）。

运行：项目根目录下 `python3 -m unittest discover -s tests -t .`
只吃 MenuItem 数据类，不碰 AX/屏幕（inventory 模块导入需要 pyobjc，本机已具备）。
"""
import unittest

try:
    from peasebar import inventory
except Exception:  # pragma: no cover - 无 pyobjc 环境直接跳过整文件
    inventory = None


def mk(bid, key_part="", label="L", frame=(0, 0, 24, 24), stash=False):
    return inventory.MenuItem(owner_app="A", owner_bundle_id=bid, owner_pid=1,
                              label=label, role="AXButton", frame=frame,
                              is_stash_button=stash, key_part=key_part)


@unittest.skipIf(inventory is None, "pyobjc 不可用")
class TestDedupKeys(unittest.TestCase):
    def test_同身份双图标加序号(self):
        # 托管树里同 pid/同 AXIdentifier，不分序号则分区设置与位图缓存只能记住第一枚（T55）
        a, b = mk("com.x", "com.x.icon"), mk("com.x", "com.x.icon")
        inventory._dedup_keys([a, b])
        self.assertEqual((a.key_part, b.key_part), ("com.x.icon", "com.x.icon#2"))

    def test_不同身份互不影响(self):
        a, b = mk("com.x", "com.x.one"), mk("com.x", "com.x.two")
        inventory._dedup_keys([a, b])
        self.assertEqual((a.key_part, b.key_part), ("com.x.one", "com.x.two"))

    def test_收纳按钮不参与编号(self):
        btn = mk("com.apple.MenuBarAgent", label="显示隐藏菜单栏项目", stash=True)
        it = mk("com.apple.MenuBarAgent", key_part="com.apple.menuextra.clock")
        inventory._dedup_keys([btn, it])
        self.assertEqual(it.key_part, "com.apple.menuextra.clock")

    def test_无_key_part时用_label_分(self):
        a, b = mk("com.y", "", label="微信"), mk("com.y", "", label="微信")
        inventory._dedup_keys([a, b])
        self.assertEqual((a.key_part, b.key_part), ("", "微信#2"))


if __name__ == "__main__":
    unittest.main()
