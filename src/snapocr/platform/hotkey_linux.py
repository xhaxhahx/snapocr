# -*- coding: utf-8 -*-
"""Linux 全局热键（X11：XGrabKey；Wayland 上自动跳过，改用 DE 自定义快捷键）。"""

import contextlib
import ctypes
import os
import select
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


class XKeyEvent(ctypes.Structure):
    """X11 按键事件（XEvent 联合体布局）。

    XNextEvent 按**完整 XEvent 联合体**整块写入，64 位下为 192 字节；本结构体
    主体仅 ~96 字节，必须补足 pad —— 否则每收到一次按键事件就越界写堆
    96 字节，堆元数据被破坏后进程在下一次 Python 分配时段错误
    （2026-11-13 用户实测：设置热键后按热键必闪退，两份 coredump 栈均落在
    热键槽内的普通分配处）。补足写法与 x11.py 的 _XClientMessageEvent 一致。
    """

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
        # 补足到 XEvent 联合体大小（64 位 192 字节）：XNextEvent 整块写入
        ("pad", ctypes.c_long * 12),
    ]


class _XDisplayHead(ctypes.Structure):
    """_XDisplay 头部布局（XlibInt.h）：fd 位于 LP64 下偏移 16。

    Xlib 没有导出 ConnectionNumber 函数（C 里是宏，直接读结构体字段），
    ctypes 只能按结构布局取。该布局自 X11R6 起稳定未变。
    """

    _fields_: ClassVar = [
        ("ext_data", ctypes.c_void_p),
        ("private1", ctypes.c_void_p),
        ("fd", ctypes.c_int),
    ]


def _display_fd(dpy) -> int:
    """从 Display 指针读出连接 fd（供 select 轮询用）。"""
    return ctypes.cast(dpy, ctypes.POINTER(_XDisplayHead)).contents.fd


class HotkeyManager(QObject):
    activated = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._stop = threading.Event()
        self._current = ""
        self._grab_done = threading.Event()  # 抓取结果握手：线程启动后置位一次
        self._grab_ok = False

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
        self._grab_done.clear()
        self._grab_ok = False
        self._thread = threading.Thread(target=self._x11_loop, args=(seq_text,), daemon=True)
        self._thread.start()
        # 等待抓取结果（XGrabKey+XSync 毫秒级完成；超时仅为连接异常兜底）。
        # 此前直接 return True，组合键被占用时 UI 已提示但状态却记成已生效。
        if not self._grab_done.wait(timeout=3.0):
            log.warning("热键抓取结果超时: %s", seq_text)
            return False
        if not self._grab_ok:
            # 改键失败回滚（与 Windows 侧 hotkey_win 语义对齐，P2-07 就此关闭）：
            # 旧热键已在 unregister 中被真正注销，不回滚则本会话热键彻底失效。
            prev = self._current
            self._current = ""  # 置空防递归回滚
            if prev and prev != seq_text:
                self.register(prev)
            return False
        self._current = seq_text
        return True

    def unregister(self):
        self._stop.set()
        t = self._thread
        self._thread = None
        if t is not None and t.is_alive() and t is not threading.current_thread():
            # X11 线程的 select 循环 ≤120ms 醒一次检查 _stop，这里等待其
            # ungrab + 关闭连接。此前只 set 事件不等待：旧线程阻塞在
            # XNextEvent 永不退出，旧抓取一直生效（"改键后旧热键仍可用"
            # 且线程泄漏，P2-07）。
            t.join(timeout=2.0)

    def current(self):
        return self._current

    @pyqtSlot()
    def _fire(self):
        self.activated.emit()

    # ---- 内部 ----
    def _x11_loop(self, seq_text):
        X11Error = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_char))

        try:
            x11 = ctypes.CDLL("libX11.so.6")
        except OSError as e:
            self.error.emit(tr("hotkey_x11_fail") + ": %s" % e)
            self._grab_done.set()  # 失败也置位：register 的握手不能永远等
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
        x11.XPending.restype = ctypes.c_int
        x11.XPending.argtypes = [ctypes.c_void_p]
        x11.XSetErrorHandler.restype = ctypes.c_int
        x11.XSetErrorHandler.argtypes = [X11Error]

        dpy = x11.XOpenDisplay(None)
        if not dpy:
            self.error.emit(tr("hotkey_no_display"))
            self._grab_done.set()
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
            self._grab_done.set()
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
            self._grab_done.set()
            return

        x11.XSelectInput(dpy, root, 0x2)  # KeyPressMask
        x11.XSync(dpy, False)
        self._grab_ok = True
        self._grab_done.set()

        from PyQt5.QtCore import QMetaObject
        from PyQt5.QtCore import Qt as QtEnum

        ev = XKeyEvent()  # 模块级定义：已补足到 XEvent 联合体完整大小
        p_ev = ctypes.byref(ev)
        fd = _display_fd(dpy)
        while not self._stop.is_set():
            # select 超时轮询而非直接阻塞在 XNextEvent：让线程能响应 _stop
            # （unregister 需在 ≤120ms 内真正注销抓取并退出，P2-07）
            try:
                ready, _, _ = select.select([fd], [], [], 0.12)
            except (OSError, ValueError):
                break  # 连接已断（如注销期间 X 退出）：走下方收尾
            if not ready:
                continue
            while not self._stop.is_set() and x11.XPending(dpy):
                x11.XNextEvent(dpy, p_ev)
                if ev.type == _KEYPRESS and ev.keycode == keycode:
                    QMetaObject.invokeMethod(self, "_fire", QtEnum.QueuedConnection)
        for m in variants:
            x11.XUngrabKey(dpy, keycode, m, root)
        x11.XCloseDisplay(dpy)
        log.info("X11 热键已注销: %s", seq_text)
