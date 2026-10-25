# -*- coding: utf-8 -*-
"""UX 渲染/交互探针套件（UX-16 ~ UX-21）。

从 `scripts/test_fix_probe.py` 拆出（第二轮审计 P2-05）：原文件 1,047 行、`main()` 977 行，
新增用例只能往主函数里堆。拆分后本模块只负责这 6 段，主文件保留其余断言。

依赖通过 `Ctx` 注入（app/scr/cfg/check），避免长参数列表。
"""

import contextlib
import os

from PyQt5.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PyQt5.QtNetwork import QLocalSocket as _QLocalSocket
from PyQt5.QtTest import QTest as _QTest

from snapocr import i18n as _i18n
from snapocr.tests.selftest import _sample_image
from snapocr.ui import theme
from snapocr.ui.editor import (
    TOOL_ARROW,
    TOOL_ELLIPSE,
    TOOL_ERASER,
    TOOL_HIGHLIGHT,
    TOOL_MOSAIC,
    TOOL_PEN,
    TOOL_RECT,
    TOOL_TEXT,
    CanvasWidget,
    EditorToolbar,
)
from snapocr.ui.overlay import OverlayWindow
from snapocr.ui.preview_dialog import PreviewDialog
from snapocr.ui.result_window import ResultWindow


class Ctx:
    """探针上下文：主文件把运行期依赖打进来，避免逐项传参。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def quad_pixmap(dpr, w=800, h=600):
    """四色象限底图（设备像素 + 逻辑 dpr），用于验证取景/坐标正确性。"""
    img = QImage(int(w * dpr), int(h * dpr), QImage.Format_RGB888)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    for hexc, qx, qy in (
        ("#ff3b30", 0, 0),
        ("#34c759", 1, 0),
        ("#2f7cf6", 0, 1),
        ("#af52de", 1, 1),
    ):
        p.fillRect(
            int(qx * w * dpr / 2),
            int(qy * h * dpr / 2),
            int(w * dpr / 2),
            int(h * dpr / 2),
            QColor(hexc),
        )
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm, img


def _sweep_move(pos):
    return QMouseEvent(QEvent.MouseMove, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def _sweep_press(pos):
    return QMouseEvent(
        QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )


def _sweep_release(pos):
    return QMouseEvent(
        QEvent.MouseButtonRelease, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )


def _src_overlay() -> str:
    """读取 overlay 源码（供源码级不变量断言）。"""
    from pathlib import Path as _P

    return _P("src/snapocr/ui/overlay.py").read_text(encoding="utf-8")


def run(ctx):
    """执行 UX-16 ~ UX-21 全部断言（断言计数由主文件的 check 回调累加）。"""
    app = ctx.app
    scr = ctx.scr
    cfg = ctx.cfg
    check = ctx.check
    skip = getattr(ctx, "skip", lambda name, reason="": None)
    # ---- UX-16 遮罩选区域取景 dpr 正确性（125%/200% 缩放不错位）----
    # Qt 语义：drawPixmap(point, pixmap, sourceRect) 的 sourceRect 是设备像素矩形。
    # 历史 bug：paintEvent 直接传逻辑 sel → dpr≠1 时选区内只有左上角 1/dpr² 面积
    # 有内容，其余仍是暗化层（用户实测"框选时显示的不对"）。用四色象限底图验证。
    for dpr_val in (1.0, 2.0):
        pm_q, img_q = quad_pixmap(dpr_val)
        ovq = OverlayWindow(scr, pm_q, cfg=cfg)
        ovq.sel = QRectF(100, 90, 420, 260)
        ovq.finalized = True
        ovq.expanded = False
        ovq._mouse_pos = None
        ovq.hover_rect = None
        ovq.dragging = False
        ovq.show()
        app.processEvents()
        shot_pm = ovq.grab()
        sim = shot_pm.toImage()
        # grab 图坐标是"屏幕设备像素"（= 逻辑 × 屏 dpr），源图是 pm 设备像素
        # （= 逻辑 × pm dpr）。两者 dpr 不同时必须分别换算，不能共用一套乘数。
        grab_dpr = shot_pm.devicePixelRatio() or 1.0
        # 选区内多点采样：显示色应等于源图对应逻辑点
        pts = [(120, 100), (300, 140), (480, 300), (200, 320)]
        same = all(
            sim.pixelColor(int(lx * grab_dpr), int(ly * grab_dpr)).name()
            == img_q.pixelColor(int(lx * dpr_val), int(ly * dpr_val)).name()
            for lx, ly in pts
        )
        check(
            "UX-16 选区域取景与源图一致(dpr=%.1f)" % dpr_val,
            same and abs(ovq.dpr - dpr_val) < 0.01,
        )
        ovq.hide()
        ovq.deleteLater()
        app.processEvents()

    # ---- UX-17 主题切换残影防护（全量重绘 + 越界不清脏区）----
    ovr = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=cfg)
    ovr.sel = QRectF(100, 80, 500, 300)
    # 1) retheme 时清空 _mag_rect（让后续移动重新以全量起点记录脏区）
    ovr._mag_rect = QRectF(10, 10, 120, 120)
    ovr.retheme(theme.current())
    check("UX-17 切主题后 _mag_rect 被清空", ovr._mag_rect is None)
    # 2) 放大镜采样越界时不得清 _mag_rect（否则旧 tile 永留 backing store）
    ovr._mag_rect = QRectF(200, 200, 120, 120)
    ovr._mag_cache = None
    ovr._mag_key = None
    p_dummy = QPainter()
    ovr._draw_magnifier(p_dummy, QPointF(-500, -500))  # 远离图像 → src 为空
    p_dummy.end()
    check("UX-17 采样越界时保留旧脏区矩形", ovr._mag_rect == QRectF(200, 200, 120, 120))
    ovr.hide()
    ovr.deleteLater()
    app.processEvents()

    # ---- UX-18 双 dpr 全状态渲染 sweep（重载/坐标/残影三模式兜底）----
    # 举一反三自查（2026-10-19）：paintEvent dpr 混用、PyQt5 重载不匹配致进程 exit 127、
    # 脏矩形 backing store 残留、状态清理致旧 tile 永不清除——四个模式一次 sweep 全兜住。
    # 任一绘制路径传错坐标/触发重载不匹配，dpr=2.0 组会 abort（exit 127 无 stderr）。
    def _sweep_tools(canvas_obj):
        for tool, pa, pb in (
            (TOOL_PEN, QPointF(60, 60), QPointF(200, 120)),
            (TOOL_HIGHLIGHT, QPointF(60, 150), QPointF(220, 190)),
            (TOOL_RECT, QPointF(60, 60), QPointF(180, 120)),
            (TOOL_ELLIPSE, QPointF(60, 60), QPointF(180, 120)),
            (TOOL_ARROW, QPointF(60, 60), QPointF(180, 120)),
            (TOOL_MOSAIC, QPointF(60, 200), QPointF(180, 240)),
        ):
            canvas_obj.set_tool(tool)
            canvas_obj.mousePressEvent(_sweep_press(pa))
            canvas_obj.mouseMoveEvent(_sweep_move(pb))
            canvas_obj.mouseReleaseEvent(_sweep_release(pb))
            app.processEvents()
        try:
            canvas_obj.set_tool(TOOL_TEXT)
            canvas_obj.mousePressEvent(_sweep_press(QPointF(90, 100)))
            app.processEvents()
            if canvas_obj._text_edit is not None:
                canvas_obj._text_edit.setPlainText("sweep")
                canvas_obj._commit_text_edit()
        except Exception:
            pass

    for sweep_dpr in (1.0, 2.0):
        qpm, qimg = quad_pixmap(sweep_dpr)
        ovs = OverlayWindow(scr, qpm, cfg=cfg)
        # idle 放大镜（脏矩形路径）
        ovs.start()
        for p in [QPointF(120 + i * 30, 100 + i * 22) for i in range(10)]:
            ovs.mouseMoveEvent(_sweep_move(p))
            app.processEvents()
        check(
            "UX-18 sweep 放大镜脏矩形(dpr=%.1f)" % sweep_dpr,
            ovs._mag_rect is not None,
        )
        ovs.hide()
        ovs.deleteLater()
        app.processEvents()
        # 拖选 → 编辑态 → 全工具 → 合成（全绘制路径）
        ovs2 = OverlayWindow(scr, qpm, cfg=cfg)
        ovs2.start()
        ovs2.mousePressEvent(_sweep_press(QPointF(80, 70)))
        for p in [QPointF(80 + i * 40, 70 + i * 26) for i in range(8)]:
            ovs2.mouseMoveEvent(_sweep_move(p))
            app.processEvents()
        ovs2.mouseReleaseEvent(_sweep_release(QPointF(400, 278)))
        app.processEvents()
        ok_final = ovs2.finalized and ovs2.canvas is not None
        sr = ovs2.sel
        shot_s = ovs2.grab()
        gd = shot_s.devicePixelRatio() or 1.0
        sim_s = shot_s.toImage()
        same = False
        if ok_final and sr is not None:
            same = all(
                sim_s.pixelColor(
                    int((sr.left() + sr.width() * fx) * gd),
                    int((sr.top() + sr.height() * fy) * gd),
                ).name()
                == qimg.pixelColor(
                    int((sr.left() + sr.width() * fx) * sweep_dpr),
                    int((sr.top() + sr.height() * fy) * sweep_dpr),
                ).name()
                for fx, fy in ((0.25, 0.25), (0.75, 0.5))
            )
        check("UX-18 sweep 选区域取景(dpr=%.1f)" % sweep_dpr, ok_final and same)
        _sweep_tools(ovs2.canvas)
        check(
            "UX-18 sweep 全工具绘制(dpr=%.1f)" % sweep_dpr,
            len(ovs2.canvas.strokes) >= 6,
        )
        check(
            "UX-18 sweep 合成图设备尺寸(dpr=%.1f)" % sweep_dpr,
            ovs2.canvas.render_to_image().size() == ovs2.canvas.base.size(),
        )
        # 编辑态整链 grab（overlay + canvas + 工具条 + 标注层）
        ovs2.grab()
        check("UX-18 sweep 编辑态 grab(dpr=%.1f)" % sweep_dpr, True)
        # 残影模式：越界后可恢复迁移
        ovs2._draw_magnifier(QPainter(), QPointF(-999, -999))
        ovs2.mouseMoveEvent(_sweep_move(QPointF(600, 400)))
        app.processEvents()
        check(
            "UX-18 sweep 放大镜越界恢复(dpr=%.1f)" % sweep_dpr,
            ovs2._mag_rect is not None,
        )
        ovs2.hide()
        ovs2.deleteLater()
        app.processEvents()

    # ---- UX-19 截图会话与输入法解耦（点托盘不再让语言栏闪现/托盘位移）----
    # 根因：默认所有窗口 WA_InputMethodEnabled=True，遮罩 activateWindow 后 Windows
    # TSF 在任务栏语言栏显示输入法标识，占位导致托盘图标左移、关闭后右移，用户点托盘
    # 位置错位点空。修复：遮罩/工具条/预览窗禁输入法关联；文本编辑控件单独保留。
    ovi = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=cfg)
    ovi.sel = QRectF(100, 80, 500, 300)
    check("UX-19 遮罩禁用输入法关联", not ovi.testAttribute(Qt.WA_InputMethodEnabled))
    ovi._finalize()
    check(
        "UX-19 工具条（子控件）继承禁用",
        not ovi.toolbar.testAttribute(Qt.WA_InputMethodEnabled),
    )
    # 核心不变量：禁输入法不影响键盘流（Esc 取消 / Enter 完成照常）
    cancelled = []
    ovi.cancelled.connect(lambda: cancelled.append(1))
    ovi.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    check("UX-19 禁输入法后 Esc 仍取消截图", bool(cancelled))
    ovi.hide()
    ovi.deleteLater()
    app.processEvents()
    # 结果窗：本体禁、可编辑文本区保留
    rwi = ResultWindow(cfg=cfg)
    check("UX-19 结果窗本体禁输入法", not rwi.testAttribute(Qt.WA_InputMethodEnabled))
    check(
        "UX-19 结果窗文本编辑保留输入法",
        rwi.text.testAttribute(Qt.WA_InputMethodEnabled),
    )
    rwi.close()
    rwi.deleteLater()
    app.processEvents()
    # 预览窗：全按钮窗，本体禁
    pvi = PreviewDialog(_sample_image(320, 200), cfg)
    check("UX-19 预览窗禁输入法", not pvi.testAttribute(Qt.WA_InputMethodEnabled))
    pvi.close()
    pvi.deleteLater()
    app.processEvents()

    # ---- UX-20 七种工具共用同一套粗细档位（2/5/10/16，严格统一笔宽）----
    # 历史问题：涂色 max(w,10*dpr) 下限使细/中/粗三档实际都是 10px；橡皮"半径=档位"
    # 视觉粗一倍；箭头杆 ×0.75 偏细。统一后：同档位所有工具笔宽/直径完全一致。
    from snapocr.ui.editor import WIDTHS as _W

    check("UX-20 档位值 2/5/10/16", [w for w, _ in _W] == [2, 5, 10, 16])
    cw_w = CanvasWidget(_sample_image(400, 300), 1.0, mosaic_block=10)
    check("UX-20 默认适中档(5)", cw_w.line_width == 5)
    cw_w.show()
    app.processEvents()

    def _press_width(tool, lw):
        """设档位 → 选中工具 → 按下一次 → 返回该工具笔迹宽度（设备像素）。"""
        cw_w.line_width = lw
        cw_w.set_tool(tool)
        cw_w.mousePressEvent(_sweep_press(QPointF(100, 100)))
        w_dev = None
        if cw_w._current is not None:
            w_dev = cw_w._current.get("width")
        cw_w._current = None
        return w_dev

    dev_expected = int(10 * cw_w.dpr)  # 粗档 10px 在 dpr=1 下即 10
    same_tools = [
        TOOL_PEN,
        TOOL_HIGHLIGHT,
        TOOL_RECT,
        TOOL_ELLIPSE,
        TOOL_ARROW,
        TOOL_MOSAIC,
    ]
    widths = {t: _press_width(t, 10) for t in same_tools}
    check(
        "UX-20 六种工具同档位笔宽一致(粗档=10)",
        all(v == dev_expected for v in widths.values()),
    )
    # 橡皮擦：存的是直径，应等于档位（不再翻倍）
    erase_w = _press_width(TOOL_ERASER, 10)
    check("UX-20 橡皮直径=档位(不再翻倍)", erase_w == dev_expected)
    # 涂色细档不再被抬到 10px
    hl_thin = _press_width(TOOL_HIGHLIGHT, 2)
    check("UX-20 涂色细档=2px(无 10px 下限)", hl_thin == int(2 * cw_w.dpr))
    # 橡皮光标与档位同径（pixmap 宽 = 直径 + 2 描边）
    cw_w.line_width = 16
    cw_w._update_eraser_cursor()
    cur_w = cw_w.cursor().pixmap().width()
    check("UX-20 橡皮光标随档位变化(16档)", cur_w == max(8, 16) + 2)
    cw_w.hide()
    cw_w.deleteLater()
    app.processEvents()

    # ---- UX-21 优化指南书 P1 修复回归（语言判定/分片 IPC/副屏坐标/i18n 文案）----

    # 1) 系统语言判定：不再用弃用的 locale.getdefaultlocale，env 优先级保持一致
    _env_keys = ("LC_ALL", "LC_CTYPE", "LANG")
    _old_env = {k: os.environ.get(k) for k in _env_keys}
    _old_lang = _i18n._current
    try:
        for k in _env_keys:
            os.environ.pop(k, None)
        os.environ["LANG"] = "en_US.UTF-8"
        _i18n.init_lang("")
        check("UX-21 系统英文(LANG)判为 en", _i18n.tr("capture") == "Capture")
        os.environ["LANG"] = "zh_CN.UTF-8"
        _i18n.init_lang("")
        check("UX-21 系统中文(LANG)判为 zh", _i18n.tr("capture") == "截屏")
    finally:
        for k, v in _old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _i18n.init_lang(_old_lang if _old_lang in ("zh", "en") else "zh")

    # 2) 分片 IPC：拼齐后才派发，且不得派发空命令（曾导致误触发截屏）
    import json as _json

    import snapocr.utils.singleinstance as _si

    _old_key = _si.KEY
    _si.KEY = "snapocr.probe.fragment.v1"
    _srv = _si.SingleInstance()
    _got = []
    _srv.commandReceived.connect(lambda a: _got.append(a))
    _srv.listen()
    _cl = _QLocalSocket()
    _cl.connectToServer(_si.KEY)
    _cl.waitForConnected(600)
    _payload = _json.dumps(["--settings"]).encode()
    _cl.write(_payload[:5])
    _cl.flush()
    _cl.waitForBytesWritten(300)
    app.processEvents()
    _cl.write(_payload[5:])
    _cl.flush()
    _cl.waitForBytesWritten(300)
    _t = QElapsedTimer()
    _t.start()
    while _t.elapsed() < 800 and not _got:
        app.processEvents()
    check("UX-21 IPC 分片拼齐后派发完整命令", _got == [["--settings"]])
    with contextlib.suppress(Exception):
        _srv._server.close()
    _si.KEY = _old_key

    # 3) 副屏窗口识别：mapToGlobal 已含屏幕偏移，不得重复叠加
    import snapocr.platform.windowdetect as _wd

    _ovp = OverlayWindow.__new__(OverlayWindow)
    _ovp.dpr = 1.0
    _ovp.screen_rect = QRectF(1920, 0, 1920, 1080)
    _ovp.mapToGlobal = lambda p: QPointF(2020.0, 100.0)
    _ovp.rect = lambda: QRectF(0, 0, 1920, 1080)
    _seen = {}
    _orig_descend = _wd.descend_rect_at
    _wd.descend_rect_at = lambda x, y: _seen.update(phys=(x, y)) or (2020, 100, 2100, 200)
    try:
        OverlayWindow._compute_window_rect(_ovp, QPointF(100, 100))
    finally:
        _wd.descend_rect_at = _orig_descend
    check("UX-21 副屏窗口识别坐标不重复叠加", _seen.get("phys") == (2020.0, 100.0))

    # 4) 用户可见文案走 i18n：档位名与语言下拉首项（U7：默认项=跟随系统，不再提 Chinese）
    _i18n.init_lang("en")
    check("UX-21 线宽档位键英文", _i18n.tr("width_thin") == "Thin")
    check("UX-21 语言下拉首项英文", _i18n.tr("lang_default") == "Follow system")
    _tb_i = EditorToolbar()
    check("UX-21 工具条档位显示英文", _tb_i.width_combo.itemText(0) == "Thin")
    _tb_i.deleteLater()
    _i18n.init_lang("zh")
    check("UX-21 档位键中文回落", _i18n.tr("width_thin") == "细")
    app.processEvents()

    # ---- UX-23 dpr≠1 拖动残影防御（2026-10-21 客户机反馈）----
    # 现象：Windows 100% 缩放拖动选区正常；>100%（125%/150%/200%）出现竖条残影。
    # 根因（代码推理 + 本地 QT_SCALE_FACTOR 模拟无法复现，属合成层差异）：
    #   dpr≠1 时 Qt 把逻辑 dirty rect 换算设备像素存在 rounding，若 backing store
    #   宽 = ceil(w*dpr) 而 dirty 宽 = floor(w*dpr)，最右/最下一列设备像素永不重绘；
    #   隐式 drawPixmap(0,0,pm) 的底图尺寸也可能差 1 设备像素。
    # 修复：全量更新走 _update_all()（目标 rect 外扩 1 逻辑 px）+ 底图显式铺满
    #   目标矩形 + 放大镜脏区余量 ±3。以下断言守住这三个不变量。
    ovd = OverlayWindow(scr, QPixmap.fromImage(_sample_image(800, 600)), cfg)
    ovd.show()
    app.processEvents()
    _caught = []
    _orig_update = ovd.update
    ovd.update = lambda r: _caught.append(r)
    ovd._update_all()
    ovd.update = _orig_update
    _r = _caught[0]
    check(
        "UX-23 全量更新覆盖窗口+1px",
        _r.left() <= -1
        and _r.top() <= -1
        and _r.right() >= ovd.width()
        and _r.bottom() >= ovd.height(),
    )
    # 放大镜脏区必须覆盖放大镜矩形外扩 8px（dpr≠1 的 rounding + 1.5px 笔宽 +
    # drawImage 缩放边缘；实测 ±3 在 125% 缩放下每步残留一行，±8 清零）
    ovd._mouse_pos = QPointF(100, 100)
    _caught2 = []
    ovd.update = lambda r: _caught2.append(r)
    ovd._mag_rect = None
    ovd._update_magnifier_dirty(QPointF(100, 100))
    ovd.update = _orig_update
    _expect = ovd._magnifier_rect(QPointF(100, 100))
    check(
        "UX-23 放大镜脏区余量≥8px",
        bool(_caught2) and _caught2[0].contains(_expect.toAlignedRect().adjusted(-8, -8, 8, 8)),
    )
    # 底图显式铺满：paintEvent 用目标矩形而非隐式尺寸
    ovd.repaint()
    check(
        "UX-23 底图显式铺满目标矩形", "QRect(0, 0, self.width(), self.height())" in _src_overlay()
    )
    ovd.hide()
    ovd.deleteLater()
    app.processEvents()
    # 真实复现路径（需 dpr≠1 屏幕或 QT_SCALE_FACTOR 环境）：从右下往左上 hover
    # 移动——该方向会触发 _magnifier_rect 的翻转分支，是残影的确定性触发条件。
    _dpr = scr.devicePixelRatio()
    if abs(_dpr - 1.0) > 0.01:
        # 底图必须与屏幕同 dpr（否则 overlay.self.dpr 与真实窗口 dpr 不一致，
        # 放大镜 tile 的缩放基准就错了，测不出真实残影）
        _qimg = _sample_image(int(scr.size().width() * _dpr), int(scr.size().height() * _dpr))
        _qpm = QPixmap.fromImage(_qimg)
        _qpm.setDevicePixelRatio(_dpr)
        ovh = OverlayWindow(scr, _qpm, cfg)
        ovh.show()
        app.processEvents()
        ovh.start()
        app.processEvents()
        for _i in range(30):
            ovh.mouseMoveEvent(_sweep_move(QPointF(1400 - _i * 40, 780 - _i * 23)))
            app.processEvents()
        _g1 = scr.grabWindow(int(ovh.winId())).toImage()
        ovh.repaint()
        app.processEvents()
        _g2 = scr.grabWindow(int(ovh.winId())).toImage()
        _d = sum(
            1
            for _y in range(_g1.height())
            for _x in range(_g1.width())
            if _g1.pixelColor(_x, _y) != _g2.pixelColor(_x, _y)
        )
        check("UX-23 HiDPI 右下→左上 hover 无残影", _d == 0)
        ovh.hide()
        ovh.deleteLater()
        app.processEvents()
    else:
        skip("UX-23 HiDPI hover 复现", "dpr=1.0，需高分屏或 QT_SCALE_FACTOR")

    # ---- UX-24 贴屏幕边缘 hover 无残影（2026-10-22 客户机反馈）----
    # 根因：指针贴边时 _draw_magnifier 的 src 被 img.rect() 裁成非正方形，
    # scaled(KeepAspectRatioByExpanding) 产出超标 tile（如 150×300），drawImage
    # 画出比放大镜框大一倍的区域 → 超出脏区的部分永久残留（竖线/横线）。
    # 修复：IgnoreAspectRatio + 翻转/跳变帧走全量。
    if abs(_dpr - 1.0) > 0.01:
        _W, _H = scr.size().width(), scr.size().height()

        def _edge_case(title, paths):
            _o = OverlayWindow(scr, _qpm, cfg)
            _o.show()
            app.processEvents()
            _o.start()
            app.processEvents()
            for _pos in paths:
                _o.mouseMoveEvent(_sweep_move(_pos))
                _QTest.qWait(8)
            _a = scr.grabWindow(int(_o.winId())).toImage()
            _o.repaint()
            app.processEvents()
            _b = scr.grabWindow(int(_o.winId())).toImage()
            _d = sum(
                1
                for _y in range(_a.height())
                for _x in range(_a.width())
                if _a.pixelColor(_x, _y) != _b.pixelColor(_x, _y)
            )
            check("UX-24 %s" % title, _d == 0)
            _o.hide()
            _o.deleteLater()
            app.processEvents()
            _QTest.qWait(150)

        # _qpm 复用 UX-23 已构造的屏幕尺寸底图
        _edge_case("贴右边缘 下→上", [QPointF(_W - 8, _H - 10 - _i * 20) for _i in range(20)])
        _edge_case("贴上边缘 右→左", [QPointF(_W - 10 - _i * 30, 8) for _i in range(20)])
        _edge_case("贴左边缘 下→上", [QPointF(8, _H - 10 - _i * 20) for _i in range(20)])
        _edge_case("贴右下角原地抖动", [QPointF(_W - 6, _H - 6) for _i in range(10)])
    else:
        skip("UX-24 贴边缘 hover 复现", "dpr=1.0，需高分屏或 QT_SCALE_FACTOR")
