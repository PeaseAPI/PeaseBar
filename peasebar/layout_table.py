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
                        CFPreferencesCopyAppValue, CFPreferencesCopyValue,
                        CFPreferencesCopyKeyList,
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
    # 该类方法有一个返回对象 + 两个出参（bookmarkDataIsStale、error），
    # pyobjc 会把它们打包成 3 元组 (url, stale, err) 返回，必须按 3 个解。
    res = NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(
        data, _RESOLVE_SCOPE, None, stale, None)
    if isinstance(res, tuple):
        url = res[0]
        err = res[-1]
        stale = res[1] if len(res) >= 3 else None
    else:
        url = res
        err = None
    if url is None:
        _log(f"书签解析失败：{err}")
    elif stale:
        _log("书签已失效（stale），需重新授权布局表")
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


def _probe_cfprefs() -> dict:
    """用 CFPreferences 在多个候选域/键上探一次，定位真正的权重表。

    诊断用：把每个 {域 × 键} 的 CFPreferencesCopyAppValue 结果、以及域的全部键列表
    都落到文件，看哪个组合返回 {status:...: 权重} 字典。
    """
    domains = [
        "com.apple.controlcenter",
        "group.com.apple.controlcenter",
    ]
    keys = [
        "TrailingItemPreferredPositions",
        "menuItemLocations",
        "TrailingItemPreferredPositions ",
    ]
    out = {}
    for dom in domains:
        entry = {}
        for key in keys:
            # 两种 API 各试：CopyAppValue（应用域）与 CopyValue（套件域 + user/host）。
            try:
                val = CFPreferencesCopyAppValue(CFSTR(key), CFSTR(dom))
                if val is None:
                    entry["CopyAppValue:" + key] = None
                elif isinstance(val, dict):
                    entry["CopyAppValue:" + key] = {
                        "type": "dict", "count": len(val),
                        "sample": {str(k): v for k, v in
                                   list(val.items())[:8]}}
                else:
                    entry["CopyAppValue:" + key] = {
                        "type": type(val).__name__, "value": str(val)[:120]}
            except Exception as exc:  # noqa: BLE001
                entry["CopyAppValue:" + key] = f"异常：{exc}"
            try:
                val2 = CFPreferencesCopyValue(CFSTR(key), CFSTR(dom),
                                              kCFPreferencesCurrentUser,
                                              kCFPreferencesAnyHost)
                if val2 is None:
                    entry["CopyValue:" + key] = None
                elif isinstance(val2, dict):
                    entry["CopyValue:" + key] = {
                        "type": "dict", "count": len(val2),
                        "sample": {str(k): v for k, v in
                                   list(val2.items())[:8]}}
                else:
                    entry["CopyValue:" + key] = {
                        "type": type(val2).__name__, "value": str(val2)[:120]}
            except Exception as exc:  # noqa: BLE001
                entry["CopyValue:" + key] = f"异常：{exc}"
        # 域的全部键（判断到底有哪些偏好驻留）
        try:
            kl = CFPreferencesCopyKeyList(CFSTR(dom), kCFPreferencesCurrentUser,
                                          kCFPreferencesAnyHost)
            entry["__all_keys__"] = [str(k) for k in (kl or [])]
        except Exception as exc:  # noqa: BLE001
            entry["__all_keys__"] = f"异常：{exc}"
        out[dom] = entry
    return out


