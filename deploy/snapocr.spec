# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置（Windows 绿色版 onedir）
import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None
_here = SPECPATH
if os.path.isfile(_here):
    _here = os.path.dirname(_here)   # 兼容 SPECPATH 为文件路径的版本
ROOT = os.path.dirname(os.path.abspath(_here))  # deploy/.. = 工程根目录

datas = [
    (os.path.join(ROOT, "resources", "app.ico"), "resources"),
    (os.path.join(ROOT, "resources", "app.png"), "resources"),
]
# resources/models 存在时一并打包（离线三模型 det/cls/rec），缺失则回落 rapidocr 内置模型
_models_dir = os.path.join(ROOT, "resources", "models")
if os.path.isdir(_models_dir):
    datas.append((_models_dir, "resources/models"))

# Qt 原生控件中文翻译（QInputDialog 按钮/编辑控件右键菜单）。目录名用 qt-i18n：
# _keep_qt_data 会过滤目标路径含 "translations/" 的条目，不能叫 translations
_qt_i18n_dir = os.path.join(ROOT, "resources", "qt-i18n")
if os.path.isdir(_qt_i18n_dir):
    datas.append((_qt_i18n_dir, "resources/qt-i18n"))
# 说明: OCR 模型不再单独打包 —— rapidocr wheel 内置 PP-OCRv6 small(det/rec)
# + PP-OCRv4 mobile(cls) 会被 collect_all('rapidocr') 带入 _internal/rapidocr/models，
# 引擎在 resources/models 缺失时自动回落（resources/models 仍可放模型覆盖升级）。
binaries = []
hiddenimports = []

for pkg in ("rapidocr", "onnxruntime", "comtypes"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(ROOT, "src", "run.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy.distutils", "scipy", "pandas",
        "IPython", "jedi", "pytest", "setuptools", "pygments",
        "PyQt5.QtQml", "PyQt5.QtQuick", "PyQt5.QtQuickWidgets",
        "PyQt5.QtBluetooth", "PyQt5.QtNfc", "PyQt5.QtPositioning",
        "PyQt5.QtSensors", "PyQt5.QtSerialPort", "PyQt5.QtSql",
        "PyQt5.QtTest", "PyQt5.QtTextToSpeech", "PyQt5.QtXml",
        "PyQt5.QtMultimedia", "PyQt5.QtMultimediaWidgets",
        "PyQt5.QtWeb", "PyQt5.QtWebKit", "PyQt5.QtWebKitWidgets",
        "PyQt5.QtWebChannel", "PyQt5.QtWebEngine", "PyQt5.QtWebEngineWidgets",
        "PyQt5.QtChart", "PyQt5.QtDataVisualization", "PyQt5.Qt3D",
        "PyQt5.QtRemoteObjects", "PyQt5.QtDBus",
    ],
    cipher=block_cipher,
    noarchive=False,
)

# 瘦身-D：只保留用到的 Qt 插件目录（platforms/styles/imageformats:qico,qpng,qjpeg），
# 剔除 translations 与其余插件目录（audio/geoservices/sqldrivers 等，白占 ~8-10MB）。
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

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SnapOCR",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "resources", "app.ico") if os.path.isfile(
        os.path.join(ROOT, "resources", "app.ico")) else None,
    version=os.path.join(ROOT, "deploy", "windows", "version.txt") if os.path.isfile(
        os.path.join(ROOT, "deploy", "windows", "version.txt")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="snapocr-win64",
)
