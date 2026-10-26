# -*- coding: utf-8 -*-
"""§33 修复项 + 用户视角轮（U/R）探针（A1~A11 / C1~C3 / U1~U10 / R1~R4）。

从 `scripts/test_fix_probe.py` 拆出（该文件已 735 行，宪法 §4.1 单文件 800 行上限）。
依赖通过 `Ctx` 注入；写盘类用例（A1/A2/C1）直接复用主文件重定向后的
`snapocr.config.config_file`（.tmp/probe_config.json），不触碰真实配置。
A5（真实 RegisterHotKey）与 A11（listen）均带环境守卫，不满足时 SKIP。
"""

import contextlib
import json
import os
import time

from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt
from PyQt5.QtGui import QImage, QMouseEvent, QPixmap
from PyQt5.QtNetwork import QLocalSocket
from PyQt5.QtTest import QTest

from snapocr.config import Config
from snapocr.ui.editor import TOOL_PEN, TOOL_TEXT, CanvasWidget
from snapocr.ui.overlay import OverlayWindow
from snapocr.ui.result_window import ResultWindow
from snapocr.ui.settings_dialog import HotkeyEdit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(rel):
    """读工程源码文本（静态断言用）。"""
    with open(os.path.join(ROOT, rel.replace("/", os.sep)), encoding="utf-8") as f:
        return f.read()


