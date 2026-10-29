# -*- coding: utf-8 -*-
"""Linux 全局热键（X11：XGrabKey；Wayland 上自动跳过，改用 DE 自定义快捷键）。"""

import contextlib
import os
import threading
from typing import ClassVar

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from ..i18n import tr
from ..utils.logger import get_logger

log = get_logger()

_MODNAME = {"ctrl": 4, "control": 4, "alt": 8, "shift": 1, "meta": 64, "win": 64, "super": 64}
_MOD2 = 0x10  # NumLock
_LOCK = 0x02  # CapsLock
_KEYPRESS = 2


class HotkeyManager(QObject):
    activated = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._stop = threading.Event()
        self._current = ""

    def register(self, seq_text: str) -> bool:
        self.unregister()
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or (
            os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY")
        ):
            log.info("Wayland 会话，跳过 X11 热键")
            return False
        if not seq_text or not seq_text.strip():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._x11_loop, args=(seq_text,), daemon=True)
        self._thread.start()
        self._current = seq_text
        return True

    def unregister(self):
        self._stop.set()

    def current(self):
        return self._current

    @pyqtSlot()
    def _fire(self):
        self.activated.emit()

    # ---- 内部 ----
    def _x11_loop(self, seq_text):
        import ctypes

        X11Error = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_char))

        try:
            x11 = ctypes.CDLL("libX11.so.6")
        except OSError as e:
            self.error.emit(tr("hotkey_x11_fail") + ": %s" % e)
            return
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XStringToKeysym.restype = ctypes.c_ulong
        x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x11.XKeysymToKeycode.restype = ctypes.c_ubyte
        x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XGrabKey.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_ulong,
            ctypes.c_bool,
            ctypes.c_int,
            ctypes.c_int,
        ]
        x11.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
        x11.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        x11.XSetErrorHandler.restype = ctypes.c_int
        x11.XSetErrorHandler.argtypes = [X11Error]

        dpy = x11.XOpenDisplay(None)
        if not dpy:
            self.error.emit(tr("hotkey_no_display"))
            return
        root = x11.XDefaultRootWindow(dpy)

        parts = [p for p in seq_text.replace(" ", "").split("+") if p]
        mods = 0
        keyname = parts[-1] if parts else ""
        for p in parts[:-1]:
            mods |= _MODNAME.get(p.lower(), 0)
        keysym = x11.XStringToKeysym(keyname.encode())
        keycode = x11.XKeysymToKeycode(dpy, keysym) if keysym else 0
        if not keycode:
            x11.XCloseDisplay(dpy)
            self.error.emit(tr("hotkey_unsupported") + ": " + seq_text)
            return

        # 吞掉 BadAccess（热键被占用时）
        err_flag = {"bad": 0}

        @X11Error
        def _handler(_dpy, _ev):
            err_flag["bad"] += 1
            return 0

        x11.XSetErrorHandler(_handler)

        variants = (mods, mods | _MOD2, mods | _LOCK, mods | _MOD2 | _LOCK)
        for m in variants:
            x11.XGrabKey(dpy, keycode, m, root, True, 0, 1)  # GrabModeAsync=0/1
        x11.XSync(dpy, False)
        if err_flag["bad"]:
            for m in variants:
                with contextlib.suppress(Exception):
                    x11.XUngrabKey(dpy, keycode, m, root)
            x11.XCloseDisplay(dpy)
            self.error.emit(tr("hotkey_conflict"))
            return

        x11.XSelectInput(dpy, root, 0x2)  # KeyPressMask
        x11.XSync(dpy, False)

        class XKeyEvent(ctypes.Structure):
            _fields_: ClassVar = [
                ("type", ctypes.c_int),
                ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong),
                ("root", ctypes.c_ulong),
                ("subwindow", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("x", ctypes.c_int),
                ("y", ctypes.c_int),
                ("x_root", ctypes.c_int),
                ("y_root", ctypes.c_int),
                ("state", ctypes.c_uint),
                ("keycode", ctypes.c_ubyte),
                ("same_screen", ctypes.c_int),
            ]

        from PyQt5.QtCore import QMetaObject
        from PyQt5.QtCore import Qt as QtEnum

        ev = XKeyEvent()
        p_ev = ctypes.byref(ev)
        while not self._stop.is_set():
            x11.XNextEvent(dpy, p_ev)
            if ev.type == _KEYPRESS and ev.keycode == keycode:
                QMetaObject.invokeMethod(self, "_fire", QtEnum.QueuedConnection)
        for m in variants:
            x11.XUngrabKey(dpy, keycode, m, root)
        x11.XCloseDisplay(dpy)
        log.info("X11 热键已注销: %s", seq_text)
