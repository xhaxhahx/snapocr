# -*- coding: utf-8 -*-
"""调试 T1.1b/T1.2：打印每个事件后的状态。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from snapocr.main import _setup_qt_plugin_path  # noqa: E402

_setup_qt_plugin_path()


def main():
    from PyQt5.QtCore import QEvent, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent, QPixmap
    from PyQt5.QtWidgets import QApplication
    from snapocr.config import Config
    from snapocr.tests.selftest import _sample_image
    from snapocr.ui.overlay import OverlayWindow

    app = QApplication([])
    scr = app.primaryScreen()
    ov = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=Config())
    ov.show(); app.processEvents()

    def me(t, x, y, b, bs):
        return QMouseEvent(t, QPointF(x, y), QPointF(x, y), b, bs, Qt.NoModifier)

    def st(tag):
        print(tag, "dragging=%s sel=%s finalized=%s" %
              (ov.dragging, ov.sel, ov.finalized), flush=True)

    st("init")
    ov.mousePressEvent(me(QEvent.MouseButtonPress, 100, 80, Qt.LeftButton, Qt.LeftButton))
    st("press(100,80)")
    ov.mouseMoveEvent(me(QEvent.MouseMove, 130, 110, Qt.NoButton, Qt.LeftButton))
    st("move(130,110)")
    ov.mouseReleaseEvent(me(QEvent.MouseButtonRelease, 130, 110, Qt.LeftButton, Qt.NoButton))
    st("release(130,110)")
    app.processEvents()
    st("processEvents")
    # 第二次
    ov.mousePressEvent(me(QEvent.MouseButtonPress, 100, 80, Qt.LeftButton, Qt.LeftButton))
    st("press2(100,80)")
    ov.mouseReleaseEvent(me(QEvent.MouseButtonRelease, 400, 280, Qt.LeftButton, Qt.NoButton))
    st("release2(400,280)")


if __name__ == "__main__":
    main()
