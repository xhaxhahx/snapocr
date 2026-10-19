# -*- coding: utf-8 -*-
r"""Windows 融合主题：跟随系统深浅色/强调色，提供全部窗口的 QSS 与 Win11 DWM 细节。

- 深浅色：注册表 AppsUseLightTheme（HKCU\...\Themes\Personalize）
- 强调色：注册表 AccentColor（HKCU\...\Explorer\Accent，COLORREF 0x00bbggrr）
- 实时响应：WM_SETTINGCHANGE("ImmersiveColorSet") 广播 → changed 信号 → 各窗口 retheme
- Win11：DWM 深色标题栏(20)、窗口圆角(33)；Win10 上为安全空操作
- 非 Windows（信创 Linux）：固定浅色 + 回退强调色，DWM/注册表代码全部安全跳过
"""

import os

from PyQt5.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal
from PyQt5.QtGui import QColor, QFont

IS_WIN = os.name == "nt"
ACCENT_FALLBACK = "#0067c0"


class Theme:
    def __init__(self, dark=False, accent=None):
        self.dark = bool(dark)
        self.accent = QColor(accent if accent else ACCENT_FALLBACK)

    # ---- 颜色令牌（Win11 风格） ----
    @property
    def bg(self):
        return "#202020" if self.dark else "#f3f3f3"

    @property
    def card(self):
        return "#2b2b2b" if self.dark else "#ffffff"

    @property
    def text(self):
        return "#ffffff" if self.dark else "#1b1b1b"

    @property
    def subtext(self):
        return "#a6a6a6" if self.dark else "#5d5d5d"

    @property
    def border(self):
        return "#3d3d3d" if self.dark else "#e5e5e5"

    @property
    def hover(self):
        return "#383838" if self.dark else "#ececec"

    @property
    def toolbar_bg(self):
        return "#2b2b2b" if self.dark else "#f9f9f9"

    @property
    def icon(self):
        return "#f2f2f2" if self.dark else "#444444"

    @property
    def accent_css(self):
        return self.accent.name()

    @property
    def on_accent(self):
        c = self.accent
        lum = 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()
        return "#1b1b1b" if lum > 150 else "#ffffff"

    @property
    def accent_hover(self):
        c = QColor(self.accent)
        return c.lighter(118).name() if self.dark else c.darker(108).name()


def read_theme() -> Theme:
    dark = False
    accent = None
    if IS_WIN:
        try:
            import winreg

            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            dark = int(v) == 0
            k.Close()
        except Exception:
            # 注册表读取失败：按浅色默认处理
            pass
        try:
            import winreg

            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent",
            )
            v, _ = winreg.QueryValueEx(k, "AccentColor")
            # 部分 Windows 版本把 AccentColor 存为 REG_BINARY：直接 int(bytes) 会抛
            # 异常并被下方 except 吞掉，表现为强调色永远不跟随系统（静默回退）。
            if isinstance(v, (bytes, bytearray)):
                v = int.from_bytes(v, "little")
            v = int(v) & 0xFFFFFF
            accent = QColor(v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)
            k.Close()
        except Exception:
            # 强调色读取失败：走 ACCENT_FALLBACK
            pass
    if accent is None or not accent.isValid():
        accent = QColor(ACCENT_FALLBACK)
    return Theme(dark, accent)


if IS_WIN:
    import ctypes

    class _SettingChangeFilter(QAbstractNativeEventFilter):
        """监听系统主题变更广播（切换深浅色/强调色时 Windows 发出）。"""

        WM_SETTINGCHANGE = 0x001A

        def __init__(self, mgr):
            super().__init__()
            self.mgr = mgr

        def nativeEventFilter(self, event_type, message):
            if event_type == b"windows_generic_MSG":
                try:
                    import ctypes.wintypes as wt

                    msg = wt.MSG.from_address(int(message))
                    if msg.message == self.WM_SETTINGCHANGE and msg.lParam:
                        s = ctypes.wstring_at(msg.lParam)
                        if s == "ImmersiveColorSet":
                            t = read_theme()
                            if t.dark != self.mgr.theme.dark or t.accent != self.mgr.theme.accent:
                                self.mgr.theme = t
                                self.mgr.changed.emit(t)
                except Exception:
                    # 消息结构解析失败（非本进程消息）：按未处理返回
                    pass
            return False, 0


class ThemeManager(QObject):
    changed = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.theme = read_theme()
        self._filter = None

    def start_watching(self):
        if IS_WIN and self._filter is None:
            self._filter = _SettingChangeFilter(self)
            from PyQt5.QtCore import QAbstractEventDispatcher

            QAbstractEventDispatcher.instance().installNativeEventFilter(self._filter)


manager = ThemeManager()


def current() -> Theme:
    return manager.theme


def app_font() -> QFont:
    f = QFont()
    f.setFamilies(
        [
            "Segoe UI Variable",
            "Segoe UI",
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Noto Sans CJK SC",
            "WenQuanYi Micro Hei",  # Linux 信创
            "Ubuntu",
        ]
    )
    f.setPointSize(9)
    return f


# ---------------- QSS 生成 ----------------


