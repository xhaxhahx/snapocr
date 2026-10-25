# -*- coding: utf-8 -*-
"""自检：模型加载、OCR 端到端、遮罩/编辑器逻辑、UI 截图导出。
用法: python -m snapocr --selftest
"""

import os
import sys
import time


def _sample_image(w=760, h=300):
    from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen

    img = QImage(w, h, QImage.Format_RGB888)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    f = QFont("Microsoft YaHei")
    f.setPixelSize(34)
    p.setFont(f)
    p.setPen(QColor("#111111"))
    p.drawText(40, 70, "截图工具 自检测试样张")
    f.setPixelSize(24)
    p.setFont(f)
    p.drawText(40, 130, "Screenshot OCR Test 1234567890")
    p.drawText(40, 180, "信创终端 UOS 麒麟兼容验证")
    f.setPixelSize(18)
    p.setFont(f)
    p.setPen(QColor("#2f7cf6"))
    p.drawText(40, 230, "RapidOCR PP-OCRv6 offline engine, 快而准。")
    p.setPen(QPen(QColor("#dddddd"), 1))
    p.drawRect(20, 20, w - 40, h - 40)
    p.end()
    return img


def _assert(cond, name, results):
    results.append((name, bool(cond)))
    print(("  [PASS] " if cond else "  [FAIL] ") + name)
    return bool(cond)


def run_selftest(app, cfg):
    if sys.stdout is not None:  # 打包版(console=False) 双击启动时 stdout 为 None
        sys.stdout.reconfigure(encoding="utf-8")
    print("== SnapOCR 自检 ==")
    results = []
    from ..paths import app_dir

    shot_dir = os.path.join(app_dir(), "docs", "screenshots")
    os.makedirs(shot_dir, exist_ok=True)

    # 1. 模型与引擎（绿色版按设计不带 resources/models，模型由 rapidocr wheel 内置提供）
    from ..ocr import engine as E
    from ..paths import find_model

    det, cls, rec = find_model("det"), find_model("cls"), find_model("rec")
    print(
        "模型: det=%s cls=%s rec=%s"
        % (os.path.basename(det or "-"), os.path.basename(cls or "-"), os.path.basename(rec or "-"))
    )
    img = _sample_image()
    try:
        t0 = time.perf_counter()
        E.get_engine(cfg)
        load_t = time.perf_counter() - t0
        # 两种模型来源任一可用即通过：resources/models 离线副本 或 rapidocr 内置
        _assert(bool((det and rec) or E._engine is not None), "模型可用(det/rec 或内置)", results)
        bgr = E.qimage_to_bgr(img)
        res, elapsed = E.recognize_sync(cfg, bgr)
        text = " ".join(r[0] for r in res)
        print("  引擎加载 %.2fs, 识别 %.2fs, 文本: %s" % (load_t, elapsed, text[:80]))
        _assert(len(res) > 0, "OCR 返回非空", results)
        _assert("自检" in text or "OCR" in text, "识别包含关键字", results)
        # 二次识别（复用引擎）
        _, e2 = E.recognize_sync(cfg, bgr)
        print("  二次识别 %.2fs" % e2)
        _assert(e2 < 5.0, "二次识别耗时可接受", results)
        # 空白图：stream 路径须与 sync 一致按"空结果"返回，不得把上游
        # "result is empty" 异常当失败直出（2026-10-23 回归轮实证的差异）
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QImage

        blank = QImage(400, 100, QImage.Format_RGB888)
        blank.fill(Qt.white)
        res_blank, _ = E.recognize_stream(cfg, E.qimage_to_bgr(blank))
        _assert(res_blank == [], "空白图识别返回空结果(非失败)", results)
    except Exception as e:
        _assert(False, "OCR 引擎: %s" % e, results)

    # 3. 遮罩逻辑（不真上屏）
    from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt
    from PyQt5.QtGui import QGuiApplication, QPixmap
    from PyQt5.QtWidgets import QApplication

    from ..ui.editor import TOOL_MOSAIC, TOOL_PEN
    from ..ui.overlay import OverlayWindow

    scr = QApplication.primaryScreen()
    pm = QPixmap.fromImage(_sample_image(1280, 720))
    ov = OverlayWindow(scr, pm, cfg=cfg)
    ov.sel = QRectF(100, 80, 500, 300)
    crop = ov.crop_image()
    # crop 使用内容矩形（选区内缩边框 2px）
    _assert(crop.width() == 496 and crop.height() == 296, "遮罩裁剪尺寸", results)

    # 进入编辑态（工具条+画布嵌入遮罩）
    ov._finalize()
    ov._on_edit_toggle(True)
    app.processEvents()
    _assert(ov.canvas is not None and ov.toolbar.isVisibleTo(ov), "编辑态展开", results)
    c = ov.canvas
    c.set_tool(TOOL_PEN)
    # 模拟画笔笔画
    c._current = {
        "kind": "pen",
        "pts": [QPointF(60 * c.dpr, 60 * c.dpr), QPointF(200 * c.dpr, 90 * c.dpr)],
        "color": "#ff3b30",
        "width": 4,
    }
    c.mouseReleaseEvent(QEvent(QEvent.MouseButtonRelease))
    c.set_tool(TOOL_MOSAIC)
    c._px_timer.stop()  # C2 首建已改防抖：自检同步构建马赛克底图，保证渲染断言确定性
    c._rebuild_pixelated()
    from PyQt5.QtGui import QPainterPath

    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    path.addRect(300 * c.dpr, 40 * c.dpr, 200 * c.dpr, 80 * c.dpr)
    c._current = {"kind": "mosaic", "path": path, "width": 20}
    c.mouseReleaseEvent(QEvent(QEvent.MouseButtonRelease))
    n_before = len(c.strokes)
    c.undo()
    _assert(len(c.strokes) == n_before - 1, "撤销笔画", results)
    c.redo()
    out = c.render_to_image()
    _assert(out.width() == crop.width() and not out.isNull(), "合成渲染", results)
    out.save(os.path.join(shot_dir, "editor_render.png"))
    ov.grab().save(os.path.join(shot_dir, "editor_ui.png"))
    # 剪贴板
    QGuiApplication.clipboard().setImage(c.render_to_image())
    app.processEvents()
    cb = QGuiApplication.clipboard().image()
    _assert(not cb.isNull(), "复制到剪贴板", results)

    # 5. 结果窗口
    from ..ui.result_window import ResultWindow

    rw = ResultWindow()
    rw.set_results(
        [("截图工具 自检测试样张", 0.98, None), ("Screenshot OCR Test 1234567890", 0.97, None)],
        0.42,
    )
    rw.grab().save(os.path.join(shot_dir, "result_ui.png"))
    _assert("OCR Test" in rw.text.toPlainText(), "结果窗口内容", results)
    rw.close()

    # 6. 设置窗口
    from ..ui.settings_dialog import SettingsDialog

    sd = SettingsDialog(cfg)
    sd.grab().save(os.path.join(shot_dir, "settings_ui.png"))
    sd.close()

    # 7. 托盘图标
    from ..ui import icons

    _assert(not icons.pixmap("app").isNull(), "托盘图标生成", results)

    fails = [n for n, ok in results if not ok]
    print("== 自检完成: %d 项, 失败 %d ==" % (len(results), len(fails)))
    if fails:
        print("失败项:", ", ".join(fails))
    return 1 if fails else 0
