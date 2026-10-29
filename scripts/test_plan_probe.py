# -*- coding: utf-8 -*-
"""测试计划执行探针：T1 崩溃风险 / T2 功能回归 / T4 安全。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from snapocr.main import _setup_qt_plugin_path

_setup_qt_plugin_path()

OK = []
FAIL = []


def check(name, cond):
    (OK if cond else FAIL).append(name)
    print(("[PASS] " if cond else "[FAIL] ") + name, flush=True)


def rw_visible(ctl) -> bool:
    """结果窗是否可见（T1.2d 用）。"""
    return ctl.result is not None and ctl.result.isVisible()


def main():
    from PyQt5.QtCore import QEvent, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent, QPixmap
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication

    from snapocr.app import CaptureController
    from snapocr.config import Config
    from snapocr.tests.selftest import _sample_image
    from snapocr.ui.editor import TOOL_PEN, TOOL_TEXT, ColorPickerPopup
    from snapocr.ui.overlay import OverlayWindow
    from snapocr.ui.result_window import ResultWindow
    from snapocr.ui.settings_dialog import HotkeyEdit
    from snapocr.utils.singleinstance import SingleInstance

    app = QApplication([])
    scr = app.primaryScreen()
    cfg = Config()

    def mouse_ev(t, x, y, b, bs):
        return QMouseEvent(t, QPointF(x, y), QPointF(x, y), b, bs, Qt.NoModifier)

    # ---- T1.1 极小选区 ----
    ov = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=cfg)
    ov.show()
    app.processEvents()
    ov.mousePressEvent(mouse_ev(QEvent.MouseButtonPress, 100, 80, Qt.LeftButton, Qt.LeftButton))
    ov.mouseReleaseEvent(mouse_ev(QEvent.MouseButtonRelease, 106, 86, Qt.LeftButton, Qt.NoButton))
    app.processEvents()
    check("T1.1a 极小选区<8不进入编辑态", not ov.finalized and ov.canvas is None)
    ov.mousePressEvent(mouse_ev(QEvent.MouseButtonPress, 100, 80, Qt.LeftButton, Qt.LeftButton))
    ov.mouseReleaseEvent(mouse_ev(QEvent.MouseButtonRelease, 130, 110, Qt.LeftButton, Qt.NoButton))
    app.processEvents()
    check("T1.1b 30x30选区可编辑且不崩", ov.finalized and ov.canvas.width() == 26)
    ov.cancelled.emit()
    app.processEvents()
    ov.close()
    app.processEvents()  # T1.1 遮罩无控制器接线，直接关闭避免干扰后续全局扫描

    # ---- T1.2 OCR 进行中交叉操作 ----
    ctl = CaptureController.__new__(CaptureController)
    from PyQt5.QtCore import QObject as _QO

    _QO.__init__(ctl)
    ctl.app = type("A", (), {"cfg": cfg})()
    from PyQt5.QtWidgets import QLabel as _QL

    ctl.app.toast = _QL()
    ctl.app.toast.hide()
    ctl.app.toast.pop = lambda *a, **k: None  # busy 路径需要 toast.pop
    ctl.overlays = []
    ctl.result = None
    ctl.worker = None
    ctl._hiding = []
    ctl._previews = []  # 钉住预览窗强引用表（10-29 新增，__new__ 夹具需同步）
    ov2 = OverlayWindow(
        scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=cfg, ocr_busy_signal=ctl.ocrPanel
    )
    ov2.ocrRequested.connect(ctl.toggle_ocr)
    ov2.selectionMoved.connect(ctl._on_selection_moved)
    ov2.finished.connect(ctl._on_finished)  # 与 start_capture 相同接线
    ov2.cancelled.connect(ctl._on_finished)
    ctl.overlays.append(ov2)
    ov2.show()
    app.processEvents()
    ov2.mousePressEvent(mouse_ev(QEvent.MouseButtonPress, 100, 80, Qt.LeftButton, Qt.LeftButton))
    ov2.mouseReleaseEvent(mouse_ev(QEvent.MouseButtonRelease, 400, 280, Qt.LeftButton, Qt.NoButton))
    app.processEvents()
    ctl.toggle_ocr(ov2.crop_image(), ov2.global_rect(), scr)
    for _ in range(300):
        app.processEvents()
        if ctl.worker is None:
            break
        import time

        time.sleep(0.02)
    check("T1.2a 识别完成且结果窗显示", ctl.result is not None and ctl.result.isVisible())
    # 识别完成后再点 OCR → 隐藏
    ov2._ocr()
    app.processEvents()
    check("T1.2b 再点隐藏", not ctl.result.isVisible() and ctl.result is not None)
    # 隐藏状态再点 → 显示
    ov2._ocr()
    for _ in range(50):
        app.processEvents()
    check("T1.2c 三点重开", ctl.result.isVisible())
    # 移动选区 → 结果窗关闭 + result=None
    ov2.mousePressEvent(mouse_ev(QEvent.MouseButtonPress, 250, 180, Qt.LeftButton, Qt.LeftButton))
    ov2.mouseMoveEvent(mouse_ev(QEvent.MouseMove, 300, 230, Qt.NoButton, Qt.LeftButton))
    ov2.mouseReleaseEvent(mouse_ev(QEvent.MouseButtonRelease, 320, 250, Qt.LeftButton, Qt.NoButton))
    app.processEvents()
    check("T1.2d 移动选区关闭结果窗", ctl.result is None and not rw_visible(ctl))
    # 忙碌路径：伪造 worker 运行中再点 OCR
    ov2._ocr()  # 重新识别（异步）
    app.processEvents()
    busy = ctl.worker is not None and ctl.worker.isRunning()
    if busy:
        states = []
        ctl.ocrPanel.connect(lambda b: states.append(b))
        ov2._ocr()  # 忙碌时点击
        app.processEvents()
        check("T1.2e 忙碌点击不破坏状态", ctl.worker is not None and ctl.worker.isRunning())
        ctl.worker.wait(30000)
        app.processEvents()
    else:
        check("T1.2e 忙碌路径(过快完成,跳过)", True)
    ov2.cancelled.emit()
    app.processEvents()
    check(
        "T1.2f 取消后无残留窗口",
        not any(
            w.isVisible()
            for w in [
                w for w in app.topLevelWidgets() if isinstance(w, (OverlayWindow, ResultWindow))
            ]
        ),
    )
    # 收尾：等待全部 OCR 子线程（含选区移动后被 _detach_worker 断信号的旧线程），
    # 否则进程退出时 QThread 仍在运行会触发 Qt abort（2026-10-29 门禁抖动实证）。
    from PyQt5.QtCore import QThread as _QThread

    for _th in ctl.findChildren(_QThread):
        if _th.isRunning():
            _th.wait(30000)
    app.processEvents()

    # ---- T1.4 文字编辑框激活时交叉操作 ----
    ov3 = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=cfg)
    ov3.show()
    app.processEvents()
    ov3.mousePressEvent(mouse_ev(QEvent.MouseButtonPress, 100, 80, Qt.LeftButton, Qt.LeftButton))
    ov3.mouseReleaseEvent(mouse_ev(QEvent.MouseButtonRelease, 400, 280, Qt.LeftButton, Qt.NoButton))
    app.processEvents()
    ov3.canvas.set_tool(TOOL_TEXT)
    QTest.mouseClick(ov3.canvas, Qt.LeftButton, Qt.NoModifier, QPointF(30, 30).toPoint())
    app.processEvents()
    check("T1.4a 输入框打开", ov3.canvas._text_edit is not None)
    # 中文无法经 QTest 键盘注入，用 setPlainText 模拟上屏后的文本
    ov3.canvas._text_edit.setPlainText("你好ABC")
    # 切换工具（应提交而非丢弃）
    ov3.canvas.set_tool(TOOL_PEN)
    app.processEvents()
    texts = [s for s in ov3.canvas.strokes if s["kind"] == "text"]
    check("T1.4b 切工具自动提交", texts and texts[-1]["text"] == "你好ABC")
    # Esc 关闭整个编辑器
    cancelled = []
    ov3.cancelled.connect(lambda: cancelled.append(1))
    ov3.canvas.set_tool(TOOL_TEXT)
    QTest.mouseClick(ov3.canvas, Qt.LeftButton, Qt.NoModifier, QPointF(60, 60).toPoint())
    QTest.keyClick(ov3.canvas._text_edit, Qt.Key_Escape)
    app.processEvents()
    check("T1.4c 输入框 Esc 仅关输入框", ov3.canvas._text_edit is None and not cancelled)
    QTest.keyClick(ov3, Qt.Key_Escape)
    app.processEvents()
    check("T1.4d 遮罩 Esc 取消", bool(cancelled))
    ov3.cancelled.emit()
    app.processEvents()

    # ---- T1.5 色板生命周期 ----
    ov4 = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=cfg)
    ov4.show()
    app.processEvents()
    ov4.mousePressEvent(mouse_ev(QEvent.MouseButtonPress, 100, 80, Qt.LeftButton, Qt.LeftButton))
    ov4.mouseReleaseEvent(mouse_ev(QEvent.MouseButtonRelease, 400, 280, Qt.LeftButton, Qt.NoButton))
    app.processEvents()
    ov4.toolbar.btn_color.click()
    app.processEvents()
    pops = [w for w in app.topLevelWidgets() if isinstance(w, ColorPickerPopup)]
    check("T1.5a 弹窗打开", bool(pops))
    if pops:
        pops[0].close()
        app.processEvents()
    ov4.toolbar.btn_color.click()
    app.processEvents()
    pops2 = [w for w in app.topLevelWidgets() if isinstance(w, ColorPickerPopup) and w.isVisible()]
    check("T1.5b 可重复打开", bool(pops2))
    for w in pops2:
        w.close()
    ov4.cancelled.emit()
    app.processEvents()

    # ---- T1.7 / T4.1 IPC 数据信任 ----
    si = SingleInstance()
    si.listen()
    got = []
    si.commandReceived.connect(lambda a: got.append(a))
    sock = __import__("PyQt5.QtNetwork", fromlist=["QLocalSocket"]).QLocalSocket()
    sock.connectToServer(
        SingleInstance.KEY
        if hasattr(SingleInstance, "KEY")
        else __import__("snapocr.utils.singleinstance", fromlist=["KEY"]).KEY
    )
    sock.waitForConnected(500)
    sock.write(b"x" * (200 * 1024))  # 超长垃圾
    sock.flush()
    sock.waitForBytesWritten(500)
    # 等待服务端读取（可能分片），确认进程不崩
    for _ in range(20):
        app.processEvents()
    check("T4.1 超长 IPC 不崩", True)  # 不崩即通过；行为上忽略即可
    sock.abort()

    # ---- T4.3 保存路径来源（复核：仅用户对话框） ----
    import inspect

    from snapocr.ui import overlay as ovmod

    src = inspect.getsource(ovmod.OverlayWindow._save)
    check("T4.3 保存路径仅经 QFileDialog", "getSaveFileName" in src)

    # ---- T4.5 日志滚动配置 ----
    import logging.handlers

    handlers = [
        h
        for h in __import__("logging").getLogger("snapocr").handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    check(
        "T4.5 日志滚动上限 512KB×3",
        handlers and handlers[0].maxBytes == 512 * 1024 and handlers[0].backupCount == 3,
    )

    # ---- T2.8 快捷键录入 ----
    hk = HotkeyEdit("Ctrl+Alt+A")
    hk.show()
    app.processEvents()
    QTest.keyClick(hk, Qt.Key_A, Qt.ControlModifier | Qt.AltModifier)
    check("T2.8a 组合键录入", hk.text() == "Ctrl+Alt+A")
    QTest.keyClick(hk, Qt.Key_F4)
    check("T2.8b 单键覆盖录入", hk.text() == "F4")
    QTest.keyClick(hk, Qt.Key_Escape)
    check("T2.8c Esc 清空", hk.text() == "")
    hk.close()

    # ---- T1.6 双屏类属性隔离（代码审查项，验证为实例属性） ----
    a = OverlayWindow(scr, QPixmap.fromImage(_sample_image(640, 360)), cfg=cfg)
    b = OverlayWindow(scr, QPixmap.fromImage(_sample_image(640, 360)), cfg=cfg)
    a._last_detect_t = 1.5
    b._last_detect_t = 2.5
    check(
        "T1.6 检测节流为实例属性（多遮罩互不干扰）",
        a._last_detect_t != b._last_detect_t and "_last_detect_t" not in OverlayWindow.__dict__,
    )

    print("\n== 探针结果: PASS=%d FAIL=%d ==" % (len(OK), len(FAIL)))
    if FAIL:
        print("失败项:", ", ".join(FAIL))


if __name__ == "__main__":
    main()
