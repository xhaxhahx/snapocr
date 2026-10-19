# -*- coding: utf-8 -*-
"""新交互回归：十字光标绘制、窗口/控件识别、右键取消、关于文本。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from snapocr.main import _setup_qt_plugin_path  # noqa: E402

_setup_qt_plugin_path()


def main():
    from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt
    from PyQt5.QtGui import QMouseEvent, QPixmap
    from PyQt5.QtWidgets import QApplication
    from snapocr import __version__, APP_DISPLAY
    from snapocr.config import Config
    from snapocr.i18n import tr
    from snapocr.platform import windowdetect
    from snapocr.tests.selftest import _sample_image
    from snapocr.ui.overlay import OverlayWindow

    app = QApplication([])
    scr = app.primaryScreen()
    ov = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=Config())
    ov.show()
    app.processEvents()

    # 1) 十字光标：移动鼠标后应重绘（finalized 前光标为 Blank）
    move = QMouseEvent(QEvent.MouseMove, QPointF(300, 200), QPointF(300, 200),
                       Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    ov.mouseMoveEvent(move)
    app.processEvents()
    assert ov._mouse_pos.x() == 300 and ov._mouse_pos.y() == 200
    assert ov.cursor().shape() == Qt.BlankCursor
    pm = ov.grab()
    img = pm.toImage()
    # 十字线应画在 (300,200)：黑描边+白芯，采样竖线两点
    c1 = img.pixelColor(300, 100)
    print("[1] crosshair pixel@(300,100):", c1.red(), c1.green(), c1.blue())
    assert not (c1.red() == c1.green() == c1.blue() == 0), "十字未绘制"

    # 2) 窗口/控件识别（真实桌面）
    import ctypes
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    cx, cy = user32.GetSystemMetrics(0) // 2, user32.GetSystemMetrics(1) // 2
    dpr = ov.dpr
    gp = ov.mapToGlobal(ov.rect().center())
    r = windowdetect.descend_rect_at(gp.x() * dpr, gp.y() * dpr)
    print("[2] descend_rect_at:", r)
    assert r and r[2] > r[0] and r[3] > r[1]

    # 3) 右键释放取消（按下不立即取消）
    cancelled = []
    ov.cancelled.connect(lambda: cancelled.append(1))
    press = QMouseEvent(QEvent.MouseButtonPress, QPointF(700, 600),
                        QPointF(700, 600), Qt.RightButton, Qt.RightButton,
                        Qt.NoModifier)
    ov.mousePressEvent(press)
    app.processEvents()
    assert not cancelled, "按下就取消了（会导致系统菜单）"
    rel = QMouseEvent(QEvent.MouseButtonRelease, QPointF(700, 600),
                      QPointF(700, 600), Qt.RightButton, Qt.NoButton,
                      Qt.NoModifier)
    ov.mouseReleaseEvent(rel)
    app.processEvents()
    assert cancelled, "右键释放未取消"
    print("[3] right-click cancel ok")

    # 4) 关于文本包含开发单位
    txt = tr("about_text", APP_DISPLAY, __version__)
    assert "中共枣庄市委组织部" in txt, txt
    print("[4] about text ok:", APP_DISPLAY, __version__)
    print("PROBE_ALL_PASS")


if __name__ == "__main__":
    main()
