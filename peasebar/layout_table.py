#!/usr/bin/env python3.14
# -*- coding: utf-8 -*-
"""菜单栏「布局权重表」直接读写引擎（真机正路，替换合成 ⌘-拖）。

为什么走这条路（对标 Thaw / 系统「设置」的轻松、可逆、不重启）：
- macOS 把每条菜单栏图标的顺序/显隐存成一张「权重表」：
  plist 顶层键 menuItemLocations = {状态键: 整数权重}；
  文件在受 TCC 保护的 group 容器里：
    ~/Library/Group Containers/group.com.apple.controlcenter/
        Library/Preferences/group.com.apple.controlcenter.plist
- 给某枚图标写一个「停车权重」（≥ HIDDEN_BASE）= 隐藏；写回正常段小值 = 显示；
  ≥ ALWAYS_BASE = 永久隐藏。MenuBarAgent 监听该表变更后自动重排——
  不移动光标、不占溢出区容量、随时可逆、也不重启目标 App。
- Group Containers 对第三方进程直接 open/读一律 EPERM，必须像 Thaw 那样
  用 NSOpenPanel 让用户「亲自选中这一个 plist」，拿到 security-scoped 书签
  才能读写。本模块负责这套授权 + 书签持久化 + 读表 + 写表 + 惊动重排。

权重常量来自 PlatformRuntimeKit 反汇编（PositionHideBackend）：
  hiddenWeightBase=0xc350=50000、alwaysHiddenWeightBase=0xea60=60000、
  isParked(w)=w>49999。
"""
from __future__ import annotations

import base64
import os
import plistlib

from Foundation import (NSURL, NSData,
                        CFPreferencesSetValue, CFPreferencesSynchronize,
                        CFSTR, kCFPreferencesCurrentUser, kCFPreferencesAnyHost)

# 停车权重常量（与系统 PositionHideBackend 完全一致）
HIDDEN_BASE = 50000
ALWAYS_BASE = 60000
PARKED_ABOVE = 49999

# CFPreferences 域（写这张表用组域 suite 名，MenuBarAgent 监听它）
SUITE = "group.com.apple.controlcenter"
TABLE_KEY = "menuItemLocations"

# 书签在原权重表里替代 label 的位置：我们把自己维护的书签/备份存进 config.json
BOOKMARK_CFG_KEY = "layout_table_bookmark"


def _log(msg: str) -> None:
    print(f"[PeaseBar][布局表] {msg}")


def table_path() -> str:
    """布局权重表 plist 的绝对路径。"""
    return os.path.expanduser(
        "~/Library/Group Containers/group.com.apple.controlcenter/"
        "Library/Preferences/group.com.apple.controlcenter.plist")


def is_parked(w) -> bool:
    """权重是否为「停车值」（即该图标已被系统收进隐藏段）。"""
    try:
        return int(w) > PARKED_ABOVE
    except (TypeError, ValueError):
        return False


# ---------- 授权书签（security-scoped）持久化 ----------

def _save_bookmark(url) -> bool:
    """把选中文件的 security-scoped 书签写进 config.json（base64）。"""
    try:
        data, err = url.bookmarkDataWithOptions_includingResourceValuesForKeys_relativeToURL_error_(
            _CREATE_SCOPE, None, None, None)
    except Exception as exc:  # noqa: BLE001
        _log(f"生成书签异常：{exc}")
        return False
    if not data:
        _log(f"生成书签失败：{err}")
        return False
    from peasebar import sections
    cfg = sections.load_config()
    cfg["prefs"][BOOKMARK_CFG_KEY] = base64.b64encode(bytes(data)).decode()
    sections.save_config(cfg)
    return True


# bookmark 选项常量：不同 pyobjc 版本未必都导出，缺则用文档数值
try:
    from Foundation import NSURLBookmarkCreationWithSecurityScope as _CREATE_SCOPE
except ImportError:  # noqa: E402
    _CREATE_SCOPE = 1 << 8
try:
    from Foundation import NSURLBookmarkResolutionWithSecurityScope as _RESOLVE_SCOPE
except ImportError:  # noqa: E402
    _RESOLVE_SCOPE = 1 << 10


def _load_bookmark_url():
    """还原持久化的书签为 NSURL（带 security scope）；没有/失效返回 None。"""
    from peasebar import sections
    cfg = sections.load_config()
    raw = cfg.get("prefs", {}).get(BOOKMARK_CFG_KEY)
    if not raw:
        return None
    try:
        data = NSData.dataWithBytes_length_(base64.b64decode(raw), len(base64.b64decode(raw)))
    except Exception:  # noqa: BLE001
        return None
    stale = None
    url, err = NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(
        data, _RESOLVE_SCOPE, None, stale, None)
    if url is None:
        _log(f"书签解析失败：{err}")
    return url


