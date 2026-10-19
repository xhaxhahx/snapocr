# -*- coding: utf-8 -*-
"""调试 T1.2f：列出取消后仍可见的相关窗口。"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from snapocr.main import _setup_qt_plugin_path  # noqa: E402

_setup_qt_plugin_path()


def main():
    from PyQt5.QtCore import QEvent, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent, QPixmap
    from PyQt5.QtWidgets import QApplication
    from snapocr.app import CaptureController
    from snapocr.config import Config
    from snapocr.tests.selftest import _sample_image
    from snapocr.ui.overlay import OverlayWindow
    from snapocr.ui.result_window import ResultWindow
    from snapocr.ui.preview_dialog import PreviewDialog

    app = QApplication([])
    scr = app.primaryScreen()
    cfg = Config()
    ctl = CaptureController.__new__(CaptureController)
    from PyQt5.QtCore import QObject as _QO
    _QO.__init__(ctl)
    ctl.app = type("A", (), {"cfg": cfg})()
    from PyQt5.QtWidgets import QLabel as _QL
    ctl.app.toast = _QL(); ctl.app.toast.hide(); ctl.app.toast.pop = lambda *a, **k: None
    ctl.overlays = []; ctl.result = None; ctl.worker = None; ctl._hiding = []

    def mouse_ev(t, x, y, b, bs):
        return QMouseEvent(t, QPointF(x, y), QPointF(x, y), b, bs, Qt.NoModifier)

    def wait_ocr(timeout=30.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            app.processEvents()
            if ctl.worker is None:
                return True
            time.sleep(0.02)
        return False

    ov2 = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)),
                        cfg=cfg, ocr_busy_signal=ctl.ocrPanel)
    ov2.ocrRequested.connect(ctl.toggle_ocr)
    ov2.selectionMoved.connect(ctl._on_selection_moved)
    ctl.overlays.append(ov2)
    ov2.show(); app.processEvents()
    ov2.mousePressEvent(mouse_ev(QEvent.MouseButtonPress, 100, 80, Qt.LeftButton, Qt.LeftButton))
    ov2.mouseReleaseEvent(mouse_ev(QEvent.MouseButtonRelease, 400, 280, Qt.LeftButton, Qt.NoButton))
    app.processEvents()
    ctl.toggle_ocr(ov2.crop_image(), ov2.global_rect(), scr)
    assert wait_ocr(), "OCR timeout"
    ov2._ocr(); app.processEvents()          # 隐藏结果窗
    ov2._ocr()                               # 重新显示+重识别
    assert wait_ocr(), "OCR2 timeout"
    ov2.cancelled.emit(); app.processEvents()

    for w in app.topLevelWidgets():
        if isinstance(w, (OverlayWindow, ResultWindow, PreviewDialog)) and w.isVisible():
            print("VISIBLE:", type(w).__name__, w.geometry())
    print("result is None:", ctl.result is None)
    print("overlays:", len(ctl.overlays))


if __name__ == "__main__":
    main()
