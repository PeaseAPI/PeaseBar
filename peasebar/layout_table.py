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


def menubar_container_dir() -> str:
    """MenuBarAgent 自己的 group 容器（真权重表很可能就在这里，非 controlcenter）。"""
    return os.path.expanduser("~/Library/Group Containers/com.apple.MenuBar")


def _collect_status_keys(obj, found, _depth=0):
    """递归找形如 status:.../module:... 的键，或名为权重字典的结构。"""
    if _depth > 8:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if ks.startswith("status:") or ks.startswith("module:"):
                found[ks] = (v if isinstance(v, (int, float, str, bool)) else
                             type(v).__name__)
            _collect_status_keys(v, found, _depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _collect_status_keys(v, found, _depth + 1)


def _probe_menubar_container() -> dict:
    """FDA 授权后走普通文件读（不需书签），枚举 com.apple.MenuBar 容器
    里的 plist 并挖出真正的权重表位置/键。写 tmp/menubar_container_dump.json。
    """
    import json
    out = {"base": menubar_container_dir(), "files": [], "plists": [],
           "status_keys": {}}
    base = menubar_container_dir()
    try:
        for root, dirs, files in os.walk(base):
            for fn in files:
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, base)
                out["files"].append(rel)
                if fn.endswith(".plist"):
                    out["plists"].append(rel)
                    try:
                        with open(fp, "rb") as f:
                            data = f.read()
                        parsed = plistlib.loads(data)
                        top = list(parsed.keys()) if isinstance(parsed, dict) else \
                            type(parsed).__name__
                        found = {}
                        _collect_status_keys(parsed, found)
                        out.setdefault("plist_detail", {})[rel] = {
                            "bytes": len(data), "top_keys": top,
                            "status_key_count": len(found)}
                        for kk, vv in found.items():
                            out["status_keys"][kk] = vv
                    except Exception as exc:  # noqa: BLE001
                        out.setdefault("plist_detail", {})[rel] = {
                            "error": str(exc)}
    except (PermissionError, OSError) as oe:
        out["error"] = f"{oe.errno}: {oe.strerror}（FDA 未生效？）"
    try:
        p = os.path.join(os.path.expanduser("~/Project/PeaseBar/tmp"),
                         "menubar_container_dump.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, default=str)
        _log(f"已 probe com.apple.MenuBar 容器 → {p}")
    except Exception as exc:  # noqa: BLE001
        _log(f"容器 probe 写入失败：{exc}")
    return out


def menubar_table_file() -> str | None:
    """容器里真正的布局表 plist 路径（MenuBarAgent 自己的 com.apple.MenuBar.plist）。
    FDA 才能读；找不到返回 None。"""
    hit = None
    try:
        for root, _dirs, files in os.walk(menubar_container_dir()):
            for fn in files:
                if fn == "com.apple.MenuBar.plist":
                    hit = os.path.join(root, fn)
    except OSError:
        return None
    return hit


def container_read_weights() -> dict:
    """读容器真表 TrailingItemPreferredPositions：{状态键: 权重}；不可读返回 {}。"""
    p = menubar_table_file()
    if not p:
        return {}
    try:
        with open(p, "rb") as f:
            parsed = plistlib.loads(f.read())
        t = parsed.get("TrailingItemPreferredPositions")
        if isinstance(t, dict):
            return {str(k): v for k, v in t.items()}
    except Exception as exc:  # noqa: BLE001
        _log(f"读容器真表失败：{exc}")
    return {}


def container_write_weights(updates: dict) -> dict:
    """把 {状态键: 权重} 写进容器真表（值为 None 则删除该键），保留其余顶层键。

    写完必须重启 MenuBarAgent 才会被采纳（在线 Agent 不监听文件变更，真机取证）。
    """
    p = menubar_table_file()
    if not p:
        return {"ok": False, "why": "找不到容器真表（FDA 未生效？）"}
    try:
        with open(p, "rb") as f:
            root = plistlib.loads(f.read())
        t = root.setdefault("TrailingItemPreferredPositions", {})
        for k, v in updates.items():
            if v is None:
                t.pop(k, None)
            else:
                t[str(k)] = v
        blob = plistlib.dumps(root, fmt=plistlib.FMT_BINARY)
        with open(p, "wb") as f:
            f.write(blob)
        return {"ok": True, "path": p, "table_count": len(t)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "why": str(exc)}


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
    # FDA 授权后走普通文件读枚举 com.apple.MenuBar 容器，拿真表键格式。
    try:
        result["menubar_container"] = _probe_menubar_container()
    except Exception as exc:  # noqa: BLE001
        result["menubar_container_error"] = str(exc)
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


# ---------- 真表（com.apple.MenuBar 容器）读写：FDA 正路 ----------

# MenuBarAgent 的权威权重表就在它自己的 group 容器里，顶层只有一个键
# TrailingItemPreferredPositions = {状态键: 位置权重}。FDA 授权后普通文件读
# 即可拿到；写要经 cfprefsd（域 com.apple.MenuBar）才能让在线 Agent 采信。
MENUBAR_SUITE = "com.apple.MenuBar"
POS_TABLE_KEY = "TrailingItemPreferredPositions"


def real_table_path() -> str:
    return os.path.join(menubar_container_dir(),
                        "Library/Preferences/com.apple.MenuBar.plist")


def read_real_table() -> dict:
    """普通文件读真表 TrailingItemPreferredPositions，返回 {状态键: 权重(float/int)}。"""
    try:
        with open(real_table_path(), "rb") as f:
            root = plistlib.loads(f.read())
    except Exception as exc:  # noqa: BLE001
        _log(f"读真表失败：{exc}")
        return {}
    tbl = root.get(POS_TABLE_KEY) if isinstance(root, dict) else None
    return {str(k): v for k, v in tbl.items()} if isinstance(tbl, dict) else {}


def cfprefs_real_table() -> dict:
    """经 CFPreferences（域 com.apple.MenuBar）读同一张表，用于比对与写路径判定。"""
    try:
        val = CFPreferencesCopyValue(CFSTR(POS_TABLE_KEY), CFSTR(MENUBAR_SUITE),
                                     kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
    except Exception as exc:  # noqa: BLE001
        _log(f"CFPreferences 读真表异常：{exc}")
        return {}
    return {str(k): v for k, v in val.items()} if isinstance(val, dict) else {}


def real_probe(live_items) -> dict:
    """决定性诊断：把在线每枚图标 → 真表状态键 → 权重 ↔ 实际 stashed 对齐，
    并比对「文件读 vs CFPreferences 读」是否同源，找出现机真实隐藏阈值。

    live_items：inventory 的 MenuItem 列表（需辅助功能）。结果落
    tmp/real_probe.json。只读不写，安全。
    """
    import json
    file_tbl = read_real_table()
    cf_tbl = cfprefs_real_table()
    keys = list(file_tbl.keys())
    rows = []
    for m in live_items:
        if getattr(m, "is_stash_button", False):
            continue
        key = resolve_key(m, keys)
        w_file = file_tbl.get(key) if key else None
        w_cf = cf_tbl.get(key) if key else None
        rows.append({
            "owner": getattr(m, "owner_bundle_id", ""),
            "label": getattr(m, "label", ""),
            "key": key,
            "w_file": w_file,
            "w_cf": w_cf,
            "stashed": bool(getattr(m, "stashed", False)),
            "on_screen": bool(getattr(m, "is_on_screen", True)),
        })
    vis = [r["w_file"] for r in rows if not r["stashed"] and isinstance(r["w_file"], (int, float))]
    hid = [r["w_file"] for r in rows if r["stashed"] and isinstance(r["w_file"], (int, float))]
    out = {
        "real_table_path": real_table_path(),
        "file_count": len(file_tbl),
        "cf_count": len(cf_tbl),
        "file_eq_cf": (file_tbl == cf_tbl),
        "file_only_keys": [k for k in file_tbl if k not in cf_tbl][:20],
        "cf_only_keys": [k for k in cf_tbl if k not in file_tbl][:20],
        "divider_candidates": {
            k: v for k, v in file_tbl.items()
            if "ControlItem" in k or k.startswith("module:")},
        "visible_weight_min": (min(vis) if vis else None),
        "visible_weight_max": (max(vis) if vis else None),
        "hidden_weight_min": (min(hid) if hid else None),
        "hidden_weight_max": (max(hid) if hid else None),
        "rows": sorted(rows, key=lambda r: (r["w_file"]
                     if isinstance(r["w_file"], (int, float)) else 1e18)),
    }
    try:
        p = os.path.join(os.path.expanduser("~/Project/PeaseBar/tmp"),
                         "real_probe.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, default=str)
        _log(f"已 probe 真表↔在线 → {p}")
    except Exception as exc:  # noqa: BLE001
        out["dump_error"] = str(exc)
    return out


def cfprefs_suite_write_probe() -> dict:
    """测：CFPreferences 写域 com.apple.MenuBar 是否被 cfprefsd 受理（能则在线
    Agent 会收到偏好变更并采信），用无害探针键，写完立即回收。"""
    probe = "__peasebar_probe__"
    err = ""
    try:
        CFPreferencesSetValue(CFSTR(probe), 1, CFSTR(MENUBAR_SUITE),
                              kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
        CFPreferencesSynchronize(CFSTR(MENUBAR_SUITE), kCFPreferencesCurrentUser,
                                 kCFPreferencesAnyHost)
    except Exception as exc:  # noqa: BLE001
        err = f"set:{exc}"
    back = CFPreferencesCopyValue(CFSTR(probe), CFSTR(MENUBAR_SUITE),
                                  kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
    accepted = back == 1
    try:
        CFPreferencesSetValue(CFSTR(probe), None, CFSTR(MENUBAR_SUITE),
                              kCFPreferencesCurrentUser, kCFPreferencesAnyHost)
        CFPreferencesSynchronize(CFSTR(MENUBAR_SUITE), kCFPreferencesCurrentUser,
                                 kCFPreferencesAnyHost)
    except Exception as exc:  # noqa: BLE001
        err += f" | cleanup:{exc}"
    return {"suite": MENUBAR_SUITE, "cfprefs_accepted": accepted,
            "readback": back, "error": err}


def write_real_table(table: dict) -> bool:
    """直写群容器真表文件（FDA）：只换顶层 TrailingItemPreferredPositions，
    其余顶层键不动。写前先读一次合并，避免覆盖 Agent 之间新写的项。"""
    try:
        with open(real_table_path(), "rb") as f:
            root = plistlib.loads(f.read())
    except Exception as exc:  # noqa: BLE001
        _log(f"写真表前读失败：{exc}")
        return False
    if not isinstance(root, dict):
        root = {}
    root[POS_TABLE_KEY] = dict(table)
    blob = plistlib.dumps(root, fmt=plistlib.FMT_BINARY)
    tmp = real_table_path() + ".peasebar.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, real_table_path())
        _log(f"直写真表完成：{len(table)} 条")
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"直写真表失败：{exc}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _stashed_of(owner, title) -> dict:
    """从在线清单里按 owner/label 找一枚图标，返回 {found, stashed, on_screen}。"""
    try:
        from peasebar import inventory
        items = inventory.list_items()[0]
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    o = _norm(owner)
    t = _norm(title)
    for m in items:
        if _norm(getattr(m, "owner_bundle_id", "")) != o:
            continue
        lab = _norm(getattr(m, "label", ""))
        if t and t not in lab and lab and lab not in t:
            continue
        return {"found": True, "label": getattr(m, "label", ""),
                "stashed": bool(getattr(m, "stashed", False)),
                "on_screen": bool(getattr(m, "is_on_screen", True)),
                "x": (round(m.frame[0], 1) if getattr(m, "frame", None) else None)}
    return {"found": False}


class _KeyProbe:
    """给 resolve_key 用的最小化假 item（只需 owner/label）。"""
    def __init__(self, owner, label):
        self.owner_bundle_id = owner
        self.label = label
        self.key_part = label


def real_hide_test(owner: str, ident: str, title: str, weight) -> dict:
    """决定性实验：往「正确的」群容器真表直写一枚图标的权重，等在线 Agent
    反应，再用 AX 重新读它的 stashed 变化。只改一枚目标键，写完自动还原。

    weight 为 None 时只测「回写原值」能否推动 Agent（验证写入链）。"""
    import time
    tbl = read_real_table()
    # 先洗掉残留的实验脏数据：值为 None 或键里带实验标记的
    tbl = {k: v for k, v in tbl.items()
           if v is not None and "__REALHIDE__" not in k
           and "__peasebar" not in k.lower()}
    keys = list(tbl.keys())
    key = resolve_key(_KeyProbe(owner, title), keys) or status_key(owner, ident)
    orig = tbl.get(key)
    before = _stashed_of(owner, title)
    probe = dict(tbl)
    probe[key] = (orig if weight is None else weight)
    wrote = write_real_table(probe)
    time.sleep(18.0)  # 不重启 Agent，只等足够久，测在线 Agent 是否会自己重读表
    after_tbl = read_real_table()
    after = _stashed_of(owner, title)
    # 还原（无论之前成没成，尽量回到原状）
    if orig is not None:
        restore = dict(after_tbl)
        restore[key] = orig
        write_real_table(restore)
    return {"key": key, "orig_weight": orig, "target_weight": probe[key],
            "write_ok": wrote, "weight_in_file_after": after_tbl.get(key),
            "agent_kept_our_write": (after_tbl.get(key) == probe[key]),
            "before": before, "after": after}


def _relaunch_menu_bar_agent() -> bool:
    """杀掉 MenuBarAgent（launchd 会自动重拉），迫使它重读真表。

    只重启系统菜单栏代理，不重启目标 App（用户不反感的只是重启目标 App）。"""
    import subprocess
    try:
        subprocess.run(["/usr/bin/pkill", "-x", "MenuBarAgent"], check=False)
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"重启 MenuBarAgent 异常：{exc}")
        return False


def _wait_inventory(timeout=12.0):
    """轮询等 MenuBarAgent 重拉、图标重新上线（至少 5 枚）；返回最大一次条数。"""
    import time
    from peasebar import inventory
    deadline = time.time() + timeout
    best = 0
    while time.time() < deadline:
        try:
            items = inventory.list_items()[0]
            n = sum(1 for m in items
                    if not getattr(m, "is_stash_button", False))
            best = max(best, n)
            if n >= 5:
                return n
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return best


def real_hide_agent_test(owner: str, ident: str, title: str, weight) -> dict:
    """决定性实验：往真表永久写一枚目标权重→重启 MenuBarAgent 重载→
    看（a）重载后文件里我们的值是否保留（表是否权威），（b）目标图标是否移动/隐藏。

    测完自动还原原值并再次重载，尽量回到原状。"""
    import time
    tbl = read_real_table()
    tbl = {k: v for k, v in tbl.items()
           if v is not None and "__REAL" not in k and "__peasebar" not in k.lower()}
    key = resolve_key(_KeyProbe(owner, title), list(tbl.keys())) or status_key(owner, ident)
    orig = tbl.get(key)
    before = _stashed_of(owner, title)
    probe = dict(tbl)
    probe[key] = weight
    wrote = write_real_table(probe)
    _relaunch_menu_bar_agent()
    time.sleep(2.0)
    seen = _wait_inventory(12.0)
    after_tbl = read_real_table()
    after = _stashed_of(owner, title)
    result = {"key": key, "orig_weight": orig, "target_weight": weight,
              "write_ok": wrote, "items_after_reload": seen,
              "weight_after_reload": after_tbl.get(key),
              "agent_reload_kept_our_value": (after_tbl.get(key) == weight),
              "before": before, "after": after,
              "moved_x": (before.get("x") != after.get("x")),
              "now_stashed": after.get("stashed")}
    # 还原原值并再重载一次，回到原状
    if orig is not None:
        restore = dict(read_real_table())
        restore[key] = orig
        write_real_table(restore)
        _relaunch_menu_bar_agent()
    return result


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
