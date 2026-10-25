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


def autostart_enabled() -> bool:
    """系统层面自启是否实际生效（Win=HKCU Run 键 / Linux=autostart 桌面项）。

    平台分支失败安全：任何读取异常一律按"未自启"返回（设置页可重新勾选写回）。
    """
    try:
        if os.name == "nt":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            ) as k:
                winreg.QueryValueEx(k, _VALUE)
                return True  # 能读到值即已自启（FileNotFoundError 走下方 False）
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
            return os.path.isfile(os.path.join(base, "autostart", "snapocr.desktop"))
    except FileNotFoundError:
        return False
    except Exception:
        return False
    return False


def sync_autostart_cfg(cfg) -> bool:
    """把配置里的自启开关对齐到系统实际状态（注册表/桌面项是事实源）。

    场景：安装器按安装页选择写/删注册表 Run 键，而 %APPDATA% 配置仍是上一
    次安装的旧值，表现为"安装时未勾选、设置页却显示已开启"（2026-10-26 反馈）。
    """
    actual = autostart_enabled()
    if bool(cfg.get("autostart")) != actual:
        cfg.set("autostart", actual)
    return actual
