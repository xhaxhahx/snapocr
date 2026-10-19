# -*- coding: utf-8 -*-
"""路径解析：兼容开发态与 PyInstaller 打包态。"""

import contextlib
import os
import sys


def app_dir() -> str:
    """可执行文件/工程所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resources_dir() -> str:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and os.path.isdir(os.path.join(meipass, "resources")):
            return os.path.join(meipass, "resources")
        return os.path.join(app_dir(), "resources")
    return os.path.join(app_dir(), "resources")


def models_dir() -> str:
    return os.path.join(resources_dir(), "models")


def find_model(kind: str) -> str:
    """按 det/cls/rec 找模型文件，找不到返回空串（由引擎报错）。"""
    d = models_dir()
    if not os.path.isdir(d):
        return ""
    # 命名约定：det.onnx / cls.onnx / rec.onnx；也兼容任意前缀
    exact = os.path.join(d, "%s.onnx" % kind)
    if os.path.isfile(exact):
        return exact
    for name in sorted(os.listdir(d)):
        if name.endswith(".onnx") and kind in name.lower():
            return os.path.join(d, name)
    return ""


def data_dir() -> str:
    """用户配置目录（含子目录创建）。"""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "SnapOCR")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        d = os.path.join(base, "snapocr")
    os.makedirs(d, exist_ok=True)
    return d


def pictures_dir() -> str:
    """系统图片目录（Qt 标准路径，已本地化），不存在则创建。"""
    try:
        from PyQt5.QtCore import QStandardPaths

        d = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        if d:
            os.makedirs(d, exist_ok=True)
            return d
    except Exception:
        # 取不到系统图片目录：走下方 ~/Pictures 兜底
        pass
    d = os.path.join(os.path.expanduser("~"), "Pictures")
    with contextlib.suppress(Exception):
        os.makedirs(d, exist_ok=True)
    return d


def log_dir() -> str:
    d = os.path.join(data_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def config_file() -> str:
    return os.path.join(data_dir(), "config.json")


def find_exe() -> str:
    """当前可执行体的启动命令（用于自启/DE 快捷键）。"""
    if getattr(sys, "frozen", False):
        return sys.executable
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    py = pyw if os.path.isfile(pyw) else sys.executable
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "snapocr", "main.py"
    )
    return "%s %s" % (py, script)
