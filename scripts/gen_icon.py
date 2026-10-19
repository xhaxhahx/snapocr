# -*- coding: utf-8 -*-
"""生成应用图标资源：`resources/app.ico`（多尺寸）与 `resources/app.png`。

图标为程序化绘制（见 `snapocr/ui/icons.py` 的 "app" 分支），无需二进制素材。
ICO 内含 16/24/32/48/64/128/256 七个尺寸，且每个尺寸**独立原生渲染**
（而非把 256 图缩小），保证任务栏、资源管理器、Alt+Tab 等小尺寸场景下依然清晰。

用法: python scripts/gen_icon.py
"""

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from snapocr.main import _setup_qt_plugin_path  # noqa: E402

_setup_qt_plugin_path()

from snapocr.ui.icons import pixmap  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _png_bytes(size: int) -> bytes:
    """把指定尺寸的图标渲染为 PNG 字节。"""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pixmap("app", size=size).save(buf, "PNG")
    buf.close()
    return bytes(ba)


def write_ico(path: str, sizes=SIZES) -> None:
    """写多尺寸 ICO（Vista+ 支持 PNG 压缩条目）。"""
    images = [_png_bytes(n) for n in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))  # reserved, type=icon, count
    offset = 6 + 16 * len(sizes)
    entries = b""
    for n, data in zip(sizes, images):
        dim = 0 if n >= 256 else n  # ICO 用 0 表示 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + entries + b"".join(images))


def main() -> int:
    _app = QApplication([])  # QPainter 需要存活的 QGuiApplication 实例（下划线名避开 F841）
    ico = os.path.join(ROOT, "resources", "app.ico")
    png = os.path.join(ROOT, "resources", "app.png")
    write_ico(ico)
    pixmap("app", size=256).save(png, "PNG")
    print("已生成 %s（尺寸 %s）与 %s" % (ico, ",".join(str(n) for n in SIZES), png), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