def request_access(parent=None) -> bool:
    """弹一次中文文件选择框，请用户亲自选中 group.com.apple.controlcenter.plist。

    返回是否成功拿到授权书签。这一步是所有同类软件「一次授权、之后轻松」的关键，
    也是绕过 Group Containers TCC 保护的唯一正路。
    """
    from AppKit import NSOpenPanel, NSFileHandlingPanelOKButton
    panel = NSOpenPanel.alloc().init()
    panel.setCanChooseFiles_(True)
    panel.setCanChooseDirectories_(False)
    panel.setAllowsMultipleSelection_(False)
    panel.setResolvesAliases_(True)
    panel.setTreatsFilePackagesAsDirectories_(False)
    tp = table_path()
    panel.setDirectoryURL_(NSURL.fileURLWithPath_(os.path.dirname(tp)))
    panel.setTitle_("授权读取菜单栏布局表")
    panel.setMessage_(
        "PeaseBar 需要访问这一个文件来逐枚隐藏菜单栏图标（和系统「设置」、"
        "同类软件的做法一致）。\n请选中并打开：group.com.apple.controlcenter.plist\n"
        "PeaseBar 只会被授予这一个文件的访问权限。")
    if panel.runModal() != int(NSFileHandlingPanelOKButton):
        _log("用户未选择文件，授权取消")
        return False
    url = panel.URLs()[0]
    if os.path.realpath(url.path()) != os.path.realpath(tp):
        _log(f"选中的不是布局表文件：{url.path()}")
        return False
    ok = _save_bookmark(url)
    _log("已保存布局表访问授权" if ok else "授权保存失败")
    return ok


def has_access() -> bool:
    """当前是否能真正读到布局表（书签存在且可打开）。"""
    url = _load_bookmark_url()
    if url is None:
        return False
    scoped = url.startAccessingSecurityScopedResource()
    try:
        data = NSData.dataWithContentsOfURL_(url)
        return data is not None
    finally:
        if scoped:
            url.stopAccessingSecurityScopedResource()


# ---------- 读表 / 写表 ----------

def _read_whole_plist(url):
    """读整份 plist，返回可变 python dict；失败 None。"""
    data = NSData.dataWithContentsOfURL_(url)
    if data is None:
        return None
    try:
        return plistlib.loads(bytes(data))
    except Exception as exc:  # noqa: BLE001
        _log(f"解析 plist 失败：{exc}")
        return None


def read_positions() -> dict:
    """读 menuItemLocations 权重表，返回 {状态键: 整数权重}；不可读返回 {}。"""
    url = _load_bookmark_url()
    if url is None:
        return {}
    scoped = url.startAccessingSecurityScopedResource()
    try:
        root = _read_whole_plist(url)
        if root is None:
            return {}
        loc = root.get(TABLE_KEY)
        out = {}
        if isinstance(loc, dict):
            for k, v in loc.items():
                try:
                    out[str(k)] = int(v)
                except (TypeError, ValueError):
                    out[str(k)] = v
        return out
    finally:
        if scoped:
            url.stopAccessingSecurityScopedResource()


