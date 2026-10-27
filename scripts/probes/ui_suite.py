# -*- coding: utf-8 -*-
"""UI 交互探针套件（Z1~Z12）。

从 `round33_suite.py` 拆出（2026-10-26 全面回归）：原文件已达 1,115 行，
超过 `docs/10 §4.1` 的 800 行上限。拆分按主题——本文件只覆盖**界面交互**
（按钮文案/Qt 原生翻译/控件对齐/tooltip/色板/工具条定位/拖动跟手性/文字输入框），
配置与资源类用例仍留在 round33_suite。

依赖通过 `ctx` 注入（app/scr/check/skip/cfg），与 ux_suite 同款约定。
"""

import os

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QFont, QImage, QPixmap

from snapocr import i18n as _i18n
from snapocr.config import Config
from snapocr.tests.selftest import _sample_image
from snapocr.ui.editor import TOOL_PEN, TOOL_TEXT, CanvasWidget, EditorToolbar
from snapocr.ui.overlay import OverlayWindow
from snapocr.ui.result_window import ResultWindow

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(rel):
    """读工程源码文本（静态断言用，与 round33_suite 同款）。"""
    with open(os.path.join(ROOT, rel.replace("/", os.sep)), encoding="utf-8") as f:
        return f.read()


def run(ctx):
    """执行 Z1~Z12（断言计数由主文件的 check/skip 回调累加）。"""
    app = ctx.app
    scr = ctx.scr
    check = ctx.check
    cfg = ctx.cfg

    # ---- Z1~Z3 按钮改名 + Qt 原生控件翻译随语言（2026-10-26） ----
    _i18n.init_lang("zh")
    tbz = EditorToolbar()
    rwz = ResultWindow(cfg=Config())
    z1 = (
        tbz.btn_copy.text().strip() == "复制图片"
        and tbz.btn_copyfile.text().strip() == "复制为jpg文件"
        and rwz.btn_save.text().strip() == "保存"
        and rwz.btn_copyfile.text().strip() == "复制为TXT文件"
    )
    tbz.deleteLater()
    rwz.close()
    rwz.deleteLater()
    check("Z1 按钮改名(复制图片/复制为jpg文件/保存)", z1)

    from PyQt5.QtWidgets import QPlainTextEdit

    _i18n.init_lang("zh")
    pez = QPlainTextEdit()
    m_zh = pez.createStandardContextMenu()
    zh_actions = [a.text() for a in m_zh.actions() if a.text()]
    z2a = any("复制" in t for t in zh_actions) and any("粘贴" in t for t in zh_actions)
    z2b = app.translate("QDialogButtonBox", "OK") == "确定"
    _i18n.init_lang("en")
    m_en = pez.createStandardContextMenu()
    en_actions = [a.text() for a in m_en.actions() if a.text()]
    z2c = any("&Copy" in t for t in en_actions)
    _i18n.init_lang("zh")  # 恢复探针主语言
    check("Z2 Qt原生翻译随语言(zh中文/en英文)", z2a and z2b and z2c)

    z3 = (
        "qt-i18n" in _src("deploy/snapocr.spec")
        and "qt-i18n" in _src("deploy/snapocr-onefile.spec")
        and "qt-i18n" in _src("deploy/snapocr-linux.spec")
        and os.path.isfile(os.path.join(ROOT, "resources", "qt-i18n", "qtbase_zh_CN.qm"))
    )
    check("Z3 三份spec登记qt-i18n+资源在位", z3)

    # ---- Z4 行B控件高度与工具按钮齐平（2026-10-26：字号/字体下拉偏高破坏对齐） ----
    tbh = EditorToolbar()
    z4 = (
        tbh.width_combo.height() == tbh._tool_buttons["pen"].height() == 34
        and tbh.size_combo.height() == 34
        and tbh.font_combo.height() == 34
    )
    tbh.deleteLater()
    check("Z4 行B下拉高度与按钮齐平(34px)", z4)

    # ---- Z5 全项目控件高度对齐清查（2026-10-26 举一反三） ----
    from snapocr.ui.preview_dialog import PreviewDialog as _PV
    from snapocr.ui.settings_dialog import SettingsDialog as _SD

    tbz5 = EditorToolbar()
    tbz5.show()
    tbz5.set_expanded(True, animate=False)
    app.processEvents()
    # 行A：编辑按钮(有图标)与纯文字按钮等高
    za = tbz5.btn_edit.height() == tbz5.btn_cancel.height()
    # 行B：下拉与工具按钮等高
    zb = tbz5.font_combo.height() == tbz5._tool_buttons["pen"].height()
    tbz5.deleteLater()
    app.processEvents()

    imgz = QImage(60, 40, QImage.Format_RGB888)
    imgz.fill(Qt.gray)
    pvz = _PV(imgz, ctx.cfg)
    pvz.show()
    app.processEvents()
    # 预览窗：primary 按钮与普通按钮等高（border:none → border:1px transparent 修复）
    zp = pvz.btn_copy.height() == pvz.btn_save.height()
    pvz.close()
    pvz.deleteLater()
    app.processEvents()

    sdz = _SD(ctx.cfg)
    sdz.show()
    app.processEvents()
    # 设置页：combo 与 line edit 等高（QSS min-height 修复）
    zs = sdz.scale_combo.height() == sdz.dir_edit.height()
    # 设置页按钮等高
    zs2 = sdz.btn_ok.height() == sdz.btn_cancel.height()
    sdz.close()
    sdz.deleteLater()
    app.processEvents()
    check("Z5 全项目高度对齐(行A/行B/预览/设置)", za and zb and zp and zs and zs2)

    # ---- Z6~Z8 字重选择器 / tooltip / 悬停 QSS（2026-10-26 用户反馈） ----
    tbz6 = EditorToolbar()
    # Z6a 字重下拉存在且默认常规，仅文字工具可见
    z6a = (
        tbz6.weight_combo.count() == 3
        and tbz6.weight_combo.currentData() == int(QFont.Normal)
        and tbz6.weight_combo.isHidden()
    )
    tbz6.set_tool(TOOL_TEXT)
    z6a = z6a and not tbz6.weight_combo.isHidden() and tbz6.width_combo.isHidden()
    tbz6.set_tool(TOOL_PEN)
    z6a = z6a and tbz6.weight_combo.isHidden() and not tbz6.width_combo.isHidden()

    # Z6b 字重写入笔画：画布 weight → stroke["weight"] → QFont.setWeight 渲染
    basz = QImage(300, 200, QImage.Format_RGB888)
    basz.fill(Qt.white)
    cvz = CanvasWidget(basz, 1.0, mosaic_block=10)
    cvz._px_timer.stop()
    cvz.text_weight = QFont.Bold
    cvz.tool = TOOL_TEXT
    cvz._open_text_edit(QPointF(20, 20))
    cvz._text_edit.setPlainText("Z6粗体")
    cvz._commit_text_edit()
    stroke_z = cvz.strokes[-1] if cvz.strokes else {}
    z6b = stroke_z.get("weight") == int(QFont.Bold)
    # 渲染验证：粗体与常规渲染像素有差异（out_n=Normal、out_b=Bold，两次都 rebuild）
    cvz.strokes[-1]["weight"] = int(QFont.Normal)
    cvz._rebuild_layer()
    out_n = cvz.render_to_image()
    cvz.strokes[-1]["weight"] = int(QFont.Bold)
    cvz._rebuild_layer()
    out_b = cvz.render_to_image()
    diff_px = sum(
        1
        for y in range(0, out_n.height(), 3)
        for x in range(0, out_n.width(), 3)
        if out_n.pixelColor(x, y) != out_b.pixelColor(x, y)
    )
    z6b = z6b and diff_px > 10
    cvz.deleteLater()

    # Z6c 工具条四下拉 tooltip 齐备
    z6c = (
        bool(tbz6.width_combo.toolTip())
        and bool(tbz6.size_combo.toolTip())
        and bool(tbz6.weight_combo.toolTip())
        and bool(tbz6.font_combo.toolTip())
    )
    tbz6.deleteLater()
    check("Z6 文字字重选择器(可见性/笔画/渲染)+四下拉tooltip", z6a and z6b and z6c)

    # Z7 悬停 QSS：工具条按钮/下拉 hover 边框 2px；结果窗按钮 hover 同款
    from snapocr.ui.theme import qss_result, qss_settings, qss_toolbar

    _tq = qss_toolbar(
        _i18n.__class__
        and type(
            "T",
            (),
            {
                "toolbar_bg": "#f9f9f9",
                "border": "#ccc",
                "text": "#000",
                "hover": "#eee",
                "card": "#fff",
                "accent_css": "#0078d4",
                "accent_hover": "#1a86d9",
                "on_accent": "#fff",
                "icon": "#333",
            },
        )(),
        "edToolbar",
    )
    z7a = "QToolButton:hover" in _tq and "border: 2px solid" in _tq and "QComboBox:hover" in _tq
    _rq = qss_result(
        type(
            "T",
            (),
            {
                "bg": "#fff",
                "card": "#fff",
                "text": "#000",
                "subtext": "#666",
                "border": "#ccc",
                "hover": "#eee",
                "accent_css": "#0078d4",
                "accent_hover": "#1a86d9",
                "on_accent": "#fff",
            },
        )()
    )
    z7b = "QPushButton:hover" in _rq and "border: 2px solid" in _rq
    _sq = qss_settings(
        type(
            "T",
            (),
            {
                "bg": "#fff",
                "card": "#fff",
                "text": "#000",
                "subtext": "#666",
                "border": "#ccc",
                "hover": "#eee",
                "accent_css": "#0078d4",
                "accent_hover": "#1a86d9",
                "on_accent": "#fff",
            },
        )()
    )
    z7c = "QPushButton:hover" in _sq and "border-color: %(accent)s" not in _sq
    check("Z7 悬停QSS统一(border 2px accent)", z7a and z7b and z7c)

    # Z8 结果窗按钮 tooltip 齐备
    rwz8 = ResultWindow(cfg=Config())
    z8 = (
        bool(rwz8.btn_copy.toolTip())
        and bool(rwz8.btn_copyfile.toolTip())
        and bool(rwz8.btn_save.toolTip())
        and bool(rwz8.btn_rerun.toolTip())
        and bool(rwz8.btn_close.toolTip())
    )
    rwz8.close()
    rwz8.deleteLater()
    check("Z8 结果窗五按钮tooltip齐备", z8)

    # ---- Z9 色板预置当前色（架构检查：ColorPickerPopup.current 曾完全未使用） ----

    from PyQt5.QtGui import QColor as _QColor

    from snapocr.ui.editor import STANDARD_COLORS as _SC
    from snapocr.ui.editor import ColorPickerPopup as _CPP

    _cur = _QColor(_SC[0])
    cp = _CPP(_SC[0])  # 用标准色，保证 Z9c 能命中被高亮的按钮
    # 色谱光标位置应与该色的 HSV 一致（sat/val 各允许 0.02 误差）
    z9a = (
        abs(cp._sv._sat - _cur.hsvSaturationF()) < 0.02 and abs(cp._sv._val - _cur.valueF()) < 0.02
    )
    z9b = abs(cp._hue._hue - max(0.0, _cur.hsvHueF())) < 0.02
    # 当前色对应的标准色按钮应带高亮样式
    # 用 QToolButton 遍历更直接
    from PyQt5.QtWidgets import QToolButton as _QTB

    z9c = any("border" in b.styleSheet() for b in cp.findChildren(_QTB) if b.styleSheet())
    cp.deleteLater()
    check("Z9a 色板色谱预置当前色", z9a)
    check("Z9b 色板色相条预置当前色相", z9b)
    check("Z9c 色板高亮当前标准色", z9c)

    # ---- Z10 工具条左边缘稳定（2026-10-26 用户反馈）----
    # 文字工具会多出字号/字重/字体三个下拉，工具条宽度 633 → 882px。
    # 旧实现按 sel.right()-宽度 右对齐，左边缘随宽度左移 249px（点「文字」整条工具栏往左蹿）。
    # 修复：改为左边缘对齐选区左边缘，宽度变化只向右扩展。
    from PyQt5.QtCore import QRectF as _QRectF

    from snapocr.ui.editor import TOOL_PEN as _TP
    from snapocr.ui.editor import TOOL_TEXT as _TT

    _ov = OverlayWindow(scr, QPixmap.fromImage(_sample_image(800, 600)), cfg)
    _ov.show()
    app.processEvents()
    _ov.start()
    app.processEvents()
    _ov.sel = _QRectF(300, 200, 600, 400)  # 居中，保证不触发 clamp
    _ov._reposition_toolbar()
    app.processEvents()
    _x_pen = _ov.toolbar.x()
    _w_pen = _ov.toolbar.width()
    _ov.toolbar.set_tool(_TT)
    _ov._reposition_toolbar()
    app.processEvents()
    _x_text = _ov.toolbar.x()
    _w_text = _ov.toolbar.width()
    _ov.toolbar.set_tool(_TP)
    _ov._reposition_toolbar()
    app.processEvents()
    _x_back = _ov.toolbar.x()
    check("Z10a 切文字工具左边缘不变", _x_pen == _x_text)
    check("Z10b 切回画笔左边缘不变", _x_pen == _x_back)
    check("Z10c 文字态确实更宽（用例有效）", _w_text > _w_pen)

    # ---- Z11 拖动/缩放跟手性（2026-10-26 用户反馈"非常不跟手"）----
    # 根因：每次 mouseMove 都 _update_all() 整屏重绘，1080p 实测 7.7ms/帧
    # （125% 缩放下更高），叠加事件循环与合成后明显掉帧。
    # 修复：只重绘旧新选区的并集（_update_sel_dirty），选区外的底图与暗化层
    # 在拖动期间不变。实测 7.2ms → 2.5ms（dpr=1）/ 11ms → 3.6ms（dpr=1.25）。
    import time as _time

    _ov2 = OverlayWindow(scr, QPixmap.fromImage(_sample_image(800, 600)), cfg)
    _ov2.show()
    app.processEvents()
    _ov2.start()
    app.processEvents()
    _ov2.sel = _QRectF(200, 150, 900, 600)
    _ov2.finalized = True

    # 1) 结构性断言：拖动一帧的重绘面积必须远小于全屏（证明没退回全量）
    _areas = []
    _orig_upd = _ov2.update

    def _spy_upd(r=None):
        if r is not None and hasattr(r, "width"):
            _areas.append(r.width() * r.height())
        return _orig_upd(r) if r is not None else _orig_upd()

    _ov2.update = _spy_upd
    _ov2._move_sel_to(_QRectF(260, 190, 900, 600))
    app.processEvents()
    _ov2.update = _orig_upd
    _screen_area = _ov2.width() * _ov2.height()
    check(
        "Z11a 拖动只重绘局部（<60% 屏幕）",
        bool(_areas) and max(_areas) < _screen_area * 0.6,
    )

    # 2) 性能：单帧耗时应明显低于整屏重绘（阈值宽松，只防退回全量级别）
    _t0 = _time.perf_counter()
    for _i in range(15):
        _ov2._move_sel_to(_QRectF(220 + _i * 5, 160 + _i * 3, 900, 600))
        app.processEvents()
    _ms_move = (_time.perf_counter() - _t0) / 15 * 1000
    _t0 = _time.perf_counter()
    for _i in range(15):
        _ov2._resize(QPointF(1100 + _i * 3, 750 + _i * 2))
        app.processEvents()
    _ms_resize = (_time.perf_counter() - _t0) / 15 * 1000
    check("Z11b 拖动单帧 < 6ms", _ms_move < 6.0)
    check("Z11c 缩放单帧 < 6ms", _ms_resize < 6.0)

    # 3) 局部重绘不留残影（工具条移走的旧区域也要被覆盖）
    _ov2.drag_mode = "move"
    for _i in range(20):
        _ov2._move_sel_to(_QRectF(220 + _i * 8, 160 + _i * 4, 900, 600))
        app.processEvents()
    _g1 = scr.grabWindow(int(_ov2.winId())).toImage()
    _ov2.repaint()
    app.processEvents()
    from PyQt5.QtTest import QTest as _QT

    _QT.qWait(60)
    _g2 = scr.grabWindow(int(_ov2.winId())).toImage()
    _d2 = sum(
        1
        for _y in range(_g1.height())
        for _x in range(_g1.width())
        if _g1.pixelColor(_x, _y) != _g2.pixelColor(_x, _y)
    )
    check("Z11d 局部重绘无残影", _d2 == 0)

    # ---- Z12 文字输入框透明背景（2026-10-26 用户要求）----
    # 输入框覆盖在截图上，白底会把下方内容糊住、看不出"文字将落在哪"；
    # 改为透明背景 + 虚线分界，并隐藏滚动条（透明底上的灰条很突兀）。
    from PyQt5.QtGui import QImage as _QImg

    from snapocr.ui.editor import CanvasWidget as _CW

    _cimg = _QImg(600, 400, _QImg.Format_RGB888)
    _cimg.fill(_QColor("#336699"))
    _cw = _CW(_cimg, 1.0, mosaic_block=10)
    _cw.show()
    app.processEvents()
    _cw._open_text_edit(QPointF(100, 100))
    app.processEvents()
    from PyQt5.QtTest import QTest as _QT2

    _QT2.qWait(150)  # 等首次绘制完成，否则 grab 到未渲染的画面
    _te = _cw._text_edit
    _css = _te.styleSheet() if _te is not None else ""
    check("Z12a 输入框背景透明", "background: transparent" in _css)
    check("Z12b 输入框虚线边框", "border: 1px dashed" in _css)
    check("Z12c 输入框隐藏滚动条", "QScrollBar" in _css and "width: 0" in _css)
    # 像素级：框内空白行必须与底图同色（避开文字行）
    if _te is not None:
        _pg = _cw.grab().toImage()
        # grab() 返回设备像素图，而 _te 的坐标是逻辑坐标，dpr≠1 时必须换算。
        # 用图自身的 dpr：cw.dpr 是构造参数（探针传 1.0），未必等于屏幕 dpr。
        _pdpr = _pg.devicePixelRatio() or 1.0
        _c = _pg.pixelColor(int((_te.x() + 200) * _pdpr), int((_te.y() + 52) * _pdpr))
        check(
            "Z12d 框内透出底图",
            abs(_c.red() - 0x33) < 12
            and abs(_c.green() - 0x66) < 12
            and abs(_c.blue() - 0x99) < 12,
        )
    _cw.close()
    _cw.deleteLater()
    app.processEvents()
    _ov2.hide()
    _ov2.deleteLater()
    app.processEvents()
    _ov.hide()
    _ov.deleteLater()
    app.processEvents()

    # ---- Z13 拖动跟手性：8ms 间隔的 move 必须每帧跟动（2026-10-26）----
    # 旧实现每个 move 都 `_move_coalesce.start()` 重置单次定时器，125Hz 鼠标
    # （8ms 间隔）下定时器永不触发：实测 20 次 move 后选区位置一次都没变，
    # 拖动中框几乎不动、松手才跳到终点。改为时间戳节流（≥8ms 立即执行）。
    import time as _t13

    from PyQt5.QtCore import QEvent as _QEvent
    from PyQt5.QtGui import QMouseEvent as _QME

    def _drag_ev(_pos):
        return _QME(_QEvent.MouseMove, _pos, _pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)

    _ov3 = OverlayWindow(scr, QPixmap.fromImage(_sample_image(800, 600)), cfg)
    _ov3.show()
    app.processEvents()
    _ov3.start()
    app.processEvents()
    _ov3.sel = _QRectF(200, 150, 960, 540)
    _ov3._finalize()
    from PyQt5.QtTest import QTest as _QT3

    _QT3.qWait(120)
    _ov3.drag_mode = "move"
    _ov3.move_offset = QPointF(0, 0)
    _ov3._pending_move_pos = None
    _xs = []
    _frames_over = 0
    for _i in range(20):
        _p = QPointF(300 + _i * 10, 200 + _i * 5)
        _a = _t13.perf_counter()
        _ov3.mouseMoveEvent(_drag_ev(_p))
        app.processEvents()
        if (_t13.perf_counter() - _a) * 1000 > 16.7:
            _frames_over += 1
        _QT3.qWait(8)
        _xs.append(round(_ov3.sel.left()))
    _moved = sum(1 for _a, _b in zip(_xs, _xs[1:]) if _a != _b)
    check("Z13a 8ms 间隔拖动每帧跟动（≥15/19）", _moved >= 15)
    check("Z13b 拖动单帧无超预算帧", _frames_over == 0)
    # 高轮询（1000Hz）节流是设计取舍，不设断言：其行为依赖真实事件到达间隔，
    # 在探针的合成事件下不稳定（同一代码实测 0~8 次变化），守护它只会产生误报。
    _ov3.hide()
    _ov3.deleteLater()
    app.processEvents()
