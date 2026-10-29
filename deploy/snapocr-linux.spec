# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置（Linux/信创，onedir）
import os
from PyInstaller.utils.hooks import collect_all

_here = SPECPATH
if os.path.isfile(_here):
    _here = os.path.dirname(_here)
ROOT = os.path.dirname(os.path.abspath(_here))

datas = [
    (os.path.join(ROOT, "resources", "app.png"), "resources"),
]
_models_dir = os.path.join(ROOT, "resources", "models")
if os.path.isdir(_models_dir):
    datas.append((_models_dir, "resources/models"))

# Qt 原生控件中文翻译（QInputDialog 按钮/编辑控件右键菜单）。目录名用 qt-i18n：
# _keep_qt_data 会过滤目标路径含 "translations/" 的条目，不能叫 translations
_qt_i18n_dir = os.path.join(ROOT, "resources", "qt-i18n")
if os.path.isdir(_qt_i18n_dir):
    datas.append((_qt_i18n_dir, "resources/qt-i18n"))
# 模型同 Windows spec: 使用 rapidocr 内置模型, resources/models 可选覆盖
binaries = []
hiddenimports = []
for pkg in ("rapidocr", "onnxruntime"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(
    [os.path.join(ROOT, "src", "run.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest",
        "PyQt5.QtQml", "PyQt5.QtQuick", "PyQt5.QtBluetooth", "PyQt5.QtNfc",
        "PyQt5.QtPositioning", "PyQt5.QtSensors", "PyQt5.QtSerialPort",
        "PyQt5.QtSql", "PyQt5.QtTest", "PyQt5.QtXml",
        "PyQt5.QtMultimedia", "PyQt5.QtWebKit", "PyQt5.QtWebEngineWidgets",
    ],
)

# 瘦身-D：只保留用到的 Qt 插件目录（platforms/styles/imageformats:qico,qpng,qjpeg），剔除 translations 等死目录
_KEEP_PLUGIN_DIRS = ("platforms/", "styles/", "imageformats/")
_KEEP_IMAGE_FORMATS = ("qico", "qpng", "qjpeg")


def _keep_qt_data(entry):
    dest = str(entry[0]).replace("\\", "/").lower()
    if "translations/" in dest or dest.startswith("translations/"):
        return False
    if "plugins/" in dest:
        tail = dest.split("plugins/", 1)[1]
        if tail.startswith("imageformats/"):
            return any(f in tail for f in _KEEP_IMAGE_FORMATS)
        return any(tail.startswith(d) for d in _KEEP_PLUGIN_DIRS)
    return True


a.datas = [d for d in a.datas if _keep_qt_data(d)]

# 系统库：conda 构建的 libfontconfig 编译期前缀为 /.tmp/py311/etc/fonts，打包后
# 找不到 fonts.conf（启动告警，且可能回落到无系统字体）。改用目标机系统
# libfontconfig1（deb Depends 已声明），字体配置/中文回退才与系统一致。
_EXCLUDE_LIBS = ("libfontconfig.so.1",)


def _keep_lib(entry):
    names = {os.path.basename(str(x)) for x in entry[:2]}
    return not (names & set(_EXCLUDE_LIBS))


a.binaries = [b for b in a.binaries if _keep_lib(b)]
a.datas = [d for d in a.datas if _keep_lib(d)]

pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SnapOCR",
          debug=False, strip=False, upx=False, console=False)

COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False,
        name="snapocr-linux64")