def _jsonable(obj, _depth=0):
    """把 plist 解析出的结构递归转成 JSON 可序列化。

    对 bytes 值会尝试再当 plist 解一次（菜单栏权重表就藏在 trackedApplications
    这个 NSKeyedArchiver 归档块里），最多往下钻 3 层，避免无限递归。
    """
    if isinstance(obj, dict):
        return {str(k): _jsonable(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v, _depth + 1) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        # 试着把内层归档（bplist/NSKeyedArchiver）解出来，方便定位权重
        if _depth < 3:
            try:
                inner = plistlib.loads(bytes(obj))
                return {"__nested_plist__": _jsonable(inner, _depth + 1)}
            except Exception:  # noqa: BLE001
                pass
        return f"<bytes {len(obj)}>"
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def dump_table(path: str | None = None) -> dict:
    """把真实布局表结构 + 完整访问链诊断落到文件（诊断用，不参与业务）。

    只有签名后的 App 进程能读到这张 TCC 保护表，命令行读不了；因此把诊断
    做进 App 内、写到一个固定文件，我离线核对两件事：
    1) 授权链到底断在哪一步（书签缺失 / startAccessing 返回 False / 读回 None）；
    2) 若读得到，真实状态键的拼法是否匹配 resolve_key。
    写全顶层键 + menuItemLocations 的完整内容（不只样例），确保一次看清。
    """
    import json
    if path is None:
        path = os.path.join(os.path.expanduser("~/Project/PeaseBar/tmp"),
                            "layout_table_dump.json")
    result = {
        "table_path": table_path(),
        "table_path_exists": os.path.exists(table_path()),
    }
    # CFPreferences 探针：定位权重表到底在哪个域/键（单独落文件）。
    try:
        probe = _probe_cfprefs()
        pf = os.path.join(os.path.dirname(path), "cfprefs_probe.json")
        with open(pf, "w", encoding="utf-8") as pff:
            json.dump(probe, pff, ensure_ascii=False, indent=2, sort_keys=True,
                      default=str)
        _log(f"已 dump CFPreferences 探针 → {pf}")
    except Exception as exc:  # noqa: BLE001
        result["cfprefs_probe_error"] = str(exc)
    # 书签是否已持久化
    from peasebar import sections
    try:
        _cfg = sections.load_config()
        result["bookmark_saved"] = bool(_cfg.get(
            "prefs", {}).get(BOOKMARK_CFG_KEY))
    except Exception as exc:  # noqa: BLE001
        result["bookmark_saved"] = f"读取异常：{exc}"
    url = _load_bookmark_url()
    result["bookmark_resolved"] = url is not None
    if url is not None:
        try:
            result["resolved_path"] = url.path()
        except Exception:  # noqa: BLE001
            result["resolved_path"] = None
        scoped = url.startAccessingSecurityScopedResource()
        try:
            result["scoped_access"] = bool(scoped)
            # 直接试探 NSData 读，单独记录成功与否
            data = NSData.dataWithContentsOfURL_(url)
            result["nsdata_read_bytes"] = (len(data) if data is not None else None)
            root = _read_whole_plist(url)
            if root is None:
                result["error"] = "读文件失败（scoped 访问未生效？）"
                # 再用裸 open 探一次，拿 errno 佐证 TCC 是否真的放行
                try:
                    with open(table_path(), "rb") as _f:
                        result["raw_open_bytes"] = len(_f.read())
                except OSError as oe:
                    result["raw_open_errno"] = f"{oe.errno}: {oe.strerror}"
            else:
                result["top_level_keys"] = list(root.keys())
                loc = root.get(TABLE_KEY)
                if isinstance(loc, dict):
                    result["table_count"] = len(loc)
                    # 全量导出 {key: weight}，key 里若含非字符串也转 str 保底
                    result["menuItemLocations"] = {
                        str(k): (int(v) if isinstance(v, (int, float)) else str(v))
                        for k, v in loc.items()}
                else:
                    result["menuItemLocations_type"] = type(loc).__name__
                # 额外落一份完整 plist 结构（递归转成 JSON 可序列化），
                # 用于定位权重到底存在哪个顶层键/子结构里。
                try:
                    full = os.path.join(os.path.dirname(path),
                                        "layout_table_full.json")
                    with open(full, "w", encoding="utf-8") as ff:
                        json.dump(_jsonable(root), ff, ensure_ascii=False,
                                  indent=2, sort_keys=True, default=str)
                    _log(f"已 dump 完整 plist → {full}")
                except Exception as exc:  # noqa: BLE001
                    result["full_dump_error"] = str(exc)
        finally:
            if scoped:
                url.stopAccessingSecurityScopedResource()
    try:
        result["has_access"] = has_access()
    except Exception as exc:  # noqa: BLE001
        result["has_access"] = f"异常：{exc}"
    if path is None:
        path = os.path.join(os.path.expanduser("~/Project/PeaseBar/tmp"),
                            "layout_table_dump.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
        _log(f"已 dump 真实布局表 → {path}")
    except Exception as exc:  # noqa: BLE001
        _log(f"dump 写入失败：{exc}")
    return result


# ---------- 把我们的图标匹配到表里的状态键 ----------

def status_key(owner: str, identifier: str) -> str:
    """按 Thaw 口径构造状态键：status:<owner>::<identifier>。"""
    return f"status:{owner}::{identifier}"


def run_hide_experiment(owner: str, identifier: str, title: str) -> dict:
    """受控实验：往文件顶层 `TrailingItemPreferredPositions` 写多种候选状态键
    的停车权重，落盘后返回写回读到的结构（判定 Agent 认哪种键）。

    诊断专用；真正权重表的键是 TrailingItemPreferredPositions（Thaw 源码明确）。
    """
    POS_KEY = "TrailingItemPreferredPositions"
    url = _load_bookmark_url()
    root = _read_whole_plist(url) if url is not None else None
    table = {}
    if isinstance(root, dict) and isinstance(root.get(POS_KEY), dict):
        table = {str(k): v for k, v in root[POS_KEY].items()}
    cands = [
        status_key(owner, identifier),
        status_key(owner, title),
        f"status:{owner}",
        owner,
    ]
    wrote = {}
    for i, k in enumerate(dict.fromkeys(cands)):
        table[k] = HIDDEN_BASE + i
        wrote[k] = table[k]
    ok = write_root_key(POS_KEY, table)
    url2 = _load_bookmark_url()
    root2 = _read_whole_plist(url2) if url2 is not None else None
    after = (root2.get(POS_KEY) if isinstance(root2, dict) else None)
    return {"pos_key": POS_KEY, "write_ok": ok, "wrote": wrote,
            "after": after, "table_path": table_path()}


def write_root_key(key: str, value) -> bool:
    """读整份 plist → 只改顶层某个键 → 写回（保留其它顶层键），并广播。"""
    url = _load_bookmark_url()
    if url is None:
        _log("写顶层键失败：无授权书签")
        return False
    scoped = url.startAccessingSecurityScopedResource()
    try:
        root = _read_whole_plist(url)
        if root is None:
            return False
        if value is None:
            root.pop(key, None)
        else:
            root[key] = value
        blob = plistlib.dumps(root, fmt=plistlib.FMT_BINARY)
        data = NSData.dataWithBytes_length_(blob, len(blob))
        did = data.writeToURL_atomically_(url, True)
        _log(f"写顶层键 {key!r} 完成：落盘={did}")
        return bool(did)
    finally:
        if scoped:
            url.stopAccessingSecurityScopedResource()


def clear_table() -> dict:
    """实验收尾：把实验写过的顶层权重键（menuItemLocations /
    TrailingItemPreferredPositions）整键删除，恢复到未自定义状态。

    仅当这些顶层键是实验新增（原本不存在）时删掉是安全的；其它顶层键不动。
    """
    removed = {}
    for k in ("menuItemLocations", "TrailingItemPreferredPositions"):
        removed[k] = write_root_key(k, None)
    url = _load_bookmark_url()
    root = _read_whole_plist(url) if url is not None else None
    return {"removed": removed, "top_level_keys":
            (list(root.keys()) if isinstance(root, dict) else None),
            "table_path": table_path()}


def cfprefs_write_probe(owner: str, title: str) -> dict:
    """决定性测试：用 CFPreferences（非直写文件）往 group suite 写一个探针
    键→同步→读回，判断 cfprefsd 是否受理第三方进程写这个套件（能则 Agent 会收到
    偏好变更通知），然后删探针。只影响一个临时键，不扰乱现有布局。
    """
    probe_key = "menuItemLocations"
    key = status_key(owner, title)
    before = CFPreferencesCopyValue(CFSTR(probe_key), CFSTR(SUITE),
                                    kCFPreferencesCurrentUser,
                                    kCFPreferencesAnyHost)
    payload = dict(before) if isinstance(before, dict) else {}
    payload = {str(k): v for k, v in payload.items()}
    payload[key] = HIDDEN_BASE
    err = ""
    try:
        CFPreferencesSetValue(CFSTR(probe_key), payload, CFSTR(SUITE),
                              kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
        CFPreferencesSynchronize(CFSTR(SUITE), kCFPreferencesCurrentUser,
                                 kCFPreferencesAnyHost)
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
    readback = CFPreferencesCopyValue(CFSTR(probe_key), CFSTR(SUITE),
                                      kCFPreferencesCurrentUser,
                                      kCFPreferencesAnyHost)
    accepted = isinstance(readback, dict) and key in {str(k) for k in readback.keys()}
    # 回收探针
    try:
        if isinstance(before, dict):
            CFPreferencesSetValue(CFSTR(probe_key), before, CFSTR(SUITE),
                                  kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
        else:
            CFPreferencesSetValue(CFSTR(probe_key), None, CFSTR(SUITE),
                                  kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
        CFPreferencesSynchronize(CFSTR(SUITE), kCFPreferencesCurrentUser,
                                 kCFPreferencesAnyHost)
    except Exception as exc:  # noqa: BLE001
        err += f" | cleanup:{exc}"
    return {"suite": SUITE, "probe_key": probe_key, "wrote": key,
            "cfprefs_accepted": accepted,
            "readback_type": type(readback).__name__,
            "readback_count": (len(readback) if isinstance(readback, dict) else None),
            "before_type": type(before).__name__,
            "error": err}


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
