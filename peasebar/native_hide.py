#!/usr/bin/env python3.14
"""用 macOS 私有框架 MenuBarClientCore.MBMenuBarItemManager 真正驱动菜单栏图标显隐。

这是 PeaseBar 隐藏引擎的核心：不再用「合成 ⌘-拖」那套做不到的老办法，
而是像 Thaw 的 PlatformRuntimeKit 一样，直接调用系统私有 ObjC API。

pyobjc 这个版本无法桥接「无元数据的 block 方法」，所以这里用 ctypes
手工构造 ObjC block + objc_msgSend 直接调用，绕开该限制。
"""
from __future__ import annotations

import ctypes
import ctypes.util

import objc
from Foundation import NSBundle

_FRAMEWORK = "/System/Library/PrivateFrameworks/MenuBarClientCore.framework"
_manager_cls = None


def _ensure_loaded():
    """加载私有框架并拿到 MBMenuBarItemManager 类；失败返回 None。"""
    global _manager_cls
    if _manager_cls is not None:
        return _manager_cls
    bundle = NSBundle.bundleWithPath_(_FRAMEWORK)
    if not bundle or not bundle.load():
        return None
    try:
        _manager_cls = objc.lookUpClass("MBMenuBarItemManager")
    except objc.nosuchclass_error:
        _manager_cls = None
    return _manager_cls


def is_available() -> bool:
    """本机是否存在这套私有 API（系统升级后可能变动）。"""
    return _ensure_loaded() is not None


class _BlockDesc(ctypes.Structure):
    _fields_ = [
        ("reserved", ctypes.c_ulong),
        ("size", ctypes.c_ulong),
        ("signature", ctypes.c_char_p),
    ]


class _BlockLayout(ctypes.Structure):
    _fields_ = [
        ("isa", ctypes.c_void_p),
        ("flags", ctypes.c_int),
        ("reserved", ctypes.c_int),
        ("invoke", ctypes.c_void_p),
        ("descriptor", ctypes.c_void_p),
    ]


# void(^)(BOOL) 的 block invoke 约定：C 函数 (block_self, BOOL)
_BLOCK_INVOKE_T = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_bool)
_BLOCK_IS_GLOBAL = 1 << 28
_BLOCK_HAS_SIGNATURE = 1 << 30


def _make_bool_block(callback):
    """把 Python 可调用包成 ObjC 的 void(^)(BOOL) block。

    返回 (block_struct, keepalive_tuple)；调用方须持有 keepalive 直到调用完成，
    否则 block 及其 invoke 闭包会被 GC 回收导致崩溃。
    """
    libobjc = ctypes.CDLL(ctypes.util.find_library("objc"))

    def _invoke(_self, value):
        try:
            callback(bool(value))
        except Exception:
            pass

    invoke = _BLOCK_INVOKE_T(_invoke)
    desc = _BlockDesc(0, ctypes.sizeof(_BlockDesc), b"v20@?0B8")
    isa = ctypes.c_void_p.in_dll(libobjc, "_NSConcreteGlobalBlock")
    blk = _BlockLayout(
        isa.value,
        _BLOCK_IS_GLOBAL | _BLOCK_HAS_SIGNATURE,
        0,
        ctypes.cast(invoke, ctypes.c_void_p),
        ctypes.cast(ctypes.byref(desc), ctypes.c_void_p),
    )
    return blk, (invoke, desc, isa, libobjc)


def _msg_send(obj_ptr, selector_name, bool_arg, block_ptr):
    """objc_msgSend(id, SEL, BOOL, block) —— 用于 setXxx:completionHandler: 形态。"""
    libobjc = ctypes.CDLL(ctypes.util.find_library("objc"))
    libobjc.sel_registerName.restype = ctypes.c_void_p
    libobjc.sel_registerName.argtypes = [ctypes.c_char_p]
    sel = libobjc.sel_registerName(selector_name.encode())
    msg = libobjc.objc_msgSend
    msg.restype = ctypes.c_void_p
    msg.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p]
    msg(obj_ptr, sel, bool_arg, block_ptr)


class MenuBarManager:
    """对 MBMenuBarItemManager 的薄封装。"""

    def __init__(self):
        cls = _ensure_loaded()
        if cls is None:
            raise RuntimeError("MenuBarClientCore / MBMenuBarItemManager 不可用")
        self._mgr = cls.new()
        self._ptr = ctypes.c_void_p(objc.pyobjc_id(self._mgr))

    def set_globally_hidden(self, hidden: bool, callback=None) -> None:
        """整排菜单栏 extras 的全局收纳开关（已真机验证系统受理、回调返回成功）。

        注意：这是全局开关，不是逐枚隐藏；逐枚隐藏用 set_items(...)。
        """
        blk, keep = _make_bool_block(callback or (lambda ok: None))
        _msg_send(self._ptr, "setGloballyHidden:completionHandler:", hidden,
                  ctypes.cast(ctypes.byref(blk), ctypes.c_void_p))
        # keep 必须活到本次调用被系统处理；调用方通过 run_loop 驱动回调。
        self._keep = keep
        self._blk = blk
