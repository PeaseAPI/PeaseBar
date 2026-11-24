#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""i18n 框架与词条表回归（2026-11-24 多语言交付）。

覆盖：六语言键集对齐、占位符一致、回退链（缺键→zh-Hans→键名）、
语言读写（set_lang 写盘 + 缓存失效）、非法值回默认。
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from peasebar import i18n  # noqa: E402

LANGS = [k for k, _n in i18n.LANGS]
PLACEHOLDER = re.compile(r"\{(\w+)\}")


class TestStringsTable(unittest.TestCase):
    def test_six_languages_present(self):
        self.assertEqual(LANGS, ["zh-Hans", "zh-Hant", "en", "ru", "fr", "de"])
        for lang in LANGS:
            self.assertIn(lang, i18n._STRINGS)

    def test_key_sets_identical(self):
        """任何语言缺键/多键都算失败（回退机制允许临时缺译，但交付时必须齐）。"""
        base = set(i18n._STRINGS[i18n.DEFAULT])
        self.assertTrue(base, "zh-Hans 原典表不能为空")
        for lang in LANGS:
            got = set(i18n._STRINGS[lang])
            self.assertEqual(got, base,
                             f"{lang} 与 zh-Hans 键集不一致：缺 {base - got}，多 {got - base}")

    def test_placeholders_match(self):
        """占位符必须跟 zh-Hans 原典一致，否则 t(**kw) 会静默 format 失败。"""
        for lang in LANGS:
            for key, s in i18n._STRINGS[lang].items():
                want = set(PLACEHOLDER.findall(i18n._STRINGS[i18n.DEFAULT][key]))
                got = set(PLACEHOLDER.findall(s))
                self.assertEqual(got, want, f"{lang}/{key} 占位符不一致：{got} != {want}")

    def test_no_empty_value(self):
        for lang in LANGS:
            for key, s in i18n._STRINGS[lang].items():
                self.assertTrue(s.strip(), f"{lang}/{key} 是空串")


class TestLookup(unittest.TestCase):
    def setUp(self):
        # 词条查找测试不碰真配置：把语言缓存钉在 zh-Hans
        self._saved = i18n._lang
        i18n._lang = "zh-Hans"

    def tearDown(self):
        i18n._lang = self._saved

    def test_fallback_to_default_table(self):
        """当前语言缺键回 zh-Hans 原典：临时删 en 的键验证，测完还原。"""
        i18n._lang = "en"
        saved_en = i18n._STRINGS["en"].pop("layout.apply")
        try:
            self.assertEqual(i18n.t("layout.apply"),
                             i18n._STRINGS["zh-Hans"]["layout.apply"])
        finally:
            i18n._STRINGS["en"]["layout.apply"] = saved_en

    def test_missing_key_returns_keyname(self):
        self.assertEqual(i18n.t("no.such.key"), "no.such.key")

    def test_format_placeholders(self):
        self.assertEqual(i18n.t("layout.count", sec="X", n=3),
                         i18n._STRINGS["zh-Hans"]["layout.count"].format(sec="X", n=3))

    def test_literal_braces_safe(self):
        """文案含字面花括号而调用没传 kw 时不应抛（format 失败原样返回）。"""
        i18n._STRINGS["zh-Hans"]["__tmp__"] = "字面 {oops} 花括号"
        try:
            self.assertIn("{oops}", i18n.t("__tmp__"))
        finally:
            del i18n._STRINGS["zh-Hans"]["__tmp__"]

    def test_lang_names_order(self):
        names = i18n.lang_names()
        self.assertEqual([k for k, _ in names], LANGS)
        # 显示名用各语言自称（不随界面语言翻译）
        self.assertEqual(dict(names)["zh-Hans"], "简体中文")
        self.assertEqual(dict(names)["de"], "Deutsch")


class TestSetLang(unittest.TestCase):
    def test_set_and_read_back(self):
        """set_lang 写盘 + 失效缓存；current_lang 从盘上读回。"""
        from peasebar import sections
        tmpdir = tempfile.mkdtemp()
        cfg_path = os.path.join(tmpdir, "config.json")
        saved = sections.config_path
        sections.config_path = lambda: cfg_path  # 函数打桩，不碰真实配置
        self._saved = i18n._lang
        try:
            self.assertTrue(i18n.set_lang("ru"))
            i18n.reset_cache()
            self.assertEqual(i18n.current_lang(), "ru")
            # 非法语言拒绝写入，盘上仍是 ru
            self.assertFalse(i18n.set_lang("xx"))
            # 盘上值非法时回默认
            cfg = sections.load_config()
            cfg["lang"] = "kl-INGON"
            sections.save_config(cfg)
            i18n.reset_cache()
            self.assertEqual(i18n.current_lang(), i18n.DEFAULT)
        finally:
            sections.config_path = saved
            i18n._lang = self._saved


if __name__ == "__main__":
    unittest.main()
