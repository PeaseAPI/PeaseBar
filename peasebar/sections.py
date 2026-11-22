#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分区与顺序模型（F4/F11）：可见 / 隐藏 / 永久隐藏 三区 + 区内顺序 + JSON 持久化。

- 配置键 = bundleId + 稳定名（`key_part`）。同一 App 双图标的序号消歧由 inventory 负责（T55）；
- 不在配置中的图标一律归「菜单栏显示」（默认区，内部代号 SECTION_VISIBLE），
  配置文件只记非默认区，保持精简；
- 区内顺序：`order` 是一份显式的键序列（用户在前一格/后一格调出来的结果），
  没记过名的新图标按盘点顺序排在末尾 —— 与 Thaw 布局编辑器的语义一致
  （它把顺序存在 tag 上，我们存在这份列表里）；
- v1 的「隐藏」只是面板分区（图标本身仍在菜单栏），真正的隐藏联动（原生收纳写入）
  在 F12；顺序写入真实菜单栏属 Phase 3，先把我们自己的顺序管起来；
- 纯逻辑函数（item_key/section_of/set_section/plan_sections/move_in_list/apply_order）
  不依赖 AppKit，可离线单测（tests/test_sections.py），item 只要求
  owner_bundle_id/label 两个属性（鸭子类型）；
- 持久化：~/Library/Application Support/PeaseBar/config.json，原子写（tmp + os.replace）；
  文件同时承载面板行为配置（panel_timeout 秒，0=不超时，默认 8，F5）。
