# -*- coding: utf-8 -*-
"""截图遮罩的跨平台呈现策略。

共享 UI（ui/overlay.py）只调用 start_overlay()，平台差异集中在本模块：
- Windows：保留 Qt.Window（DWM 合成路径），加 WS_EX_TOOLWINDOW 隐藏任务栏项。
- Linux/X11：全屏覆盖 Dock/任务栏，并设置 _NET_WM_STATE_SKIP_TASKBAR 不进 Dock 任务列表。
- Linux/Wayland：全屏；任务栏跳过依赖合成器，失败安全。
所有平台分支失败都不影响遮罩显示。
"""

import os


def start_overlay(widget):
    if os.name == "nt":
        _win_hide_taskbar(widget)
        widget.show()
        return
    wayland = _is_wayland()
    if not wayland:
        _x11_skip_taskbar(widget)
    widget.showFullScreen()
    if not wayland:
        _x11_skip_taskbar(widget)  # map 后再补一次 ClientMessage


def _is_wayland() -> bool:
    from .capture import is_wayland

    return is_wayland()


def _x11_skip_taskbar(widget):
    try:
        from .x11 import set_skip_taskbar

        set_skip_taskbar(int(widget.winId()))
    except Exception:
        pass


def _win_hide_taskbar(widget):
    """Windows：加 WS_EX_TOOLWINDOW，保留 Qt.Window 的 DWM 合成路径。"""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = ctypes.c_void_p(int(widget.winId()))
        gwl_exstyle = -20
        ws_ex_toolwindow = 0x80
        get = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        put = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get.restype = ctypes.c_ssize_t
        put.restype = ctypes.c_ssize_t
        get.argtypes = [ctypes.c_void_p, ctypes.c_int]
        put.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        ex = get(hwnd, gwl_exstyle)
        put(hwnd, gwl_exstyle, ex | ws_ex_toolwindow)
        # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED：立即让样式位生效
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x1 | 0x2 | 0x4 | 0x20)
    except Exception:
        pass
