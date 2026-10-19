# -*- coding: utf-8 -*-
"""新交互探针 v5：文字按钮/OCR激活态/色板弹窗/字体下拉/边框四边/右键取消。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from snapocr.main import _setup_qt_plugin_path  # noqa: E402

_setup_qt_plugin_path()


def main():
    from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt
    from PyQt5.QtGui import QMouseEvent, QPixmap
    from PyQt5.QtWidgets import QApplication
    from snapocr.config import Config
    from snapocr.tests.selftest import _sample_image
    from snapocr.ui.editor import TOOL_PEN, TOOL_SELECT, TOOL_TEXT
    from snapocr.ui.overlay import OverlayWindow

    app = QApplication([])
    scr = app.primaryScreen()
    ov = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=Config())
    ov.show()
    app.processEvents()

    def mouse_ev(type_, x, y, btn, btns):
        return QMouseEvent(type_, QPointF(x, y), QPointF(x, y), btn, btns,
                           Qt.NoModifier)

    # 1) 拖动框选 → 编辑态（默认展开）
    ov.mousePressEvent(mouse_ev(QEvent.MouseButtonPress, 100, 80,
                                Qt.LeftButton, Qt.LeftButton))
    for i in range(1, 6):
        ov.mouseMoveEvent(mouse_ev(QEvent.MouseMove, 100 + i * 60, 80 + i * 40,
                                   Qt.NoButton, Qt.LeftButton))
    ov.mouseReleaseEvent(mouse_ev(QEvent.MouseButtonRelease, 400, 280,
                                  Qt.LeftButton, Qt.NoButton))
    app.processEvents()
    assert ov.finalized and ov.expanded, "编辑态/展开失败"
    tb = ov.toolbar
    assert not hasattr(tb, "btn_done"), "完成按钮应已移除"
    assert tb.btn_copy.text() == "复制" and tb.btn_save.text() == "保存"
    assert tb.btn_cancel.text() == "取消"
    print("[1] 编辑态默认展开 + 文字按钮 + 无完成按钮 ok")

    # 2) OCR 激活态：点击后蓝底（checked），结束取消
    tb.btn_ocr.click()
    app.processEvents()
    assert tb.btn_ocr.isChecked(), "OCR 未进入激活态"
    tb.set_ocr_active(False)
    assert not tb.btn_ocr.isChecked()
    print("[2] OCR 激活态链路 ok")

    # 3) 色板弹窗：标准色点选 → 颜色芯片/画布颜色更新
    tb.btn_color.click()
    from snapocr.ui.editor import ColorPickerPopup
    popups = [w for w in app.topLevelWidgets()
              if isinstance(w, ColorPickerPopup)]
    assert popups, "色板弹窗未打开"
    popups[0]._pick("#00c7be")   # 点标准色 → 选择并自动关闭
    app.processEvents()
    assert ov.canvas.color == "#00c7be", ov.canvas.color
    print("[3] 色板选色 ok:", ov.canvas.color)

    # 4) 字体下拉 → 画布字体更新 + 文字笔画带字体
    ov.toolbar._on_tool_btn(TOOL_TEXT)
    app.processEvents()
    assert ov.toolbar.font_combo.isVisibleTo(ov.toolbar)
    ov.toolbar.font_combo.setCurrentFont(__import__("PyQt5.QtGui",
                                        fromlist=["QFont"]).QFont("SimSun"))
    app.processEvents()
    assert ov.canvas.text_font == "宋体", ov.canvas.text_font  # QFontComboBox 本地化名
    QTest_ = None
    from PyQt5.QtTest import QTest
    QTest.mouseClick(ov.canvas, Qt.LeftButton, Qt.NoModifier, QPointF(30, 30).toPoint())
    app.processEvents()
    te = ov.canvas._text_edit
    assert te is not None
    QTest.keyClicks(te, "FONT")
    ov.mousePressEvent(mouse_ev(QEvent.MouseButtonPress, 700, 600,
                                Qt.LeftButton, Qt.LeftButton))
    app.processEvents()
    texts = [s for s in ov.canvas.strokes if s["kind"] == "text"]
    assert texts and texts[-1].get("font") == "宋体", texts[-1]
    print("[4] 字体选择+提交 ok:", texts[-1]["font"], texts[-1]["text"])

    # 5) 边框四边：grab 中采样四边中点像素应为强调色
    ov.toolbar._on_tool_btn(TOOL_SELECT)
    app.processEvents()
    shot = ov.grab().toImage()
    sel = ov.sel
    from snapocr.ui.theme import current
    acc = current().accent
    mid_top = shot.pixelColor(int(sel.center().x()), int(sel.top()) + 1)
    mid_bot = shot.pixelColor(int(sel.center().x()), int(sel.bottom()) - 2)
    mid_left = shot.pixelColor(int(sel.left()) + 1, int(sel.center().y()))
    mid_right = shot.pixelColor(int(sel.right()) - 2, int(sel.center().y()))
    for name, c in (("top", mid_top), ("bottom", mid_bot),
                    ("left", mid_left), ("right", mid_right)):
        assert c.red() == acc.red() and c.green() == acc.green() \
            and c.blue() == acc.blue(), (name, c.name(), acc.name())
    print("[5] 边框四边 ok")

    # 6) 右键选区内/外都取消
    cancelled = []
    ov.cancelled.connect(lambda: cancelled.append(1))
    ov.mousePressEvent(mouse_ev(QEvent.MouseButtonPress, 200, 150,
                                Qt.RightButton, Qt.RightButton))
    ov.mouseReleaseEvent(mouse_ev(QEvent.MouseButtonRelease, 200, 150,
                                  Qt.RightButton, Qt.NoButton))
    app.processEvents()
    assert cancelled == [1]
    print("[6] 右键取消 ok")
    print("PROBE_ALL_PASS")


if __name__ == "__main__":
    main()
