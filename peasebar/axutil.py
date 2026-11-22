#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AX（辅助功能）基础封装。

全部方法为本会话在 macOS 27 上实测可用的调用模式（见 docs/DEVELOPMENT.md §5）：
- 属性读取统一走 AXUIElementCopyAttributeValue；
- AXValue 用 AXValueGetValue(value, type, None) 解码（PyObjC 自动出 CGPoint/CGSize）；
- MenuBarAgent 与第三方 App 上报的坐标均为全局 CG 坐标（左上原点，y 向下）。
"""
import ApplicationServices as AS


def copy_attr(el, attr):
    """读取一个 AX 属性，返回 (err, value)，失败时 value 为 None。"""
    try:
        return AS.AXUIElementCopyAttributeValue(el, attr, None)
    except Exception:
        return -1, None


def _as_list(val):
    """把 PyObjC 返回值统一转成 Python list。

    关键怪癖：AX 数组在 PyObjC 里是 __NSArrayM/NSMutableArray，不是 Python list，
    isinstance(x, (list, tuple)) 判不出来；不可迭代的 AXUIElementRef 则视为单元素。
    """
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return list(val)
    try:
        return list(val)  # NSArray/NSMutableArray 等可迭代对象
    except TypeError:
        return [val]      # 单元素（如 AXUIElementRef）


def copy_children(el, attr):
    """读取某属性下的子元素数组。

    实测结构三种（T6 扩展）：① 数组（__NSArrayM）；② 单容器元素（如
    AXExtrasMenuBar → AXMenuBar，需下钻一层）；③ 同一结构在不同时刻可能返回
    空树（MenuBarAgent 懒加载），由调用方重试。单元素按角色分流：容器角色
    （AXMenuBar/AXGroup/AXMenu）才下钻，其余视为单项。
    """
    err, val = copy_attr(el, attr)
    if err != 0 or val is None:
        return err, []
    if isinstance(val, (list, tuple)):
        return err, _as_list(val)
    try:
        iter(val)
        return err, _as_list(val)  # 可迭代：就是数组
    except TypeError:
        pass
    role = element_role(val)
    if role in ("AXMenuBar", "AXGroup", "AXMenu"):
        err2, kids = copy_attr(val, "AXChildren")
        if err2 != 0 or kids is None:
            return err, []
        return err, _as_list(kids)
    return err, [val]


def decode_value(val, kind):
    """解码 AXValueRef；kind 传 kAXValueCGPointType / kAXValueCGSizeType。"""
    if val is None:
        return None
    ok, v = AS.AXValueGetValue(val, kind, None)
    return v if ok else None


def element_frame(el):
    """返回元素矩形 (x, y, w, h)（全局 CG 坐标），失败返回 None。"""
    _, pos = copy_attr(el, "AXPosition")
    _, size = copy_attr(el, "AXSize")
    if pos is None or size is None:
        return None
    p = decode_value(pos, AS.kAXValueCGPointType)
    s = decode_value(size, AS.kAXValueCGSizeType)
    if p is None or s is None:
        return None
    return (p.x, p.y, s.width, s.height)


def element_string(el, attr):
    """读取字符串型 AX 属性（AXTitle/AXDescription 等），失败返回 None。"""
    err, val = copy_attr(el, attr)
    if err != 0 or val is None:
        return None
    return str(val)


def element_role(el):
    """读取元素角色（AXRole）。"""
    return element_string(el, "AXRole")


def perform_press(el):
    """对元素执行 AXPress 动作，返回是否成功。"""
    return AS.AXUIElementPerformAction(el, "AXPress") == 0


def app_element_for_pid(pid):
    """取某进程的 AX 应用元素。"""
    return AS.AXUIElementCreateApplication(pid)


def element_actions(el):
    """列出元素支持的动作名。"""
    try:
        err, names = AS.AXUIElementCopyActionNames(el, None)
        if err != 0 or names is None:
            return []
        return [str(n) for n in names]
    except Exception:
        return []


def notch_region(screen):
    """计算给定 NSScreen 的刘海区 (x0, x1)（全局 CG 坐标）；无刘海返回 None。

    依据 T7：auxiliaryTopLeftArea/auxiliaryTopRightArea 拼不满整行即为有刘海；
    macOS 27 的 safeAreaInsets 不再报告左右内缩，不能使用。
    """
    aux_l = screen.auxiliaryTopLeftArea()
    aux_r = screen.auxiliaryTopRightArea()
    f = screen.frame()
    left_end = aux_l.origin.x + aux_l.size.width
    # 左右辅助区已相接（或超出）说明无刘海
    if left_end >= aux_r.origin.x - 0.5:
        return None
    return (left_end, aux_r.origin.x)


def rect_intersects(frame, x0, x1):
    """判断图标矩形（x, y, w, h）是否落入刘海横向区间。"""
    if frame is None:
        return False
    ix0, _, iw, _ = frame
    if iw <= 0:  # 零宽/异常宽度（AX 偶发异常 frame）不构成相交，否则空集误报
        return False
    ix1 = ix0 + iw
    return ix0 < x1 and ix1 > x0