"""
import json
import os

SECTION_VISIBLE = "visible"
SECTION_HIDDEN = "hidden"
SECTION_ALWAYS_HIDDEN = "always_hidden"

SECTION_LABELS = {
    SECTION_VISIBLE: "菜单栏显示",
    SECTION_HIDDEN: "弹窗显示",
    SECTION_ALWAYS_HIDDEN: "永久隐藏",
}

# 区的上下顺序（⌥↑/⌥↓ 换区、↑/↓ 跳选都按这个序列走）
SECTION_ORDER = (SECTION_VISIBLE, SECTION_HIDDEN, SECTION_ALWAYS_HIDDEN)

# 控制图标预设（菜单栏触发钮可定义，用户定调：比如三个点之类）：
# (SF Symbol 名, 设置页显示名)；存 key，渲染端找不到符号时退回文字「···」
CONTROL_ICONS = (
    ("ellipsis.circle.fill", "圆圈三点（默认）"),
    ("ellipsis", "三点"),
    ("eye", "眼睛"),
    ("command", "命令键"),
    ("square.grid.2x2", "四格"),
)

DEFAULT_CONFIG = {"sections": {}, "order": [], "panel_timeout": 8,
                  "control_icon": CONTROL_ICONS[0][0],
                  # 布局页选项（Phase 9，对标 Thaw 的 Options 卡片）：
                  # use_captured=格子优先用菜单栏真实截图像素；bar_wrap=图标条放不下就换行
                  # 换行默认开：单行放不下会被条子裁掉，用户看到的是「图标少了一半」，
                  # 宁可区变高，也要整区一次看全（Thaw 的 LayoutBar 就是自动折行）
                  "use_captured": True, "bar_wrap": True}


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
    icon = data.get("control_icon")
    # 只认预设表里的符号名：脏数据/旧版本删掉的预设回默认，渲染端不用二次校验
    if isinstance(icon, str) and any(k == icon for k, _ in CONTROL_ICONS):
        cfg["control_icon"] = icon
    # 两个布局选项只认布尔值（json 里写别的都当没写过，回默认）
    for flag in ("use_captured", "bar_wrap"):
        if isinstance(data.get(flag), bool):
            cfg[flag] = data[flag]
    raw_order = data.get("order")
    if isinstance(raw_order, list):
        # 只留字符串项，且去重保序（脏数据/重复键会让位次计算自相矛盾）
        seen, order = set(), []
        for k in raw_order:
            if isinstance(k, str) and k not in seen:
                seen.add(k)
                order.append(k)
        cfg["order"] = order
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
    """查图标所在区；无记录 = 菜单栏显示（默认）。"""
    s = cfg["sections"].get(key)
    return s if s in (SECTION_HIDDEN, SECTION_ALWAYS_HIDDEN) else SECTION_VISIBLE


def set_section(cfg, key, section):
    """把图标移到某区；visible=回默认区（删键，配置文件只存非默认区）。"""
    if section == SECTION_VISIBLE:
        cfg["sections"].pop(key, None)
    elif section in (SECTION_HIDDEN, SECTION_ALWAYS_HIDDEN):
        cfg["sections"][key] = section


def apply_order(items, cfg):
    """按显式顺序表排列（稳定排序）：没记过名的保持传入顺序，统一排在末尾。"""
    pos = {k: i for i, k in enumerate(cfg.get("order") or [])}
    fallback = len(pos)
    return sorted(items, key=lambda it: pos.get(item_key(it), fallback))


def move_in_list(keys, key, delta):
    """把 key 在序列里前移（delta<0）/后移（delta>0）若干位，越界就地夹住。

    返回 (新序列, 是否真的动了)。动不了（末尾再往后、key 不在表里）时返回原序列，
    调用方据此决定是否写盘/记撤销点，避免按下无效键也产生一次「可撤销的改动」。
    """
    out = list(keys)
    if key not in out:
        return out, False
    i = out.index(key)
    j = max(0, min(len(out) - 1, i + delta))
    if i == j:
        return out, False
    out.pop(i)
    out.insert(j, key)
    return out, True


def plan_sections(items, cfg):
    """按三区分桶（纯函数）。返回 dict[区名] → [item]，桶内按显式顺序排列。"""
    buckets = {s: [] for s in SECTION_ORDER}
    for it in items:
        buckets[section_of(cfg, item_key(it))].append(it)
    for s in buckets:
        buckets[s] = apply_order(buckets[s], cfg)
    return buckets


def flatten(buckets):
    """分桶摊回一维（按区顺序），供 store_order 写回完整展示顺序。"""
    return [it for s in SECTION_ORDER for it in buckets.get(s, [])]


def find_pos(buckets, key):
    """选中键在 (区, 区内序号) 里的位置；没记或已消失返回 None。"""
    if not key:
        return None
    for s in SECTION_ORDER:
        for i, it in enumerate(buckets.get(s) or []):
            if item_key(it) == key:
                return s, i
    return None


def move_to_index(seq, key_of, key, index):
    """把 seq 里 key_of(it)==key 那一项摘出来、插到 index（拖拽落位，纯函数）。

    同区拖与跨区拖都走它：先摘后插，所以落在自己右边时要把目标位往后让一格
    （视觉上的「两格之间」在摘掉自己之后变了一格）。index 越界就地夹住；
    key 不在序列里时原样返回（宁可不也不凭空插个空位）。
    """
    out = list(seq)
    src = next((i for i, it in enumerate(out) if key_of(it) == key), None)
    if src is None:
        return out
    item = out.pop(src)
    if src < index:
        index -= 1
    out.insert(max(0, min(len(out), index)), item)
    return out


def reorder_bucket(buckets, section, key, delta):
    """同区内把 key 挪 delta 格。返回 (新 buckets, 是否真动了)，不改入参。

    抽成纯函数是为了让单测能直接测编辑语义本身，不用拉 AppKit 与窗口。
    """
    group = list(buckets.get(section) or [])
    keys = [item_key(it) for it in group]
    new_keys, changed = move_in_list(keys, key, delta)
    out = dict(buckets)
    if not changed:
        return out, False
    by_key = {item_key(it): it for it in group}
    out[section] = [by_key[k] for k in new_keys]
    return out, True


def sort_bucket_by_name(buckets, section):
    """把某区按显示名排序（大小写不敏感），不改入参。

    对应 Thaw 每区「Sort by Name」菜单项。返回 (新 buckets, 是否真的变了)：
    已经有序时 changed=False，调用方据此决定要不要写盘/记撤销点（与
    reorder_bucket 同一套「无效动作不留撤销痕迹」的纪律）。
    """
    group = list(buckets.get(section) or [])
    ordered = sorted(group, key=lambda it: (it.label or "").casefold())
    out = dict(buckets)
    out[section] = ordered
    changed = [item_key(it) for it in group] != [item_key(it) for it in ordered]
    return out, changed


def reset_layout(cfg):
    """重置布局：分区归属与自定义顺序清空，panel_timeout 等行为配置不动。"""
    cfg["sections"] = {}
    cfg["order"] = []
    return cfg


def neighbour_section(section, delta):
    """⌥↑/⌥↓ 的目标区：沿 SECTION_ORDER 移动，越界返回 None（顶端不再往上换区）。"""
    if section not in SECTION_ORDER:
        return None
    i = SECTION_ORDER.index(section) + delta
    return SECTION_ORDER[i] if 0 <= i < len(SECTION_ORDER) else None


def select_neighbour(buckets, key, dx, dy):
    """不带修饰的方向键：找下一个该选中的键（←/→ 同区，↑/↓ 跳区并夹住位次）。

    没选中项时返回第一个非空区的首格（「一按方向键就有的选」），
    一个图标都没有时返回 None。跳区不跳空区：否则按一↑选中会默默丢。
    """
    groups = [(s, buckets.get(s) or []) for s in SECTION_ORDER]
    groups = [(s, g) for s, g in groups if g]
    if not groups:
        return None
    by_sec = dict(groups)
    pos = find_pos(buckets, key)
    if pos is None:
        return item_key(groups[0][1][0])
    sec, idx = pos
    if dx:
        group = by_sec[sec]
        j = max(0, min(len(group) - 1, idx + dx))
        return item_key(group[j])
    if dy:
        order = [s for s, _ in groups]
        i = max(0, min(len(order) - 1, order.index(sec) + dy))
        group = by_sec[order[i]]
        return item_key(group[max(0, min(len(group) - 1, idx))])
    return None


def store_order(cfg, items):
    """把当前展示顺序整体记进配置（编辑器的写侧入口）。"""
    cfg["order"] = [item_key(it) for it in items]
    return cfg


def snapshot(cfg):
    """可撤销动作前的深拷贝快照（只存分区与顺序两项，行为配置不参与撤销）。"""
    return {"sections": dict(cfg.get("sections") or {}),
            "order": list(cfg.get("order") or [])}


def restore_snapshot(cfg, snap):
    """把快照写回 cfg（就地改，返回是否成功）。"""
    if not isinstance(snap, dict):
        return False
    cfg["sections"] = dict(snap.get("sections") or {})
    cfg["order"] = list(snap.get("order") or [])
    return True
