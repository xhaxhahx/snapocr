# -*- coding: utf-8 -*-
"""窗口/控件自动识别：返回屏幕坐标(物理像素)下最顶层可见窗口（含子窗口控件）的矩形。

仅 Windows 实现；其他平台返回 None（框选退化为手动拖拽）。
排除：自身进程、不可见/最小化/被 DWM cloaked 的窗口。
控件级：在命中的顶层窗口内用 RealChildWindowFromPoint 逐层下钻
（对原生 Win32 控件生效；对自绘界面如 Qt/Electron 退化为窗口级）。
"""

import ctypes
import ctypes.wintypes as wt
import os

IS_WIN = os.name == "nt"

DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9
MAX_CHILD_DEPTH = 8


def _is_cloaked(hwnd):
    try:
        v = ctypes.c_uint(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), 4)
        return v.value != 0
    except Exception:
        return False


def _frame_rect(hwnd):
    """优先 DWM 扩展边界（不含不可见阴影边框），失败用 GetWindowRect。"""
    r = wt.RECT()
    try:
        res = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)
        )
        if res == 0 and r.right > r.left and r.bottom > r.top:
            return r
    except Exception:
        # DWM 查询失败（无 DWM/权限不足）：回落 GetWindowRect
        pass
    user32 = ctypes.windll.user32
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def _top_window_at(x_phys, y_phys, min_size=40):
    """返回包含物理坐标点的最顶层普通窗口 HWND（按 z 序），无则 None。"""
    if not IS_WIN:
        return None
    user32 = ctypes.windll.user32
    my_pid = os.getpid()
    pt = wt.POINT(int(x_phys), int(y_phys))
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _l):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == my_pid:
            return True
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if _is_cloaked(hwnd):
            return True
        # 跳过无边框工具窗（托盘/提示类）
        ex = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        if ex & 0x80:  # WS_EX_TOOLWINDOW
            return True
        r = _frame_rect(hwnd)
        if r.right - r.left < min_size or r.bottom - r.top < min_size:
            return True
        if not (r.left <= pt.x <= r.right and r.top <= pt.y <= r.bottom):
            return True
        found.append(hwnd)
        return False  # EnumWindows 按 z 序，第一个命中即停

    try:
        user32.EnumWindows(cb, 0)
    except Exception:
        return None
    return found[0] if found else None


def _descend_child(hwnd, pt_screen):
    """在顶层窗口内按屏幕坐标下钻子窗口控件（RealChildWindowFromPoint）。"""
    user32 = ctypes.windll.user32
    cur = hwnd
    for _ in range(MAX_CHILD_DEPTH):
        cpt = wt.POINT(pt_screen.x, pt_screen.y)
        user32.ScreenToClient(cur, ctypes.byref(cpt))
        child = user32.RealChildWindowFromPoint(cur, cpt)
        if not child or child == cur:
            break
        cur = child
    return cur if cur != hwnd else None


def descend_rect_at(x_phys, y_phys, min_size=24):
    """控件级识别：顶层窗口 → 子窗口控件下钻，返回最终矩形，无则 None。"""
    if not IS_WIN:
        return None
    hwnd = _top_window_at(x_phys, y_phys, min_size)
    if not hwnd:
        return None
    r = _frame_rect(hwnd)
    x1, y1, x2, y2 = r.left, r.top, r.right, r.bottom
    user32 = ctypes.windll.user32
    cur = hwnd
    for _ in range(MAX_CHILD_DEPTH):
        cpt = wt.POINT(int(x_phys), int(y_phys))
        user32.ScreenToClient(cur, ctypes.byref(cpt))
        child = user32.RealChildWindowFromPoint(cur, cpt)
        if not child or child == cur:
            break
        cr = _frame_rect(child)
        if cr.right - cr.left < min_size or cr.bottom - cr.top < min_size:
            break
        if not (cr.left <= x_phys <= cr.right and cr.top <= y_phys <= cr.bottom):
            break
        cur, (x1, y1, x2, y2) = child, (cr.left, cr.top, cr.right, cr.bottom)
    # 控件矩形至少要比整窗小才算"更精细"
    if (x1, y1, x2, y2) == (r.left, r.top, r.right, r.bottom):
        return (r.left, r.top, r.right, r.bottom)
    if x2 - x1 < min_size or y2 - y1 < min_size:
        return (r.left, r.top, r.right, r.bottom)
    return (x1, y1, x2, y2)