class Ctx:
    """探针上下文：主文件把运行期依赖打进来，避免逐项传参。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _press(pos):
    return QMouseEvent(
        QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )


def _release(pos):
    return QMouseEvent(
        QEvent.MouseButtonRelease, pos, pos, Qt.LeftButton, Qt.NoButton, Qt.NoModifier
    )


def _move(pos):
    return QMouseEvent(QEvent.MouseMove, pos, pos, Qt.NoButton, Qt.LeftButton, Qt.NoModifier)


def run(ctx):
    """执行 §33 全部可自动化断言（计数由主文件的 check/skip 回调累加）。"""
    app = ctx.app
    scr = ctx.scr
    check = ctx.check
    skip = ctx.skip
    cfg = ctx.cfg  # 配置已由主探针重定向到 .tmp，构造窗口可安全复用
    cfg_path = ctx.cfg_path  # 已重定向到 .tmp/probe_config.json
    from snapocr import i18n as _i18n
    from snapocr.tests.selftest import _sample_image

    # ---- A1 非 DEFAULTS 键重启回读（原缺陷：首次提示每次启动都弹） ----
    cfg1 = Config()
    cfg1.set("autostart_shown_tip", True)
    cfg1._flush_now()  # 探针不等 0.3s 去抖窗口，同步落盘
    check("A1 首次提示键重启可回读", Config().get("autostart_shown_tip") is True)
    cfg1.set("autostart_shown_tip", False)
    cfg1._flush_now()

    # ---- A2 脏配置类型校验（合法键保留、脏类型回落默认） ----
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write('{"save_dir": 123, "ocr_threads": "abc", "hotkey": "Ctrl+Alt+Z"}')
    cfg2 = Config()
    check(
        "A2 脏类型回落默认且合法键保留",
        cfg2.get("save_dir") == ""
        and cfg2.get("ocr_threads") == 0
        and cfg2.get("hotkey") == "Ctrl+Alt+Z",
    )

    # ---- A3 失败终态清空流式缓存 ----
    rw3 = ResultWindow(cfg=ctx.cfg)
    rw3.begin_stream()
    rw3.stream_line("半截", 1, 2)
    rw3.set_error("boom")
    rw3.cycle_wrap()
    check("A3 失败后切换换行不冒半截文字", rw3.text.toPlainText() == "")
    rw3.close()
    rw3.deleteLater()

    # ---- A4 TXT 默认文件名走 i18n（中英双语） ----
    _i18n.init_lang("en")
    check("A4 TXT 文件名英文", (_i18n.tr("default_txt_filename") % "x") == "ocr_text_x.txt")
    _i18n.init_lang("zh")
    check("A4 TXT 文件名中文", (_i18n.tr("default_txt_filename") % "x") == "OCR_文本_x.txt")

    # ---- A5 改键失败回滚旧热键（真实 RegisterHotKey，带环境守卫） ----
    if os.name == "nt":
        from snapocr.platform.hotkey_win import HotkeyManager

        hm = HotkeyManager()
        if hm.register("Ctrl+Alt+B"):
            prev = hm.current()
            failed = hm.register("Ctrl+Alt+Del")  # Del 不在 _vk_for_key → 必走失败分支
            check("A5 改键失败回滚旧热键", failed is False and hm.current() == prev)
            hm.unregister()
        else:
            skip("A5 改键失败回滚", "Ctrl+Alt+B 被其他程序占用，无法搭建前置条件")
    else:
        skip("A5 改键失败回滚", "非 Windows 平台")

    # ---- A6 无修饰键单键拒绝录入（F 键仍允许） ----
    he = HotkeyEdit("")
    he.show()
    app.processEvents()
    QTest.keyClick(he, Qt.Key_A)
    a6_single = he.text()
    QTest.keyClick(he, Qt.Key_F6)
    a6_fkey = he.text()
    QTest.keyClick(he, Qt.Key_C, Qt.ControlModifier | Qt.AltModifier)
    a6_combo = he.text()
    he.hide()
    he.deleteLater()
    check(
        "A6 单键拒绝/F键与组合键允许",
        a6_single == "" and a6_fkey == "F6" and a6_combo == "Ctrl+Alt+C",
    )

    # ---- A7 结果窗关闭释放输入图 ----
    from PyQt5.QtCore import QObject

    from snapocr.app import CaptureController

    class _StubApp(QObject):
        once = False
        toast = None

    _StubApp.cfg = ctx.cfg
    ctrl7 = CaptureController(_StubApp())
    img7 = QImage(64, 64, QImage.Format_RGB888)
    ctrl7._last_input = img7
    ctrl7._result_closed()
    check("A7 结果窗关闭释放输入图", ctrl7._last_input is None)

    # ---- A9 单击未位移不发 selectionMoved，真实位移才发 ----
    pm = QPixmap.fromImage(_sample_image(640, 480))
    ov9 = OverlayWindow(scr, pm, cfg=ctx.cfg)
    ov9.resize(640, 480)
    ov9.sel = QRectF(100, 100, 200, 150)
    # 屏蔽窗口边缘吸附（探测真实桌面窗口，结果随环境漂移），探针只验位移语义
    ov9._snap_target_at = lambda pos: None
    ov9._finalize()
    fired = []
    ov9.selectionMoved.connect(lambda: fired.append(1))
    center = QPointF(150, 150)
    ov9.mousePressEvent(_press(center))
    ov9.mouseReleaseEvent(_release(center))  # 原地按下即释放（单击）
    app.processEvents()
    a9_click = len(fired)
    ov9.mousePressEvent(_press(center))
    ov9.mouseMoveEvent(_move(QPointF(200, 190)))  # 真实拖动
    ov9.mouseReleaseEvent(_release(QPointF(200, 190)))
    app.processEvents()
    check(
        "A9 单击不发信号/位移才发",
        a9_click == 0 and len(fired) == 1,
    )

    # ---- C3 移动按帧合并：事件后未即时生效、释放即定格最后位置 ----
    ov9.sel = QRectF(100, 100, 200, 150)
    left_before = ov9.sel.left()
    ov9.mousePressEvent(_press(center))
    ov9.mouseMoveEvent(_move(QPointF(260, 210)))
    c3_pending = ov9.sel.left() == left_before and ov9._pending_move_pos is not None
    ov9.mouseReleaseEvent(_release(QPointF(260, 210)))
    # move_offset=(-50,-50)：释放点 (260,210) → 左上角 (210,160)
    check(
        "C3 移动合并到帧/释放定格生效",
        c3_pending and ov9.sel.left() == 210 and ov9._pending_move_pos is None,
    )
    ov9._teardown_canvas()
    ov9.deleteLater()
    app.processEvents()

    # ---- A10 原图换行保留缩进（空行用例在主文件 UX-22 段） ----
    from snapocr.ui.result_window import WRAP_ORIGINAL, apply_wrap

    check("A10 原图换行保留缩进", apply_wrap(["  a"], WRAP_ORIGINAL) == ["  a"])

    # ---- A11 并发双连接命令均送达（原缺陷：_pending 单槽被覆盖丢命令） ----
    import snapocr.utils.singleinstance as _si

    old_key = _si.KEY
    _si.KEY = "snapocr.probe.round33.v1"
    srv = _si.SingleInstance()
    srv.listen()
    got = []
    srv.commandReceived.connect(lambda a: got.append(a))
    c1 = QLocalSocket()
    c1.connectToServer(_si.KEY)
    ok1 = c1.waitForConnected(600)
    c2 = QLocalSocket()
    c2.connectToServer(_si.KEY)
    ok2 = c2.waitForConnected(600)
    app.processEvents()
    c2.write(json.dumps(["--capture"]).encode("utf-8"))
    c2.flush()
    c2.waitForBytesWritten(300)
    app.processEvents()
    c1.write(json.dumps(["--settings"]).encode("utf-8"))
    c1.flush()
    c1.waitForBytesWritten(300)
    for _ in range(60):
        app.processEvents()
        if len(got) >= 2:
            break
        time.sleep(0.01)
    check(
        "A11 并发双连接命令均送达",
        ok1 and ok2 and sorted(map(str, got)) == ["['--capture']", "['--settings']"],
    )
    for _s in (c1, c2):
        with contextlib.suppress(Exception):
            _s.disconnectFromServer()
    with contextlib.suppress(Exception):
        srv._server.close()
    _si.KEY = old_key

    # ---- C1 写盘去抖：窗口期内不落盘、到期合并一次；save/reset 立即 ----
    if os.path.isfile(cfg_path):
        os.remove(cfg_path)
    cfgc = Config()
    cfgc._flush_now()  # 先建立基线文件（构造本身不写盘）

    def _disk_val():
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f).get("mosaic_block")

    cfgc.set("mosaic_block", 21)
    time.sleep(0.05)
    c1_pending = _disk_val() != 21  # 去抖窗口内尚未写盘
    cfgc._flush_now()
    c1_flushed = _disk_val() == 21
    cfgc.set("mosaic_block", 30)
    cfgc.reset()  # reset 立即落盘（不等去抖）
    c1_reset = _disk_val() == 10
    check("C1 set 去抖/flush 与 reset 立即落盘", c1_pending and c1_flushed and c1_reset)

    # ---- C2 马赛克底图首建防抖（不阻塞 _finalize，显式重建后可用） ----
    cw = CanvasWidget(_sample_image(300, 200), 1.0, mosaic_block=10)
    cw._px_timer.stop()  # 冻结防抖，验证"构造不再同步构建"
    c2_deferred = cw._pixelated is None
    cw._rebuild_pixelated()
    check("C2 马赛克首建防抖+显式重建可用", c2_deferred and cw._pixelated is not None)
    cw.deleteLater()

    # ==================== 用户视角轮（U1~U10 / R1~R4） ====================

    # ---- U1 OCR 输入=所见即所得合成图（马赛克遮蔽不再被绕过） ----
    from PyQt5.QtGui import QPainterPath

    pm_u1 = QPixmap(640, 480)
    pm_u1.fill(Qt.darkGreen)
    ov_u1 = OverlayWindow(scr, pm_u1, cfg=ctx.cfg)
    ov_u1.resize(640, 480)
    ov_u1.sel = QRectF(50, 50, 400, 300)
    ov_u1._finalize()
    ov_u1.canvas._px_timer.stop()
    ov_u1.canvas._rebuild_pixelated()
    mp = QPainterPath()
    mp.setFillRule(Qt.WindingFill)
    mp.addEllipse(QPointF(200, 150), 60, 30)
    ov_u1.canvas.strokes.append({"kind": "mosaic", "path": mp, "width": 20})
    ov_u1.canvas._rebuild_layer()
    cap_u1 = []
    ov_u1.ocrRequested.connect(lambda img, r, s: cap_u1.append(img))
    ov_u1._ocr()
    check(
        "U1 OCR 输入为合成图(马赛克生效)",
        bool(cap_u1) and cap_u1[0] == ov_u1.composite() and cap_u1[0] != ov_u1.crop_image(),
    )
    ov_u1._teardown_canvas()
    ov_u1.deleteLater()

    # ---- U2 文字输入框钳回画布内（贴右缘不再盲打） ----
    base_u2 = QImage(300, 200, QImage.Format_RGB888)
    base_u2.fill(Qt.white)
    cv_u2 = CanvasWidget(base_u2, 1.0, mosaic_block=10)
    cv_u2._px_timer.stop()
    cv_u2._open_text_edit(QPointF(290, 20))
    e_u2 = cv_u2._text_edit
    u2_ok = e_u2.x() >= 0 and e_u2.x() + e_u2.width() <= cv_u2.width() + 4
    u2_ok = u2_ok and e_u2.y() >= 0 and e_u2.y() + e_u2.height() <= cv_u2.height() + 4
    cv_u2._cancel_text_edit()
    cv_u2.deleteLater()
    check("U2 文字输入框贴边钳回画布内", u2_ok)

    # ---- U3 选区移动后在途任务放行新请求（stale + detach） ----
    from PyQt5.QtCore import QThread, pyqtSignal

    import snapocr.app as appmod
    from snapocr.app import CaptureController, ToastLabel
    from snapocr.ocr.worker import OcrWorker as _RealWorker

    class _FakeWorker(QThread):
        ok = pyqtSignal(list, float)
        fail = pyqtSignal(str)
        loaded = pyqtSignal(float)
        found = pyqtSignal(int)
        partial = pyqtSignal(str, int, int)

        def __init__(self, cfg, qimage, parent=None):
            super().__init__(parent)

        def run(self):
            pass

    class _StubApp3(_StubApp):
        pass

    _StubApp3.cfg = ctx.cfg
    stub3 = _StubApp3()
    stub3.toast = ToastLabel()
    ctrl3 = CaptureController(stub3)
    img3 = QImage(32, 32, QImage.Format_RGB888)
    old_w = _RealWorker(ctx.cfg, img3)  # 未启动的真实 worker 充当被弃置旧任务
    ctrl3.worker = old_w
    ctrl3._stale_ocr = True
    appmod.OcrWorker = _FakeWorker
    try:
        ctrl3.run_ocr(img3)
        u3_new = ctrl3.worker is not old_w and isinstance(ctrl3.worker, _FakeWorker)
        ctrl3._ocr_ok([], 0.1)
        u3_clear = ctrl3.worker is None and ctrl3._stale_ocr is False
    finally:
        appmod.OcrWorker = _RealWorker
    check("U3 在途任务弃收后放行新请求", u3_new and u3_clear)
    with contextlib.suppress(Exception):
        ctrl3.result.close()
    app.processEvents()

    # ---- U4 TXT 另存 utf-8-sig（LTSC 2019 记事本兼容） ----
    check(
        "U4 TXT 写入 utf-8-sig", 'encoding="utf-8-sig"' in _src("src/snapocr/ui/result_window.py")
    )

    # ---- U6 编辑态手柄缩放：置顶放大镜标签跟随/隐藏 ----
    pm_u6 = QPixmap(640, 480)
    pm_u6.fill(Qt.darkBlue)
    ov_u6 = OverlayWindow(scr, pm_u6, cfg=ctx.cfg)
    ov_u6.resize(640, 480)
    ov_u6.sel = QRectF(100, 100, 200, 150)
    ov_u6._finalize()
    ov_u6._mouse_pos = QPointF(280, 160)
    ov_u6.drag_mode = "resize"
    ov_u6._update_resize_magnifier()
    lb = ov_u6._mag_label
    u6_vis = (
        lb is not None
        and lb.isVisibleTo(ov_u6)
        and lb.geometry().right() <= ov_u6.width()
        and lb.geometry().bottom() <= ov_u6.height()
    )
    ov_u6._hide_resize_magnifier()
    u6_hidden = lb is not None and not lb.isVisibleTo(ov_u6)
    ov_u6._teardown_canvas()
    ov_u6.deleteLater()
    check("U6 缩放放大镜跟随且可隐藏", u6_vis and u6_hidden)

    # ---- U7 英文界面语言默认项文案 ----
    _i18n.init_lang("en")
    u7_label = _i18n.tr("lang_default")
    _i18n.init_lang("zh")
    check("U7 EN 默认语言项不再误导", u7_label == "Follow system")

    # ---- U8 结果窗尺寸记忆回填 ----
    cfg8 = Config()
    cfg8.set("result_win_w", 700)
    cfg8.set("result_win_h", 520)
    rw8 = ResultWindow(cfg=cfg8)
    rw8.show_near(QRectF(0, 0, 0, 0), scr)
    u8_size = rw8.width() == 700 and rw8.height() == 520
    rw8.resize(760, 540)
    rw8.close()
    u8_saved = cfg8.get("result_win_w") == 760 and cfg8.get("result_win_h") == 540
    check("U8 结果窗尺寸记忆回填", u8_size and u8_saved)
    rw8.deleteLater()

    # ---- U9 线程数"0=自动"三处口径一致（标签/注释/行为封顶 ≤4） ----
    _i18n.init_lang("zh")
    u9 = (
        "≤4" in _i18n.tr("threads")
        and "min(4" in _src("src/snapocr/config.py")
        and "min(threads, _cpu)" in _src("src/snapocr/ocr/engine.py")
    )
    check("U9 自动线程口径一致(≤4)", u9)

    # ---- U10 截屏中打开设置置顶（静态） ----
    check(
        "U10 截屏会话中设置窗置顶",
        "WindowStaysOnTopHint" in _src("src/snapocr/app.py"),
    )

    # ---- R4 tile 缓存已删（永不命中的死代码） ----
    check("R4 放大镜 tile 缓存已移除", "_mag_cache" not in _src("src/snapocr/ui/overlay.py"))

    # ---- R1 拖动框选脏区重绘：repaint 前后屏幕像素一致（无残留） ----
    pm_r = scr.grabWindow(0)
    ov_r1 = OverlayWindow(scr, pm_r, cfg=ctx.cfg)
    ov_r1.show()
    app.processEvents()
    ov_r1.start()
    QTest.qWait(30)
    ov_r1.mousePressEvent(_press(QPointF(200.0, 150.0)))
    for _i in range(8):
        ov_r1.mouseMoveEvent(_move(QPointF(200.0 + _i * 25, 150.0 + _i * 12)))
        QTest.qWait(8)
    app.processEvents()
    QTest.qWait(16)
    _a = scr.grabWindow(int(ov_r1.winId())).toImage()
    ov_r1.repaint()
    _b = scr.grabWindow(int(ov_r1.winId())).toImage()
    diff_r1 = sum(
        1
        for _y in range(min(_a.height(), _b.height()))
        for _x in range(min(_a.width(), _b.width()))
        if _a.pixelColor(_x, _y) != _b.pixelColor(_x, _y)
    )
    check("R1 拖动脏区重绘无残留", _a.size() == _b.size() and diff_r1 == 0)
    ov_r1.mouseReleaseEvent(_release(QPointF(400, 250)))
    ov_r1.cancelled.emit()
    ov_r1.hide()
    ov_r1.deleteLater()
    app.processEvents()
    QTest.qWait(120)

    # ---- R3 高亮变化脏区：确定性 stub 后 repaint 前后一致 ----
    ov_r3 = OverlayWindow(scr, pm_r, cfg=ctx.cfg)
    ov_r3._mouse_pos = QPointF(300, 300)
    _r3_rects = [QRectF(100, 100, 120, 80), QRectF(320, 240, 150, 100), QRectF(320, 240, 150, 100)]
    ov_r3._detect_window = lambda pos: _r3_rects.pop(0) if _r3_rects else QRectF(320, 240, 150, 100)
    ov_r3.show()
    app.processEvents()
    ov_r3.start()
    QTest.qWait(30)
    ov_r3.mouseMoveEvent(_move(QPointF(302, 301)))  # 高亮变化帧（extra 脏区路径）
    QTest.qWait(16)
    ov_r3.mouseMoveEvent(_move(QPointF(304, 302)))  # 平滑帧（仅放大镜脏区）
    QTest.qWait(16)
    app.processEvents()
    _a3 = scr.grabWindow(int(ov_r3.winId())).toImage()
    ov_r3.repaint()
    _b3 = scr.grabWindow(int(ov_r3.winId())).toImage()
    diff_r3 = sum(
        1
        for _y in range(min(_a3.height(), _b3.height()))
        for _x in range(min(_a3.width(), _b3.width()))
        if _a3.pixelColor(_x, _y) != _b3.pixelColor(_x, _y)
    )
    check("R3 高亮变化脏区重绘无残留", _a3.size() == _b3.size() and diff_r3 == 0)
    ov_r3.cancelled.emit()
    ov_r3.hide()
    ov_r3.deleteLater()
    app.processEvents()
    QTest.qWait(120)

    # ==================== 安装自启一致 / 画布状态一致（2026-10-26 反馈） ====================

    # ---- V1 初态一致：色片=记住色，画布同色；粗细/字号档位与画布初值一致 ----
    ctx.cfg.set("pen_color", "#ffd60a")  # 模拟"上次使用过黄色"
    pm_v = QPixmap(640, 480)
    pm_v.fill(Qt.darkCyan)
    ov_v = OverlayWindow(scr, pm_v, cfg=ctx.cfg)
    ov_v.resize(640, 480)
    ov_v.sel = QRectF(50, 50, 300, 220)
    ov_v._finalize()
    v1 = (
        ov_v.toolbar.btn_color._hex == "#ffd60a"
        and ov_v.canvas.color == "#ffd60a"
        and ov_v.toolbar.width_combo.currentData() == 5
        and ov_v.canvas.line_width == 5
        and ov_v.toolbar.size_combo.currentData() == 18
        and ov_v.canvas.text_size == 18
    )
    check("V1 初态一致(记住色/中档/18px)", v1)

    # ---- V2 重新框选后一致：颜色/粗细/字号/字体沿用工具条当前值 ----
    ov_v.toolbar.width_combo.setCurrentIndex(3)  # 加粗 16
    ov_v.toolbar.size_combo.setCurrentIndex(3)  # 32px
    from PyQt5.QtGui import QFont

    ov_v.toolbar.font_combo.setCurrentFont(QFont("Arial"))
    ov_v._on_color("#34c759")  # 与色板弹窗同一路径：改色片+画布+cfg
    app.processEvents()
    ov_v._teardown_canvas()
    ov_v.finalized = False
    ov_v.sel = QRectF(120, 90, 260, 200)  # 换区域重新框选
    ov_v._finalize()
    v2 = (
        ov_v.canvas.color == "#34c759"
        and ov_v.toolbar.btn_color._hex == "#34c759"
        and ov_v.canvas.line_width == 16
        and ov_v.canvas.text_size == 32
        and ov_v.canvas.text_font == "Arial"
    )
    check("V2 重新框选后颜色/粗细/字号/字体一致", v2)
    ov_v._teardown_canvas()
    ov_v.deleteLater()
    ctx.cfg.set("pen_color", "#ff3b30")
    app.processEvents()

    # ---- V3 自启配置对齐系统实际状态（注册表/桌面项为事实源；探针打桩不触真机） ----
    import snapocr.platform.autostart as _asmod

    cfg_v = Config()
    cfg_v.set("autostart", True)
    _orig_enabled = _asmod.autostart_enabled
    _asmod.autostart_enabled = lambda: False  # 模拟"安装器未勾选 → Run 键不存在"
    _asmod.sync_autostart_cfg(cfg_v)
    v3a = cfg_v.get("autostart") is False
    cfg_v.set("autostart", False)
    _asmod.autostart_enabled = lambda: True  # 模拟"Run 键在而配置为关"
    _asmod.sync_autostart_cfg(cfg_v)
    v3b = cfg_v.get("autostart") is True
    _asmod.autostart_enabled = _orig_enabled
    check("V3 自启配置按系统实际状态对齐", v3a and v3b)

    # ---- V4 安装脚本：自启默认勾选、未勾选清旧值、BOM 保留 ----
    with open(os.path.join(ROOT, "deploy", "windows", "snapocr.iss"), "rb") as f:
        _iss_raw = f.read()
    _iss = _iss_raw.decode("utf-8-sig")
    v4 = (
        _iss_raw[:3] == b"\xef\xbb\xbf"
        and 'Name: "autostart"' in _iss
        and 'Name: "autostart"; Description: "开机自动启动（后台托盘常驻）"; Flags: unchecked'
        not in _iss
        and "WizardIsTaskSelected('autostart')" in _iss
        and "RegDeleteValue" in _iss
        and 'Name: "desktopicon"' in _iss
        and "desktopicon" in _iss.split('Name: "autostart"')[0]  # 桌面图标仍默认不勾
    )
    check("V4 安装器自启默认勾选+未勾选清残留+BOM", v4)

    # ---- W1 RDP 忽略几何重建 / 非 RDP 静默期后重建一次（RDP 黑帧回归，2026-10-26） ----
    from PyQt5.QtCore import QObject as _QObject
    from PyQt5.QtCore import QTimer as _QTimer

    import snapocr.app as _appmod2
    from snapocr.app import SnapApp

    sa = SnapApp.__new__(SnapApp)
    _QObject.__init__(sa)
    sa._rebuild_timer = _QTimer()
    sa._rebuild_timer.setSingleShot(True)
    sa._rebuild_timer.setInterval(20)  # 探针缩短静默期
    sa._rebuild_timer.timeout.connect(sa._rebuild_overlays)
    closed = []
    started = []

    class _Ctl:
        def __init__(self):
            self.overlays = [object()]

        def _close_overlays(self):
            closed.append(1)
            self.overlays = []

    sa.controller = _Ctl()
    sa.start_capture = lambda: started.append(1)
    _orig_rdp = _appmod2.is_remote_session
    _appmod2.is_remote_session = lambda: True
    sa._on_screens_changed()
    w1_rdp = not sa._rebuild_timer.isActive()  # RDP：不启动重建
    _appmod2.is_remote_session = lambda: False
    sa._on_screens_changed()
    w1_armed = sa._rebuild_timer.isActive()  # 非 RDP：进入静默期
    QTest.qWait(10)
    w1_quiet = not closed  # 静默期内未重建
    QTest.qWait(60)
    QTest.qWait(200)  # 等 150ms 的重启取景
    w1_rebuilt = len(closed) == 1 and len(started) == 1
    _appmod2.is_remote_session = _orig_rdp
    check("W1 RDP忽略几何重建/非RDP静默期重建一次", w1_rdp and w1_armed and w1_quiet and w1_rebuilt)

    # ---- X1/X2/X3 弹出层靠边自适应（色板/下拉，2026-10-26 反馈） ----
    from PyQt5.QtWidgets import QToolButton

    from snapocr.ui.editor import (
        ColorPickerPopup,
        EdgeAwareComboBox,
        EdgeAwareFontComboBox,
        EditorToolbar,
    )
    from snapocr.ui.settings_dialog import SettingsDialog

    ag = scr.availableGeometry()
    an = QToolButton()
    an.setFixedSize(34, 34)
    an.move(ag.right() - 8, ag.top() + 150)  # 锚点贴屏幕右缘
    an.show()
    app.processEvents()
    pop = ColorPickerPopup("#ff0000")
    pop.popup_below(an)
    app.processEvents()
    x1_h = pop.x() >= ag.left() and pop.x() + pop.width() <= ag.right() + 1
    pop.close()
    pop.deleteLater()
    an.move(ag.left() + 300, ag.bottom() - 8)  # 锚点贴屏幕下缘
    app.processEvents()
    pop2 = ColorPickerPopup("#ff0000")
    pop2.popup_below(an)
    app.processEvents()
    x1_v = pop2.y() >= ag.top() and pop2.y() + pop2.height() <= ag.bottom() + 1
    pop2.close()
    pop2.deleteLater()
    an.close()
    an.deleteLater()
    app.processEvents()
    check("X1 色板弹窗靠边自适应(贴右缘/贴下缘)", x1_h and x1_v)

    cb = EdgeAwareComboBox()
    for s in ("短", "很长很长的示例条目内容一", "更长的一个示例条目文本内容等"):
        cb.addItem(s)
    cb.resize(70, 26)
    cb.move(ag.right() - 30, ag.top() + 150)  # 框贴右缘、列表远宽于框
    cb.show()
    app.processEvents()
    cb.showPopup()
    app.processEvents()
    _pu = cb.view().window()
    x2 = _pu.x() >= ag.left() and _pu.x() + _pu.width() <= ag.right() + 1
    cb.hidePopup()
    app.processEvents()
    cb.close()
    cb.deleteLater()
    app.processEvents()
    check("X2 下拉列表钳回屏幕(宽列表贴右缘)", x2)

    tbx = EditorToolbar()
    sdx = SettingsDialog(ctx.cfg)
    x3 = (
        isinstance(tbx.width_combo, EdgeAwareComboBox)
        and isinstance(tbx.size_combo, EdgeAwareComboBox)
        and isinstance(tbx.font_combo, EdgeAwareFontComboBox)
        and isinstance(sdx.scale_combo, EdgeAwareComboBox)
        and isinstance(sdx.lang_combo, EdgeAwareComboBox)
    )
    tbx.deleteLater()
    sdx.deleteLater()
    check("X3 全部下拉换用靠边自适应类", x3)

    # ---- Y1~Y5 复制为文件（2026-10-26 新功能） ----
    from PyQt5.QtGui import QGuiApplication

    from snapocr.ui import clipboard as clipmod
    from snapocr.ui.preview_dialog import PreviewDialog

    # Y1 图片复制为 JPG 文件：落盘 + 剪贴板带文件 URL；不带图像数据（用户口径）
    img_y = QImage(60, 40, QImage.Format_RGB888)
    img_y.fill(Qt.red)
    p1 = clipmod.copy_image_as_file(img_y, "y测试")
    cb_y = QGuiApplication.clipboard()
    md_y = cb_y.mimeData()
    y1 = (
        p1 is not None
        and p1.endswith("y测试.jpg")
        and os.path.isfile(p1)
        and md_y.hasUrls()
        and os.path.normpath(md_y.urls()[0].toLocalFile()) == os.path.normpath(p1)
        and not md_y.hasImage()
    )
    check("Y1 图片复制为JPG文件(仅文件形态)", y1)

    # Y2 文本复制为 TXT 文件：utf-8-sig 内容 + 文件 URL
    p2 = clipmod.copy_text_as_file("中文内容 Y2", "y文本")
    with open(p2, "rb") as f:
        head_y = f.read(3)
    with open(p2, encoding="utf-8-sig") as f:
        body_y = f.read()
    md_y2 = cb_y.mimeData()
    y2 = (
        p2 is not None
        and p2.endswith("y文本.txt")
        and head_y == b"\xef\xbb\xbf"
        and body_y == "中文内容 Y2"
        and md_y2.hasUrls()
        and os.path.normpath(md_y2.urls()[0].toLocalFile()) == os.path.normpath(p2)
        # hasText() 对 uri-list 有回落（Qt 既定行为），"仅文件"看格式表：不含 text/plain
        and "text/plain" not in md_y2.formats()
    )
    check("Y2 文本复制为TXT文件(utf-8-sig,仅文件形态)", y2)

    # Y3 同名去重 + 空名拒绝
    p3 = clipmod.copy_text_as_file("dup", "y文本")
    y3 = p3 is not None and p3 != p2 and clipmod.copy_text_as_file("x", "  ") is None
    check("Y3 同名去重/空名拒绝", y3)

    # Y4 三处按钮存在并接线；结果窗可用态同步（busy 置灰 → 有内容恢复）
    tby = EditorToolbar()
    rwy = ResultWindow(cfg=Config())
    pvy = PreviewDialog(img_y, ctx.cfg)
    y4 = (
        bool(tby.btn_copyfile.text().strip())
        and rwy.btn_copyfile is not None
        and pvy.btn_file is not None
    )
    rwy.begin_stream()
    y4b = rwy.btn_copyfile.isEnabled() is False
    rwy.set_results([("文本", 0.9, None)], 0.1)
    y4c = rwy.btn_copyfile.isEnabled()
    tby.deleteLater()
    rwy.close()
    rwy.deleteLater()
    pvy.deleteLater()
    check("Y4 三处按钮+可用态同步", y4 and y4b and y4c)

    # Y5 启动清理接线 + i18n 双语齐备；清掉探针刚写的文件（不留垃圾）
    y5 = (
        "cleanup_clip_files" in _src("src/snapocr/main.py")
        and _i18n._ZH.get("copy_as_file") is not None
        and _i18n._EN.get("copy_as_file") is not None
        and _i18n._EN.get("default_filename_jpg") == "screenshot_%s.jpg"
        and _i18n._ZH.get("default_filename_jpg") == "截图_%s.jpg"
    )
    clipmod.cleanup_clip_files()
    y5 = y5 and not os.path.exists(os.path.dirname(p1))
    check("Y5 启动清理+i18n双语齐备", y5)

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
