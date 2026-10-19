# -*- coding: utf-8 -*-
"""开机自启：Win 注册表 Run 键 / Linux autostart 桌面项。"""

import contextlib
import os

from ..paths import find_exe
from ..utils.logger import get_logger

log = get_logger()
_VALUE = "SnapOCR"


def set_autostart(enabled: bool) -> bool:
    try:
        if os.name == "nt":
            return _win_set(enabled)
        return _linux_set(enabled)
    except Exception as e:
        log.warning("设置自启失败: %s", e)
        return False


def _win_set(enabled: bool) -> bool:
    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    )
    try:
        if enabled:
            cmd = find_exe()
            winreg.SetValueEx(key, _VALUE, 0, winreg.REG_SZ, '"%s"' % cmd if " " in cmd else cmd)
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, _VALUE)
    finally:
        key.Close()
    return True


def _linux_set(enabled: bool) -> bool:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    adir = os.path.join(base, "autostart")
    os.makedirs(adir, exist_ok=True)
    path = os.path.join(adir, "snapocr.desktop")
    if enabled:
        exe = find_exe()
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "[Desktop Entry]\nType=Application\nName=SnapOCR\n"
                "Exec=%s --hidden\nTerminal=false\nX-GNOME-Autostart-enabled=true\n" % exe
            )
    else:
        if os.path.isfile(path):
            os.remove(path)
    return True
