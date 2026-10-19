# -*- coding: utf-8 -*-
"""定位：框选 idle 时屏幕左上角的灰色块是什么控件。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from snapocr.main import _setup_qt_plugin_path  # noqa: E402

_setup_qt_plugin_path()


def main():
    from PyQt5.QtCore import QPoint, QPointF
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import QApplication
    from snapocr.config import Config
    from snapocr.tests.selftest import _sample_image
    from snapocr.ui.overlay import OverlayWindow

    app = QApplication([])
    scr = app.primaryScreen()
    ov = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=Config())
    ov.show()
    app.processEvents()

    for pt in [(5, 5), (30, 15), (60, 20), (120, 23)]:
        w = ov.childAt(QPoint(*pt))
        print("childAt(%s) =" % (pt,), w.__class__.__name__ if w else None,
              "| geometry:", w.geometry() if w else "-")

    print("toolbar visible:", ov.toolbar.isVisible(), "geo:", ov.toolbar.geometry())
    print("toast visible:", ov.toast.isVisible(), "geo:", ov.toast.geometry())
    # 模拟鼠标移动到左上角，看 hover 检测结果
    ev = QEvent(QEvent.MouseMove)
    from PyQt5.QtCore import QEvent as _QE
    move = _QE(_QE.MouseMove)
    # 直接构造 QMouseEvent 更可靠
    from PyQt5.QtGui import QMouseEvent
    mv = QMouseEvent(_QE.MouseMove, QPointF(30, 15), QPointF(30, 15),
                     Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    ov.mouseMoveEvent(mv)
    app.processEvents()
    print("hover_rect:", ov.hover_rect)
    ov.grab().save("docs/screenshots/_probe_idle_tl.png")
    print("DONE")


if __name__ == "__main__":
    main()
