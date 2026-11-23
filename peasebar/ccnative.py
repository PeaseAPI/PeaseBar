#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ControlCenter 按 App 显隐通道（macOS 27「系统设置 > 菜单栏」的存储直写）。

隐藏机制的真相（真机实证 2026-11-23，Thaw native 模式同源）：
- `~/Library/Group Containers/group.com.apple.controlcenter/.../group.com.apple.controlcenter.plist`
  里的 `trackedApplications[]` 每条记录带 `isAllowed`（该 App 菜单栏图标是否允许显示）；
- 外部写 `isAllowed=false` 后 **killall MenuBarAgent**（渲染宿主重读）→ 图标从菜单栏
  消失而 App 进程照常运行；`isAllowed=true` 同法 → 图标回来。双向可逆；
- **不受系统收纳条容量限制**（这是系统级开关，不是溢出区），因此「想藏几枚藏几枚」；
- 图标隐藏后从 AX 树消失，点击弹窗格子需「先临时显示 → AXPress 弹菜单 → 再收回」。

为何不 killing ControlCenter：只杀 cfprefsd（清偏好缓存）+ MenuBarAgent（渲染宿主）
即可生效；ControlCenter 不参与判定。为何外部写 plist 是安全的：写完立即 killall
cfprefsd，launchd 拉起新实例从磁盘重读，旧缓存不会回写覆盖。
"""
import os
import plistlib
import subprocess
import time

from peasebar import sections

# 记录文件路径（TCC 只保护目录列举，按完整路径读写不受限——实证可读写）
CC_PLIST = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.controlcenter/"
    "Library/Preferences/group.com.apple.controlcenter.plist")

# 永不允许隐藏的 bundle id：PeaseBar 自己的控制图标必须常显，否则面板叫不出来
PROTECTED = {"com.pease.peasebar"}


def is_protected(bid):
    """true = 这个 bundle id 不适用本通道：PeaseBar 自己，或 Apple 自家（含 agent）。"""
    if not bid:
        return True
    return bid in PROTECTED or bid.startswith("com.apple.")


# 侧车状态文件：记下 PeaseBar 上轮藏了谁（与用户手动在系统设置里关的区分开，
# 启动同步只翻转自己藏过的，不动用户的手动选择）
def state_path():
    return sections.config_path() + ".cc"


def record_hidden(bids):
    """把本轮 PeaseBar 藏的 bundle id 落盘（去重保序）。"""
    import json
    try:
        with open(state_path(), "r", encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        prev = []
    merged = [b for b in prev if b not in bids] + sorted(bids)
    try:
        with open(state_path(), "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False)
    except Exception:
        pass
    return merged


def last_hidden():
    """上轮 PeaseBar 藏的 bundle id 列表（无记录返回空表）。"""
    import json
    try:
        with open(state_path(), "r", encoding="utf-8") as f:
            return [b for b in json.load(f) if not is_protected(b)]
    except Exception:
        return []


def is_writable():
    """记录文件可读可写则通道可用（系统升级可能变动，失败时上层回退拖拽）。"""
    try:
        with open(CC_PLIST, "rb") as f:
            plistlib.load(f)
        return os.access(CC_PLIST, os.W_OK)
    except Exception:
        return False


def _load():
    """读文件，返回 (外层 dict, trackedApplications 记录列表)。"""
    with open(CC_PLIST, "rb") as f:
        outer = plistlib.load(f)
    recs = outer.get("trackedApplications")
    if isinstance(recs, bytes):
        recs = plistlib.loads(recs)
    return outer, recs


def record_bid(rec):
    """取记录的 bundle id：完整记录在 location.bundle._0，简单记录在 bundle._0。"""
    loc = rec.get("location") or rec
    b = loc.get("bundle") if isinstance(loc, dict) else None
    return (b or {}).get("_0")


def hidden_bids_now():
    """当前系统里 isAllowed=false 的 bundle id 集合（诊断用）。"""
    try:
        _, recs = _load()
    except Exception:
        return set()
    return {record_bid(r) for r in recs
            if r.get("isAllowed") is False and record_bid(r)}


def is_app_hidden(bid):
    """查一个 App 此刻的 CC 显隐状态（含前缀匹配）。

    True = 已藏；False = 有记录且显示；None = 管不了（无完整记录，
    例如 Apple 系统项或从未被系统跟踪过的 App），调用方据此回退拖拽。
    """
    try:
        _, recs = _load()
    except Exception:
        return None
    by_bid = {}
    for rec in recs:
        if "isAllowed" not in rec:
            continue
        b = record_bid(rec)
        if b:
            by_bid[b] = rec
    rec = by_bid.get(match_bid(bid, set(by_bid)))
    if rec is None:
        return None
    return rec["isAllowed"] is False


def match_bid(bid, known):
    """在已知 bid 集合里找 bid 的落点：精确优先，退化为包名前缀。

    盘点给的 bundle id 有时带子路径（CleanMyMac 的菜单宿主是
    com.macpaw.CleanMyMac5.Menu，而系统记录挂在 com.macpaw.CleanMyMac5），
    按「前缀 + 分段边界」匹配（com.a.b 不得匹配 com.a.bc）；多个命中取最短
    （最贴近盘点 bid 的安装主体）。无命中返回 None。
    """
    if bid in known:
        return bid
    hits = [k for k in known
            if k.startswith(bid + ".") or bid.startswith(k + ".")]
    if not hits:
        return None
    return min(hits, key=len)


def set_apps_allowed(bids, allowed):
    """把 bids 里各 App 的 isAllowed 改成 allowed，返回实际改动的 bundle id 集合。

    只动已有完整记录（带 isAllowed 键）的第三方；PeaseBar 自己与 com.apple.*
    永不触碰。盘点 bid 与系统记录 bid 允许前缀差异（match_bid）。改完一次性
    apply_now()（一轮重启，不按 App 杀多次）。返回的是调用方传入的 bid
    （与配置/侧车同一口径），不是系统记录的落点 bid。
    """
    want = {b for b in bids if not is_protected(b)}
    if not want:
        return set()
    outer, recs = _load()
    by_bid = {}
    for rec in recs:
        if "isAllowed" not in rec:
            continue
        b = record_bid(rec)
        if b:
            by_bid[b] = rec
    changed = set()
    for w in want:
        rec = by_bid.get(match_bid(w, set(by_bid)))
        if rec is not None and rec["isAllowed"] != allowed:
            rec["isAllowed"] = allowed
            changed.add(w)
    if not changed:
        return set()
    outer["trackedApplications"] = plistlib.dumps(recs, fmt=plistlib.FMT_BINARY)
    # 原子写：先临时文件再 replace，避免被系统读到半截
    tmp = CC_PLIST + ".peasebar.tmp"
    with open(tmp, "wb") as f:
        f.write(plistlib.dumps(outer, fmt=plistlib.FMT_BINARY))
    os.replace(tmp, CC_PLIST)
    apply_now()
    return changed


def apply_now():
    """让改动生效：清 cfprefsd 缓存（launchd 秒拉起）+ 重启 MenuBarAgent 重画。"""
    for proc in ("cfprefsd", "MenuBarAgent"):
        subprocess.run(["killall", proc], capture_output=True)
    # 给 launchd 拉起与首帧重画一点时间
    time.sleep(0.6)
