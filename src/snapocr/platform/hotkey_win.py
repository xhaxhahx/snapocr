# -*- coding: utf-8 -*-
"""Windows 全局热键：RegisterHotKey + 原生事件过滤器。"""

import contextlib
import ctypes
import ctypes.wintypes as wt

from PyQt5.QtCore import QAbstractNativeEventFilter, QObject, Qt, pyqtSignal

WM_HOTKEY = 0x0312
HOTKEY_ID = 1001  # RegisterHotKey 的 id（遮罩模块常量，过滤器与管理器共用）
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000

_MOD_NAME = {Qt.META: MOD_WIN, Qt.CTRL: MOD_CONTROL, Qt.ALT: MOD_ALT, Qt.SHIFT: MOD_SHIFT}


def _vk_for_key(key: int):
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return int(key) - int(Qt.Key_F1) + 0x70
    if ord("A") <= key <= ord("Z"):
        return key
    if ord("0") <= key <= ord("9"):
        return key
    simple = {
        Qt.Key_Space: 0x20,
        Qt.Key_Return: 0x0D,
        Qt.Key_Tab: 0x09,
        Qt.Key_Minus: 0xBD,
        Qt.Key_Equal: 0xBB,
        Qt.Key_BracketLeft: 0xDB,
        Qt.Key_BracketRight: 0xDD,
        Qt.Key_Semicolon: 0xBA,
        Qt.Key_Apostrophe: 0xDE,
        Qt.Key_Comma: 0xBC,
        Qt.Key_Period: 0xBE,
        Qt.Key_Slash: 0xBF,
    }
    return simple.get(key)


class WinHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            try:
                msg = wt.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self._cb()
                    return True, 0
            except Exception:
                # 消息结构解析失败（非本进程消息）：按未处理返回
                pass
        return False, 0


class HotkeyManager(QObject):
    activated = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter = None
        self._current = ""

    def register(self, seq_text: str) -> bool:
        self.unregister()
        ks = seq_text.strip()
        if not ks:
            return False
        from PyQt5.QtGui import QKeySequence

        qseq = QKeySequence(ks)
        if not qseq.count():
            self.error.emit("无效快捷键: " + ks)
            return False
        key = qseq[0]
        mods_map = {
            Qt.CTRL: MOD_CONTROL,
            Qt.ALT: MOD_ALT,
            Qt.SHIFT: MOD_SHIFT,
            Qt.META: MOD_WIN,
        }
        m = 0
        # PyQt5 中 qseq[0] 为 int：高位是修饰键标志，低 25 位是按键
        k = int(key)
        for mod_flag, win_mod in mods_map.items():
            if k & mod_flag:
                m |= win_mod
        base = k & 0x01FFFFFF
        vk = _vk_for_key(base)
        if vk is None:
            self.error.emit("不支持的按键: " + ks)
            return False
        if not ctypes.windll.user32.RegisterHotKey(None, HOTKEY_ID, m | MOD_NOREPEAT, vk):
            # 改键失败回滚：register 首行已注销旧热键，不回滚则本会话热键彻底失效
            # （实测失败后旧组合可被外部进程立刻抢注，§33.1 A5）。
            # Linux 侧因 P2-07（X11 线程阻塞在 XNextEvent）无法等价回滚，维持既有语义。
            prev = self._current
            if prev:
                self._current = ""  # 置空防递归回滚
                with contextlib.suppress(Exception):
                    self.register(prev)
            self.error.emit("RegisterHotKey 失败: " + ks)
            return False
        self._filter = WinHotkeyFilter(lambda: self.activated.emit())
        from PyQt5.QtCore import QAbstractEventDispatcher

        QAbstractEventDispatcher.instance().installNativeEventFilter(self._filter)
        self._current = ks
        return True

    def unregister(self):
        if self._filter is not None:
            try:
                from PyQt5.QtCore import QAbstractEventDispatcher

                QAbstractEventDispatcher.instance().removeNativeEventFilter(self._filter)
            except Exception:
                # 注销失败（热键已被系统回收）：忽略
                pass
            self._filter = None
        ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)

    def current(self):
        return self._current
