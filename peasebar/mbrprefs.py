# -*- coding: utf-8 -*-
"""菜单栏物理顺序引擎：com.apple.MenuBar 的 TrailingItemPreferredPositions 权重表。

真机实证（2026-11-24 报障#6 实验）：
- 这张表存右侧图标段每枚图标的排布权重：键 `status:<bundle>::<item>` /
  `module:<名>`，值越大越靠左（QQ=570.5 > 微信=532.5 > Telegram=492.5，
  Clock=0 最右，-2200 = 进口袋）；
- 按目标序置换权重 + killall cfprefsd/MenuBarAgent → 图标视觉顺序真的互换，
  全程零鼠标；agent 重启后原样尊重外部写的值（复读 12s 未被改写）；
- 该 plist 装机进程可直接读写（不同于 CC 组域表，无需 security-scoped 书签）。

改序策略只做置换不做发明：把参与项之间现有的权重值按目标序重新发牌，
未参与项（系统 module、没盘点的）原值不动 → 它们与参与项的相对位置保持，
整段不会把谁挤出可视区。
"""
import os
import plistlib

PLIST_PATH = os.path.expanduser(
    "~/Library/Group Containers/com.apple.MenuBar/Library/Preferences/"
    "com.apple.MenuBar.plist")
TABLE_KEY = "TrailingItemPreferredPositions"


def _log(msg):
    print(f"[PeaseBar][顺序表] {msg}")


def bundle_of_key(key):
    """`status:<bundle>::<item>` → bundle；module:/异形键返回 None。"""
    if not key.startswith("status:"):
        return None
    head, sep, _tail = key[len("status:"):].partition("::")
    return head if sep else None


def table_keys_by_bundle(table):
    """权重表 → {bundle: [完整键, …]}（只收 status: 第三方键）。"""
    out = {}
    for key in table or {}:
        bid = bundle_of_key(key)
        if bid:
            out.setdefault(bid, []).append(key)
    return out


def reorder_weights(table, ordered_bids, match_bid):
    """纯函数：按 ordered_bids（左→右目标序）给表内键重新发权重，返回新表。

    match_bid(bid, known) 把盘点口径的 bundle id 落到表内键（前缀差异，与
    ccnative 同一规则）。表里没有的项跳过（不发明权重）。Ordered_bids 里
    匹配到的键按目标序排成一条线，同 bundle 多键按 Item 名保持相对序；
    权重值只在参与键之间置换——数值集合不变，未参与键原值不动。
    已是目标序时返回原表引用（调用方据此幂等跳过）。
    """
    by_bid = table_keys_by_bundle(table)
    known = set(by_bid)
    seq = []  # 目标序下的完整键列表
    for bid in ordered_bids:
        hit = match_bid(bid, known)
        if not hit:
            continue
        seq.extend(sorted(by_bid[hit]))
    if len(seq) < 2:
        return table
    pool = sorted((table[k] for k in seq), reverse=True)
    want = dict(zip(seq, pool))
    if all(table[k] == want[k] for k in seq):
        return table  # 幂等：目标序就是现状
    return {**table, **want}


def _read():
    with open(PLIST_PATH, "rb") as f:
        return plistlib.load(f)


def _write(data):
    """原子写 + 立即清 cfprefsd 缓存：agent 重启前缓存里还是旧值，
    必须先杀 cfprefsd 再杀 agent，新表才会在重画时被读到。"""
    import subprocess
    tmp = PLIST_PATH + ".peasebar.tmp"
    with open(tmp, "wb") as f:
        plistlib.dump(data, f)
    os.replace(tmp, PLIST_PATH)
    subprocess.run(["killall", "cfprefsd"], capture_output=True)


def apply_visible_order(ordered_bids, match_bid):
    """把「菜单栏显示」区的目标序写进权重表。返回 {changed, error}。

    只写表不重启 agent：调用方随后统一 apply（与显隐同步共用一次重启，
    少闪一次栏）。写不了（路径异常/权限）只报告不抛——显隐同步照跑。
    """
    out = {"changed": 0, "error": None}
    try:
        data = _read()
        table = data.get(TABLE_KEY)
        if not isinstance(table, dict):
            out["error"] = f"表形态异常：{type(table).__name__}"
            return out
        new = reorder_weights(table, ordered_bids, match_bid)
        if new is table:
            return out
        changed = [k for k in new if new[k] != table.get(k)]
        data[TABLE_KEY] = new
        _write(data)
        out["changed"] = len(changed)
        _log(f"已按目标序重排 {len(changed)} 个键的权重，待 apply 生效")
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out