def qss_toolbar(t: Theme, obj: str, radius="0") -> str:
    return """
#%(obj)s { background: %(tb)s; border: 1px solid %(border)s; border-radius: %(radius)s; }
#%(obj)s QFrame#sep { background: %(border)s; }
QToolButton { background: %(card)s; border: 1px solid %(border)s;
              border-radius: 7px; padding: 3px; color: %(text)s; font-size: 13px; }
QToolButton:hover { background: %(hover)s; border-color: %(sub)s; }
QToolButton:checked { background: %(accent)s; border-color: %(accent)s;
                      color: %(on_acc)s; }
QToolButton:checked:hover { background: %(accent_h)s; }
QToolButton[textBtn="true"] { padding: 4px 14px; }
QToolButton#btnOcr { background: %(card)s; color: %(text)s; }
QToolButton#btnOcr:checked { background: %(accent)s; border-color: %(accent)s;
                             color: %(on_acc)s; }
QToolButton#btnOcr:checked:hover { background: %(accent_h)s; }
QComboBox { background: %(card)s; color: %(text)s; border: 1px solid %(border)s;
            border-radius: 7px; padding: 4px 8px; font-size: 12px; }
QComboBox:hover { background: %(hover)s; }
QComboBox QAbstractItemView { background: %(card)s; color: %(text)s;
                              border: 1px solid %(border)s;
                              selection-background-color: %(accent)s;
                              selection-color: %(on_acc)s; }
""" % {
        "obj": obj,
        "radius": radius,
        "tb": t.toolbar_bg,
        "border": t.border,
        "text": t.text,
        "hover": t.hover,
        "card": t.card,
        "sub": t.subtext,
        "accent": t.accent_css,
        "accent_h": t.accent_hover,
        "on_acc": t.on_accent,
    }


def qss_result(t: Theme) -> str:
    return """
#resultRoot { background: %(bg)s; }
#resultTitle { font-size: 15px; font-weight: 600; color: %(text)s; }
#resultMeta { font-size: 12px; color: %(sub)s; }
#resultToast { background: rgba(20,22,26,235); color: #ffffff; border-radius: 6px;
              padding: 6px 14px; font-size: 12px; }
QPlainTextEdit { background: %(card)s; border: 1px solid %(border)s;
                 border-radius: 8px; padding: 10px; font-size: 14px; color: %(text)s;
                 selection-background-color: %(accent)s; selection-color: %(on_acc)s; }
QPushButton { background: %(card)s; border: 1px solid %(border)s; border-radius: 6px;
              padding: 6px 14px; font-size: 13px; color: %(text)s; }
QPushButton:hover { background: %(hover)s; }
QPushButton#primary { background: %(accent)s; border: none; color: %(on_acc)s; font-weight: 600; }
QPushButton#primary:hover { background: %(accent_h)s; }
""" % {
        "bg": t.bg,
        "card": t.card,
        "text": t.text,
        "sub": t.subtext,
        "border": t.border,
        "hover": t.hover,
        "accent": t.accent_css,
        "accent_h": t.accent_hover,
        "on_acc": t.on_accent,
    }


def qss_settings(t: Theme) -> str:
    return """
#settingsRoot { background: %(bg)s; }
QLabel { color: %(text)s; font-size: 13px; }
QGroupBox { font-weight: 600; border: 1px solid %(border)s; border-radius: 8px;
            margin-top: 12px; background: %(card)s; color: %(text)s; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px;
                   color: %(text)s; background: %(bg)s; }
QLineEdit, QSpinBox, QComboBox { background: %(card)s; color: %(text)s;
                                 border: 1px solid %(border)s; border-radius: 6px;
                                 padding: 5px 8px; }
QLineEdit:hover, QSpinBox:hover, QComboBox:hover { border-color: %(sub)s; }
QComboBox QAbstractItemView { background: %(card)s; color: %(text)s;
                              selection-background-color: %(accent)s;
                              selection-color: %(on_acc)s; }
QPushButton { background: %(card)s; border: 1px solid %(border)s; border-radius: 6px;
              padding: 6px 16px; color: %(text)s; }
QPushButton:hover { background: %(hover)s; }
QPushButton#primary { background: %(accent)s; border: none; color: %(on_acc)s; font-weight: 600; }
QPushButton#primary:hover { background: %(accent_h)s; }
QCheckBox { color: %(text)s; }
""" % {
        "bg": t.bg,
        "card": t.card,
        "text": t.text,
        "sub": t.subtext,
        "border": t.border,
        "hover": t.hover,
        "accent": t.accent_css,
        "accent_h": t.accent_hover,
        "on_acc": t.on_accent,
    }


def qss_menu(t: Theme) -> str:
    return """
QMenu { background: %(card)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px; }
QMenu::item { padding: 6px 24px; border-radius: 6px; }
QMenu::item:selected { background: %(hover)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 8px; }
QMenu::icon { padding-left: 6px; }
""" % {"card": t.card, "text": t.text, "border": t.border, "hover": t.hover}


# ---------------- Win11 DWM 细节 ----------------


def apply_window_chrome(widget, dark_title=None, rounded=None):
    """深色标题栏(DWMWA_USE_IMMERSIVE_DARK_MODE=20)与窗口圆角(33)。Win10 上为空操作。"""
    if not IS_WIN:
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        if dark_title is not None:
            v = ctypes.c_int(1 if dark_title else 0)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), 4)
        if rounded is not None:
            v = ctypes.c_int(2 if rounded else 1)  # DWMWCP_ROUND / DONOTROUND
            dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(v), 4)
    except Exception:
        # DWM 调用失败（旧系统/非 Win11）：保持系统默认外观
        pass
