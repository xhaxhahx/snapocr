# -*- coding: utf-8 -*-
"""X11/EWMH 小工具：让全屏遮罩跳过任务栏（不进 Dock 的任务列表）。

PyQt5 没有暴露 _NET_WM_STATE_SKIP_TASKBAR，这里用 libX11 直接设置：
- 先写窗口属性（map 前生效）；
- 再向 root 发送 _NET_WM_STATE ClientMessage（map 后补充，兼容只认消息的 WM）。
失败安全：任何异常都返回 False，调用方继续显示遮罩即可。
"""

import ctypes
import os
from typing import ClassVar

_CLIENT_MESSAGE = 33
_SUBSTRUCTURE_REDIRECT_MASK = 1 << 19
_SUBSTRUCTURE_NOTIFY_MASK = 1 << 20
_XA_ATOM = 4
_PROP_MODE_REPLACE = 0
_NET_WM_STATE_ADD = 1


class _XClientMessageEvent(ctypes.Structure):
    _fields_: ClassVar = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
        # XEvent 联合体在 64 位下为 192 字节；补足避免 XSendEvent 越界读取
        ("pad", ctypes.c_long * 12),
    ]


def set_skip_taskbar(win_id: int, mapped: bool = False) -> bool:
    """给指定 X11 窗口设置 _NET_WM_STATE_SKIP_TASKBAR；成功返回 True。

    mapped=False：map 前写初始属性（此时窗口还没有 WM 状态，可安全 Replace）。
    mapped=True ：map 后只能发 ClientMessage ADD；若再 Replace 属性会把
                  WM 刚设置的 _NET_WM_STATE_FULLSCREEN 一并冲掉，窗口退化为
                  可用区 1035 高的最大化窗口，出现"双任务栏"（2026-10-29 用户实测）。
    """
    if os.name == "nt" or not win_id:
        return False
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XChangeProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_int,
        ]
        x11.XSendEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_long,
            ctypes.c_void_p,
        ]
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

        dpy = x11.XOpenDisplay(None)
        if not dpy:
            return False
        try:
            root = x11.XDefaultRootWindow(dpy)
            wm_state = x11.XInternAtom(dpy, b"_NET_WM_STATE", 0)
            skip = x11.XInternAtom(dpy, b"_NET_WM_STATE_SKIP_TASKBAR", 0)
            if not wm_state or not skip:
                return False
            if not mapped:
                state = (ctypes.c_ulong * 1)(skip)
                x11.XChangeProperty(
                    dpy, win_id, wm_state, _XA_ATOM, 32, _PROP_MODE_REPLACE, state, 1
                )
            ev = _XClientMessageEvent()
            ev.type = _CLIENT_MESSAGE
            ev.display = dpy
            ev.window = win_id
            ev.message_type = wm_state
            ev.format = 32
            ev.data[0] = _NET_WM_STATE_ADD
            ev.data[1] = skip
            ev.data[2] = 0
            ev.data[3] = 1  # source indication: normal application
            x11.XSendEvent(
                dpy,
                root,
                0,
                _SUBSTRUCTURE_REDIRECT_MASK | _SUBSTRUCTURE_NOTIFY_MASK,
                ctypes.byref(ev),
            )
            x11.XSync(dpy, 0)
            return True
        finally:
            x11.XCloseDisplay(dpy)
    except Exception:
        return False
