#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分区模型（F4）：可见 / 隐藏 / 永久隐藏 三区 + JSON 持久化。

- 配置键 = bundleId + "|" + 图标名（label）。同一 App 双图标的序号消歧放 Phase 3；
- 不在配置中的图标一律归「可见区」（默认区），配置文件只记非默认区，保持精简；
- v1 的「隐藏」只是面板分区（图标本身仍在菜单栏），真正的隐藏联动（原生收纳写入）
  在 F12；分区价值：把救援重点图标分组标记，配合 F12 后即为「藏起来但可找回」；
- 纯逻辑函数（item_key/section_of/set_section/plan_sections）不依赖 AppKit，可离线单测
  （tests/test_sections.py），item 只要求 owner_bundle_id/label 两个属性（鸭子类型）；
- 持久化：~/Library/Application Support/PeaseBar/config.json，原子写（tmp + os.replace）；
  文件同时承载面板行为配置（panel_timeout 秒，0=不超时，默认 8，F5）。
"""
import json
import os

SECTION_VISIBLE = "visible"
SECTION_HIDDEN = "hidden"
SECTION_ALWAYS_HIDDEN = "always_hidden"

SECTION_LABELS = {
    SECTION_VISIBLE: "可见区",
    SECTION_HIDDEN: "隐藏区",
    SECTION_ALWAYS_HIDDEN: "永久隐藏",
}

DEFAULT_CONFIG = {"sections": {}, "panel_timeout": 8}


def config_path():
    return os.path.expanduser("~/Library/Application Support/PeaseBar/config.json")


def load_config(path=None):
    """读配置；无文件/损坏/字段非法时回默认（不抛异常，面板首启零依赖）。"""
    cfg = dict(DEFAULT_CONFIG, sections={})
    path = path or config_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    raw_sections = data.get("sections")
    if isinstance(raw_sections, dict):
        # 只接受合法分区值，脏数据直接丢弃
        cfg["sections"] = {
            str(k): str(v) for k, v in raw_sections.items()
            if v in (SECTION_HIDDEN, SECTION_ALWAYS_HIDDEN)
        }
    timeout = data.get("panel_timeout")
    if isinstance(timeout, (int, float)) and timeout >= 0:
        cfg["panel_timeout"] = timeout
    return cfg


def save_config(cfg, path=None):
    """原子写配置：先写 .tmp 再 os.replace，避免半截文件。"""
    path = path or config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def item_key(item):
    """配置键：bundleId|稳定名。

    优先用 item.key_part（inventory 给的不是图标名而是 AXIdentifier / 应名，
    因为图标名常常是温度/未读数这种会变的活文本，T55）；
    没有则退回 label（纯逻辑单测里的鸭子类型项只有 owner_bundle_id/label）。
    """
    part = getattr(item, "key_part", "") or item.label
    return f"{item.owner_bundle_id}|{part}"


def section_of(cfg, key):
    """查图标所在区；无记录 = 可见区。"""
    s = cfg["sections"].get(key)
    return s if s in (SECTION_HIDDEN, SECTION_ALWAYS_HIDDEN) else SECTION_VISIBLE


def set_section(cfg, key, section):
    """把图标移到某区；visible=回默认区（删键，配置文件只存非默认区）。"""
    if section == SECTION_VISIBLE:
        cfg["sections"].pop(key, None)
    elif section in (SECTION_HIDDEN, SECTION_ALWAYS_HIDDEN):
        cfg["sections"][key] = section


def plan_sections(items, cfg):
    """按三区分桶（纯函数）。返回 dict[区名] → [item]，桶内保持传入顺序。"""
    buckets = {s: [] for s in (SECTION_VISIBLE, SECTION_HIDDEN, SECTION_ALWAYS_HIDDEN)}
    for it in items:
        buckets[section_of(cfg, item_key(it))].append(it)
    return buckets