def write_positions(positions: dict) -> bool:
    """把新的 menuItemLocations 权重表写回文件并广播给 MenuBarAgent 重排。

    两条都发（与 PRK 一致：CFPreferences 广播优先 + 直接落盘兜底）：
    1) 直接改写 plist 文件里 menuItemLocations 子表（保留其它顶层键不动）；
    2) CFPreferencesSetValue(整表)+Synchronize，触发 MenuBarAgent 偏好监听重排。
    """
    url = _load_bookmark_url()
    if url is None:
        _log("写表失败：无授权书签")
        return False
    scoped = url.startAccessingSecurityScopedResource()
    try:
        root = _read_whole_plist(url)
        if root is None:
            return False
        root[TABLE_KEY] = dict(positions)
        blob = plistlib.dumps(root, fmt=plistlib.FMT_BINARY)
        data = NSData.dataWithBytes_length_(blob, len(blob))
        did = data.writeToURL_atomically_(url, True)
        # 广播：让 cfprefsd 通知 MenuBarAgent（能写则写，失败不致命，已落盘）
        try:
            CFPreferencesSetValue(CFSTR(TABLE_KEY), positions, CFSTR(SUITE),
                                  kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
            CFPreferencesSynchronize(CFSTR(SUITE), kCFPreferencesCurrentUser,
                                     kCFPreferencesAnyHost)
        except Exception as exc:  # noqa: BLE001
            _log(f"CFPreferences 广播异常（已落盘，忽略）：{exc}")
        _log(f"写表完成：{len(positions)} 条，落盘={did}")
        return bool(did)
    finally:
        if scoped:
            url.stopAccessingSecurityScopedResource()


def relayout() -> None:
    """惊动 MenuBarAgent 重新按表排版（在已广播的基础上再同步一次，尽量免重启）。

    优先靠偏好变更通知驱动重排；若个别机器不响应，上层会回退到合成拖，
    不再重启任何目标 App。
    """
    try:
        CFPreferencesSynchronize(CFSTR(SUITE), kCFPreferencesCurrentUser,
                                 kCFPreferencesAnyHost)
    except Exception as exc:  # noqa: BLE001
        _log(f"relayout 同步异常：{exc}")


# ---------- 把我们的图标匹配到表里的状态键 ----------

def _norm(s: str) -> str:
    return (s or "").lower().strip()


def resolve_key(item, keys) -> str | None:
    """把一枚 MenuItem 对应到布局表里的状态键。

    状态键形如 status:<owner>::<name>（Thaw 源码 StrandedAlwaysHiddenDivider）。
    优先用 owner_bundle_id 命中，再在候选里用 key_part/label 词元消歧；
    只命中一条时直接用它。匹配不到返回 None（这枚交回上层用拖拽兜底）。
    """
    owner = _norm(getattr(item, "owner_bundle_id", "") or "")
    if not owner:
        return None
    # 1. owner 命中的候选键
    cands = [k for k in keys if owner in _norm(k)]
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    # 2. 多候选：用稳定名/标签的词元打分
    name_tokens = set()
    for src in (getattr(item, "key_part", "") or "", getattr(item, "label", "") or ""):
        for tok in _norm(src).replace("::", " ").split():
            if len(tok) >= 2:
                name_tokens.add(tok)
    best, best_score = None, -1
    for k in cands:
        tail = k.split("::")[-1] if "::" in k else k
        score = sum(1 for tok in name_tokens if tok in _norm(tail))
        if score > best_score:
            best, best_score = k, score
    return best


def hide(item, always: bool = False) -> bool:
    """逐枚隐藏：把这枚图标的权重写成停车值（≥50000 / 永久 ≥60000）。

    可逆、无数量限制、不重启。成功返回 True。匹配不到状态键返回 False。
    """
    positions = read_positions()
    if not positions:
        _log("hide 失败：读不到权重表（未授权或表为空）")
        return False
    key = resolve_key(item, list(positions.keys()))
    if key is None:
        _log(f"hide 失败：{getattr(item,'owner_bundle_id','?')} 匹配不到状态键")
        return False
    base = ALWAYS_BASE if always else HIDDEN_BASE
    # 记录原权重，供显示时还原（放进 config.prefs）
    _remember_original(key, positions.get(key))
    # 停车值按当前已有停车数量微增，避免多枚同值互相顶（保持相对次序稳定）
    parked_existing = [w for w in positions.values() if is_parked(w)]
    positions[key] = base + len(parked_existing)
    ok = write_positions(positions)
    if ok:
        relayout()
    return ok


def show(item) -> bool:
    """取消隐藏：把这枚图标权重写回正常段（有存档就还原存档，没有就给个低位）。"""
    positions = read_positions()
    if not positions:
        return False
    key = resolve_key(item, list(positions.keys()))
    if key is None:
        return False
    orig = _pop_original(key)
    if orig is not None and not is_parked(orig):
        positions[key] = orig
    else:
        # 没有可用原值：放到「可见段」权重上界之外一点点会又变停车，故放到所有
        # 正常值之下，保证显示；MenuBarAgent 会按可见段重排。
        normal = [w for w in positions.values() if isinstance(w, int) and not is_parked(w)]
        positions[key] = (min(normal) - 100) if normal else 100
    ok = write_positions(positions)
    if ok:
        relayout()
    return ok


def apply_plan(assignments: dict) -> bool:
    """一趟写入多枚图标的目标分区（{状态键: 'visible'|'hidden'|'always_hidden'}）。

    reconcile/启动同步用它：读一次表→按目标批量调权重→写一次→广播一次。
    """
    positions = read_positions()
    if not positions:
        return False
    parked_existing = sum(1 for w in positions.values() if is_parked(w))
    changed = False
    for key, want in assignments.items():
        if key not in positions:
            continue
        if want in ("hidden", "always_hidden"):
            if not is_parked(positions[key]):
                _remember_original(key, positions[key])
                base = ALWAYS_BASE if want == "always_hidden" else HIDDEN_BASE
                positions[key] = base + parked_existing
                parked_existing += 1
                changed = True
        elif want == "visible":
            if is_parked(positions[key]):
                orig = _pop_original(key)
                normal = [w for w in positions.values()
                          if isinstance(w, int) and not is_parked(w)]
                positions[key] = (orig if (orig is not None and not is_parked(orig))
                                  else ((min(normal) - 100) if normal else 100))
                changed = True
    if not changed:
        _log("apply_plan：无需变更")
        return True
    ok = write_positions(positions)
    if ok:
        relayout()
    return ok


# ---------- 原权重存档（放 config.prefs，显示时精确还原） ----------

_ORIG_CFG_KEY = "layout_table_originals"


def _remember_original(key, weight) -> None:
    from peasebar import sections
    cfg = sections.load_config()
    store = cfg["prefs"].setdefault(_ORIG_CFG_KEY, {})
    # 只在尚未存档、且当前是正常权重时记一次，避免把停车值当原值存进去
    if key not in store and isinstance(weight, int) and not is_parked(weight):
        store[key] = weight
        sections.save_config(cfg)


def _pop_original(key):
    from peasebar import sections
    cfg = sections.load_config()
    store = cfg.get("prefs", {}).get(_ORIG_CFG_KEY, {})
    val = store.pop(key, None)
    if val is not None:
        cfg["prefs"][_ORIG_CFG_KEY] = store
        sections.save_config(cfg)
    return val
