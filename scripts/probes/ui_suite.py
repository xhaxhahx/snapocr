# -*- coding: utf-8 -*-
"""UI 交互探针套件（Z1~Z12）。

从 `round33_suite.py` 拆出（2026-10-26 全面回归）：原文件已达 1,115 行，
超过 `docs/10 §4.1` 的 800 行上限。拆分按主题——本文件只覆盖**界面交互**
（按钮文案/Qt 原生翻译/控件对齐/tooltip/色板/工具条定位/拖动跟手性/文字输入框），
配置与资源类用例仍留在 round33_suite。

依赖通过 `ctx` 注入（app/scr/check/skip/cfg），与 ux_suite 同款约定。
"""

import contextlib
import os

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPixmap

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
    _ov2._move_sel_to(QPointF(260, 190))
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
        _ov2._move_sel_to(QPointF(220 + _i * 5, 160 + _i * 3))
        app.processEvents()
    _ms_move = (_time.perf_counter() - _t0) / 15 * 1000
    _t0 = _time.perf_counter()
    for _i in range(15):
        _ov2._resize(QPointF(1100 + _i * 3, 750 + _i * 2))
        app.processEvents()
    _ms_resize = (_time.perf_counter() - _t0) / 15 * 1000
    check("Z11b 拖动单帧 < 12ms（防明显退化）", _ms_move < 12.0)
    check("Z11c 缩放单帧 < 12ms（防明显退化）", _ms_resize < 12.0)

    # 3) 局部重绘必须覆盖"工具条移走后的旧位置"——原先靠抓屏比对像素，但抓屏要走
    # DWM 合成、时序不稳（实测连跑 5 次误报 2 次）。改为结构断言：spy update 区域，
    # 断言某次重绘覆盖了工具条旧 geometry。真残影（漏重绘）会直接让这条失败。
    _ov2.drag_mode = "move"
    _ov2._last_move_t = 0.0
    _tb_old = _ov2.toolbar.geometry()
    _areas2 = []
    _orig_upd2 = _ov2.update

    def _spy2(r=None):
        if r is not None and hasattr(r, "width"):
            _areas2.append(r)
        return _orig_upd2(r) if r is not None else _orig_upd2()

    _ov2.update = _spy2
    _ov2._move_sel_to(QPointF(int(_ov2.sel.left()) + 220, int(_ov2.sel.top()) + 160))
    app.processEvents()
    _ov2.update = _orig_upd2
    check(
        "Z11d 工具条旧位置被重绘覆盖（无残影）",
        any(r.intersects(_tb_old) for r in _areas2),
    )

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
    # 确定性验证节流逻辑（不依赖 qWait 精度与机器负载）：
    # 清掉时间戳 → 下一次 move 必须**立即**生效；紧接着再 move（<8ms）→ 必须**挂起**。
    # 旧 bug 的表现是"每次 start() 重置定时器，任何情况下都不生效"，这里两条都能抓到。
    _ov3._last_move_t = 0.0
    _x0 = _ov3.sel.left()
    _ov3._request_move(QPointF(_x0 + 40, _ov3.sel.top()))
    _immediate = _ov3.sel.left() != _x0
    # 首次执行本身可能耗时 >8ms（含 img.copy 与重绘），若不重置时间戳，
    # 第二次调用会被判为"已过间隔"而立即执行，导致偶发误报。
    _ov3._last_move_t = _time.monotonic()
    _ov3._request_move(QPointF(_x0 + 80, _ov3.sel.top()))
    _parked = _ov3._pending_move_pos is not None
    check("Z13a 节流：≥8ms 立即执行（跟手）", _immediate)
    check("Z13a2 节流：<8ms 挂起并由定时器补执行", _parked)
    # 释放时补执行，位置定格到最后一次请求
    _ov3._apply_pending_move()
    check("Z13a3 挂起位置在补执行后生效", _ov3.sel.left() == _x0 + 80)
    # 高轮询（1000Hz）节流是设计取舍，不设断言：其行为依赖真实事件到达间隔，
    # 在探针的合成事件下不稳定（同一代码实测 0~8 次变化），守护它只会产生误报。
    _ov3.hide()
    _ov3.deleteLater()
    app.processEvents()

    # ---- Z14 举一反三：同类"高频事件 + 全量重算"缺陷（2026-10-27）----
    # 与 _move_coalesce 同源的三处：马赛克底图冻结、流式文本 O(n²)、笔画层每帧重建。
    import time as _t14

    from PyQt5.QtGui import QImage as _QImg14

    from snapocr.ui.editor import TOOL_MOSAIC as _TM14

    class _Ev14:
        def __init__(self, _p):
            self._p = _p

        def pos(self):
            return self._p

        def button(self):
            return Qt.LeftButton

        def buttons(self):
            return Qt.LeftButton

    # a) 马赛克：换底图后（全图重建未跟上）画面必须显示新内容，而不是冻结旧内容
    _b14 = _QImg14(400, 300, _QImg14.Format_RGB888)
    _b14.fill(QColor("#ff0000"))
    _cw14 = CanvasWidget(_b14, 1.0, mosaic_block=20)
    _cw14.show()
    app.processEvents()
    _cw14.set_tool(_TM14)
    _cw14.mousePressEvent(_Ev14(QPointF(150, 120)))
    _cw14.mouseMoveEvent(_Ev14(QPointF(250, 180)))
    _cw14.mouseReleaseEvent(_Ev14(QPointF(250, 180)))
    from PyQt5.QtTest import QTest as _QT14

    _QT14.qWait(200)
    _g14 = _QImg14(400, 300, _QImg14.Format_RGB888)
    _g14.fill(QColor("#00ff00"))
    _cw14.set_base(_g14)  # 拖动一帧：底图换绿，全图 _pixelated 仍是旧的
    _QT14.qWait(60)
    _img14 = _cw14.grab().toImage()
    _d14 = _img14.devicePixelRatio() or 1.0
    _pc = _img14.pixelColor(int(200 * _d14), int(150 * _d14))
    check("Z14a 马赛克随底图更新（不冻结）", _pc.green() > 100 and _cw14._px_stale)
    _cw14.close()
    _cw14.deleteLater()
    app.processEvents()

    # b) 流式文本：300 行累计必须远低于 O(n²) 基线（改前 370ms）
    _rw14 = ResultWindow(cfg=Config())
    _rw14.show()
    app.processEvents()
    _rw14._stream_lines = []
    _rw14.text.setPlainText("")
    _rw14._last_stream_render = 0.0
    _t14a = _t14.perf_counter()
    for _i in range(300):
        _rw14.stream_line("第 %d 行识别文本示例 ABC" % _i, _i + 1, 300)
    _ms14 = (_t14.perf_counter() - _t14a) * 1000
    _lines14 = _rw14.text.toPlainText().count("\n") + 1
    check("Z14b 300 行流式 < 60ms", _ms14 < 60)
    check("Z14b2 末行强制渲染（内容完整）", _lines14 >= 300)
    _rw14.close()
    _rw14.deleteLater()
    app.processEvents()

    # c) 笔画层：拖动期间只累积位移、不重建；停顿后归位并重建
    _cw14b = CanvasWidget(_QImg14(600, 400, _QImg14.Format_RGB888), 1.0, mosaic_block=20)
    _cw14b.base.fill(QColor("#ffffff"))
    _cw14b.show()
    app.processEvents()
    _cw14b.set_tool(TOOL_PEN)
    _cw14b.color = "#ff0000"
    _cw14b.line_width = 12
    _cw14b.mousePressEvent(_Ev14(QPointF(100, 100)))
    _cw14b.mouseMoveEvent(_Ev14(QPointF(200, 100)))
    _cw14b.mouseReleaseEvent(_Ev14(QPointF(200, 100)))
    _QT14.qWait(100)
    _cw14b.set_base(_QImg14(600, 400, _QImg14.Format_RGB888))
    _cw14b.base.fill(QColor("#ffffff"))
    _cw14b.shift_strokes(50.0, 40.0)
    _QT14.qWait(50)
    _moved14 = not _cw14b._layer_offset.isNull()
    _img14b = _cw14b.grab().toImage()
    _d14b = _img14b.devicePixelRatio() or 1.0
    _pc2 = _img14b.pixelColor(int(200 * _d14b), int(140 * _d14b))
    check("Z14c 拖动中笔画层只位移不重建", _moved14)
    check("Z14c2 位移后笔画画在新位置", _pc2.red() > 180 and _pc2.green() < 90)
    _QT14.qWait(260)
    check("Z14c3 停顿后位移归位并重建", _cw14b._layer_offset.isNull() and not _cw14b._px_stale)
    _cw14b.close()
    _cw14b.deleteLater()
    app.processEvents()

    # ---- Z15 重新框选后工具条跟随（2026-10-27 用户反馈）----
    # 拖动选区后不退出、立即左键重新框选：工具条已是展开态，而 `_animate_rowb`
    # 在 `start == target` 时直接 return，不重定位 → 操作栏停在旧选区位置。
    from PyQt5.QtCore import QEvent as _QE15
    from PyQt5.QtGui import QMouseEvent as _QM15

    _W15, _H15 = scr.size().width(), scr.size().height()
    _dpr15 = scr.devicePixelRatio()

    def _ev15(_t, _p, _btn=Qt.LeftButton):
        return _QM15(
            _t,
            _p,
            _p,
            _btn,
            Qt.LeftButton if _t != _QE15.MouseButtonRelease else Qt.NoButton,
            Qt.NoModifier,
        )

    _ov15 = OverlayWindow(
        scr,
        QPixmap.fromImage(_sample_image(int(_W15 * _dpr15), int(_H15 * _dpr15))),
        cfg,
    )
    _ov15.show()
    app.processEvents()
    _ov15.start()
    app.processEvents()

    def _box15(_a, _b):
        _ov15.mousePressEvent(_ev15(_QE15.MouseButtonPress, _a))
        _ov15.mouseMoveEvent(_ev15(_QE15.MouseMove, _b))
        _ov15.mouseReleaseEvent(_ev15(_QE15.MouseButtonRelease, _b))
        _QT14.qWait(340)
        return _ov15.toolbar.x(), _ov15.toolbar.y(), _ov15.toolbar.height()

    _box15(QPointF(200, 100), QPointF(700, 260))
    _tx, _ty, _th = _box15(QPointF(300, 420), QPointF(800, 580))
    check(
        "Z15a 重新框选后工具条跟随新选区",
        abs(_ty - (int(_ov15.sel.bottom()) + 8)) <= 14 and abs(_tx - int(_ov15.sel.left())) <= 14,
    )
    _tx2, _ty2, _th2 = _box15(QPointF(300, _H15 - 200), QPointF(900, _H15 - 20))
    check("Z15b 贴底框选工具条翻到选区上方", _ty2 + _th2 <= int(_ov15.sel.top()) + 6)
    _ov15.hide()
    _ov15.deleteLater()
    app.processEvents()

    # ---- Z16 预览窗：钉住 / 画布缩放拖动 / 尺寸适配 / 最小化（2026-10-28）----
    # 这批功能由用户实现并修了 6 轮 GUI 问题，此前零探针覆盖。
    from PyQt5.QtCore import QEvent as _QE16
    from PyQt5.QtCore import QPoint as _QP16
    from PyQt5.QtGui import QImage as _QI16
    from PyQt5.QtGui import QKeyEvent as _QK16
    from PyQt5.QtGui import QWheelEvent as _QW16

    from snapocr.ui.preview_dialog import PreviewCanvas as _PC16
    from snapocr.ui.preview_dialog import PreviewDialog as _PD16

    _img16 = _QI16(800, 600, _QI16.Format_RGB888)  # 4:3
    _img16.fill(QColor("#336699"))

    # a) 尺寸适配：保持纵横比 + 左上锚点
    _cv16 = _PC16(_img16)
    _cv16.resize(400, 300)
    _QT14.qWait(50)
    _d16 = _cv16.draw_size()
    check("Z16a 适配 400x300 → 400x300（4:3）", (_d16.width(), _d16.height()) == (400, 300))
    _cv16.resize(200, 300)
    _QT14.qWait(50)
    _d16b = _cv16.draw_size()
    check("Z16a2 窄窗口保持纵横比 200x150", (_d16b.width(), _d16b.height()) == (200, 150))

    # b) 滚轮缩放：步进与上下限
    def _wheel16(_delta):
        _cv16.wheelEvent(
            _QW16(
                QPointF(100, 100),
                QPointF(100, 100),
                _QP16(0, 0),
                _QP16(0, _delta),
                Qt.NoButton,
                Qt.NoModifier,
                Qt.NoScrollPhase,
                False,
            )
        )

    _wheel16(120)
    _z1 = _cv16._zoom
    check("Z16b 滚轮上滚放大", _z1 > 1.0)
    for _ in range(40):
        _wheel16(-120)
    check("Z16b2 下滚钳在下限 1.0", abs(_cv16._zoom - 1.0) < 1e-6)
    for _ in range(60):
        _wheel16(120)
    check("Z16b3 上滚钳在上限 8.0", abs(_cv16._zoom - 8.0) < 1e-6)

    # c) 拖动偏移钳制（放大后只能拖到图边缘，不会拖丢）
    _cv16._zoom = 2.0
    _cv16._offset = _QP16(-99999, -99999)
    _cv16._clamp_offset()
    _dd = _cv16.draw_size()
    check(
        "Z16c 拖动偏移钳制在图片范围内",
        _cv16._offset.x() == min(0, _cv16.width() - _dd.width())
        and _cv16._offset.y() == min(0, _cv16.height() - _dd.height()),
    )
    _cv16._offset = _QP16(500, 500)
    _cv16._clamp_offset()
    check("Z16c2 正向偏移归零（左上锚点）", _cv16._offset.x() == 0 and _cv16._offset.y() == 0)

    # d) 缩放缓存：命中时不应重新 scaled（4K 单次 22ms，每帧重算会卡）
    import time as _t16

    _big16 = _QI16(3840, 2160, _QI16.Format_RGB888)
    _big16.fill(QColor("#336699"))
    _cvb16 = _PC16(_big16)
    _cvb16.resize(640, 420)
    _QT14.qWait(50)
    _cvb16._render_image()
    _t16a = _t16.perf_counter()
    for _ in range(10):
        _cvb16._render_image()
    _ms16 = (_t16.perf_counter() - _t16a) / 10 * 1000
    check("Z16d 缩放缓存命中 < 3ms（改前 22ms）", _ms16 < 3.0)

    # e) 钉住按钮 + 最小化（结束会话但不关闭窗口）
    _pv16 = _PD16(_img16, cfg)
    _pv16.show()
    _QT14.qWait(100)
    _got16 = []
    _pv16.finished.connect(lambda: _got16.append(1))
    _pv16.btn_pin.setChecked(True)
    _QT14.qWait(30)
    check("Z16e 钉住按钮切换 pinned", _pv16.pinned is True)
    # 改用原生标题栏后不再有自绘"最小化=结束会话"按钮：验证系统最大化可用、
    # 且钉住态窗口保持可见（2026-10-28 照搬结果窗样式）
    _pv16.showMaximized()
    _QT14.qWait(60)
    _max16 = _pv16.isMaximized()
    _pv16.showNormal()
    _QT14.qWait(40)
    check("Z16e2 原生最大化可用且钉住窗口保留", _max16 and _pv16.isVisible())

    # f) 钉住态 Esc 不关窗（docs/03 §4）；未钉住时 Esc 关闭
    _pv16.keyPressEvent(_QK16(_QE16.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    _QT14.qWait(50)
    check("Z16f 钉住态 Esc 不杀窗口", _pv16.isVisible())
    _pv16.btn_pin.setChecked(False)
    _QT14.qWait(30)
    _pv16.keyPressEvent(_QK16(_QE16.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    _QT14.qWait(50)
    check("Z16f2 未钉住 Esc 关闭窗口", not _pv16.isVisible())

    _pv16.close()
    _pv16.deleteLater()
    _cv16.close()
    _cvb16.close()
    app.processEvents()

    # ---- Z17 钉住预览窗 × 会话结束后的生命周期（2026-10-28 客户机崩溃）----
    # 钉住窗寿命长于遮罩：会话结束后遮罩被销毁，若信号仍连着它，点复制/最小化会
    # 回调到已删除的 OverlayWindow（RuntimeError 甚至直接崩溃）。
    # 修复：遮罩 closeEvent 断开连接并通知"会话已结束"；_close_overlays 改用 close()
    # 触发 closeEvent（原先 hide() 不触发，导致清理逻辑形同虚设）。
    from PyQt5.QtCore import QRectF as _QR17
    from PyQt5.QtGui import QPixmap as _QP17

    _hook17 = []
    _prev_hook = getattr(app, "on_preview_closed", None)
    app.on_preview_closed = lambda: _hook17.append(1)

    def _session17(_pinned):
        _ov = OverlayWindow(scr, _QP17.fromImage(_sample_image(800, 600)), cfg)
        _ov.show()
        app.processEvents()
        _ov.start()
        app.processEvents()
        _ov.sel = _QR17(100, 100, 400, 300)
        _ov._finalize()
        _QT14.qWait(100)
        _ov._done()
        _QT14.qWait(150)
        _pv = _ov._preview
        if _pinned:
            _pv.btn_pin.setChecked(True)
            _QT14.qWait(40)
        # 模拟真实退出路径：close() + deleteLater()（与 app._close_overlays 一致）
        _ov.close()
        _ov.deleteLater()
        app.processEvents()
        _QT14.qWait(180)
        return _pv

    _pv17 = _session17(True)
    _ok17 = True
    try:
        _pv17._copy()
        _QT14.qWait(150)
    except Exception:
        _ok17 = False
    check("Z17a 会话结束后点复制不崩且窗口保留", _ok17 and _pv17.isVisible())

    _ok17b = True
    try:
        _pv17._retry()  # 会话后重试按钮已禁用，即便被程序调用也只能关窗，不得崩
        _QT14.qWait(150)
    except Exception:
        _ok17b = False
    check("Z17b 会话结束后调用重试不崩", _ok17b)
    check("Z17c 会话结束后重试按钮被禁用", not _pv17.btn_retry.isEnabled())
    check("Z17d 会话结束后复制按钮仍可用", _pv17.btn_copy.isEnabled())

    _pv17.btn_cancel.click()
    _QT14.qWait(150)
    check("Z17e 会话结束后点取消可关闭窗口", not _pv17.isVisible())
    check("Z17f 关闭预览窗触发 on_preview_closed 钩子", len(_hook17) >= 1)

    if _prev_hook is not None:
        app.on_preview_closed = _prev_hook
    else:
        with contextlib.suppress(AttributeError):
            del app.on_preview_closed
    app.processEvents()

    # ---- Z18 预览窗外观与钉住语义（2026-10-28 用户要求）----
    # a) 照搬结果窗样式：同一套 qss_result + QPalette + 自动填充背景，明暗都跟
    from snapocr.ui.theme import Theme as _Theme18

    _pv18 = _PD16(_img16, cfg)
    _pv18.show()
    _QT14.qWait(100)
    _ok18 = True
    for _dark in (False, True):
        _t18 = _Theme18(dark=_dark)
        _pv18.retheme(_t18)
        _QT14.qWait(40)
        _pal = _pv18.palette()
        if not (
            _pal.color(_pal.Window).name() == _t18.bg
            and _pal.color(_pal.Base).name() == _t18.card
            and "#resultRoot" in _pv18.styleSheet()
            and _t18.bg in _pv18.styleSheet()
        ):
            _ok18 = False
    check("Z18a 样式/调色板照搬结果窗且明暗同步", _ok18)
    check("Z18a2 自动填充背景（原生绘制部分也跟主题）", _pv18.autoFillBackground())

    # b) 钉住 ≠ 总在最前：钉住取消置顶，取消钉住恢复置顶
    _pv18.btn_pin.setChecked(True)
    _QT14.qWait(60)
    _top_pinned = bool(_pv18.windowFlags() & Qt.WindowStaysOnTopHint)
    _pv18.btn_pin.setChecked(False)
    _QT14.qWait(60)
    _top_normal = bool(_pv18.windowFlags() & Qt.WindowStaysOnTopHint)
    check("Z18b 钉住后取消置顶（钉住≠最前）", not _top_pinned)
    check("Z18b2 取消钉住后恢复置顶", _top_normal)

    # c) 钉住时再次截图不隐藏：验证 start_capture 的排除条件成立
    _pv18.btn_pin.setChecked(True)
    _QT14.qWait(40)
    check(
        "Z18c 钉住预览窗满足不隐藏条件",
        isinstance(_pv18, _PD16) and getattr(_pv18, "pinned", False) and _pv18.isVisible(),
    )
    _pv18.close()
    _pv18.deleteLater()
    app.processEvents()

    # ---- Z19 预览窗复制按钮：普通样式、纯文字、无快捷键（2026-10-28 用户要求）----
    # 此前是 primary（强调蓝）+ 文案带 "(Ctrl+C)" 后缀 + Ctrl+C/Enter 触发复制。
    # 结果窗的「复制文本」是普通按钮，用户要求预览窗保持一致。
    _pv19 = _PD16(_img16, cfg)
    _pv19.show()
    _QT14.qWait(100)
    check("Z19a 复制按钮文字只有「复制图片」", _pv19.btn_copy.text() == "复制图片")
    check("Z19b 复制按钮不用强调色（非 primary）", _pv19.btn_copy.objectName() != "primary")

    _copied19 = []
    _pv19.copyDone.connect(lambda: _copied19.append(1))

    def _key19(_k, _m=Qt.NoModifier):
        _pv19.keyPressEvent(_QK16(_QE16.KeyPress, _k, _m))
        _QT14.qWait(60)

    _key19(Qt.Key_C, Qt.ControlModifier)
    _key19(Qt.Key_Return)
    _key19(Qt.Key_Enter)
    check("Z19c 复制快捷键已取消（Ctrl+C/Enter 不复制）", not _copied19)
    _pv19.close()
    _pv19.deleteLater()
    app.processEvents()
