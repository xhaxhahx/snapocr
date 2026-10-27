# -*- coding: utf-8 -*-
"""本轮修复项验证探针（对应《问题与优化总表》中标注「需修复」的条目）。

与 test_plan_probe.py（回归守住项）互补：本探针只验证本轮改动的新行为，
不涉及真实抓屏（用离屏/构造数据），尽量快且确定性。

用法: python scripts/test_fix_probe.py
"""

import contextlib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from snapocr.main import _setup_qt_plugin_path  # noqa: E402

_setup_qt_plugin_path()

OK = []
FAIL = []
SKIP = []


def check(name, cond):
    (OK if cond else FAIL).append(name)
    print(("[PASS] " if cond else "[FAIL] ") + name, flush=True)


def skip(name, reason):
    """环境不满足时跳过，而不是判失败（不计入 FAIL，不阻断门禁）。"""
    SKIP.append(name)
    print("[SKIP] " + name + " —— " + reason, flush=True)


def _instance_running(timeout=400) -> bool:
    """探测是否已有 SnapOCR 实例在跑。

    只建立连接、**不发送任何命令**：`SingleInstance.try_connect` 会真的把
    `--capture` 转发给在跑的实例，导致其弹出框选遮罩并抢焦点。
    """
    from PyQt5.QtNetwork import QLocalSocket

    from snapocr.utils.singleinstance import KEY

    sock = QLocalSocket()
    sock.connectToServer(KEY)
    running = bool(sock.waitForConnected(timeout))
    sock.abort()
    return running


def _read_text(path) -> str:
    """读取工程文件文本（静态复核用，统一走上下文管理器）。"""
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_head(path, n) -> bytes:
    """读取文件头 n 字节（BOM 检测用）。"""
    with open(path, "rb") as f:
        return f.read(n)


def main():
    from PyQt5.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt
    from PyQt5.QtGui import QImage, QPixmap
    from PyQt5.QtNetwork import QLocalSocket
    from PyQt5.QtWidgets import QApplication, QGroupBox, QToolButton

    app = QApplication([])
    scr = app.primaryScreen()
    # 隔离配置：本探针会反复写配置，绝不能污染用户真实的 %APPDATA%\SnapOCR\config.json
    import snapocr.config as cfgmod

    tmp_cfg = os.path.join(ROOT, ".tmp", "probe_config.json")
    os.makedirs(os.path.dirname(tmp_cfg), exist_ok=True)
    cfgmod.config_file = lambda: tmp_cfg
    from snapocr.config import DEFAULTS, Config
    from snapocr.i18n import tr
    from snapocr.ocr import engine as E
    from snapocr.tests.selftest import _sample_image
    from snapocr.ui import icons
    from snapocr.ui.editor import (
        EXPAND_ANIM_MS,
        TOOL_ERASER,
        TOOL_PEN,
        CanvasWidget,
        EditorToolbar,
    )
    from snapocr.ui.overlay import OverlayWindow
    from snapocr.ui.result_window import (
        WRAP_JOIN,
        WRAP_ORIGINAL,
        WRAP_SENTENCE,
        ResultWindow,
        apply_wrap,
    )
    from snapocr.ui.settings_dialog import SettingsDialog
    from snapocr.utils.singleinstance import SingleInstance

    cfg = Config()

    # ---- P21 线程数封顶 ----
    c2 = Config()
    c2._d["ocr_threads"] = 9999
    p = E._build_params(c2)
    n = p["EngineConfig.onnxruntime.intra_op_num_threads"]
    check("P21 线程数越界被封顶", 1 <= n <= (os.cpu_count() or 4))
    c2._d["ocr_threads"] = -5
    check(
        "P21 负值回落自动",
        E._build_params(c2)["EngineConfig.onnxruntime.intra_op_num_threads"] >= 1,
    )

    # ---- P28 / 引擎-2 大图钳制 ----
    import numpy as np

    big = np.zeros((2160, 7680, 3), dtype=np.uint8)
    small = E._clamp_max_dim(big, 4000)
    check("P28 超长边被钳制到 <=4000", max(small.shape[:2]) <= 4000)
    check("引擎-2 未超限时原样返回", E._clamp_max_dim(big, 9000) is big)

    # ---- 引擎-3 阅读顺序重排 ----
    def box(x, y):
        return [[x, y], [x + 10, y], [x + 10, y + 10], [x, y + 10]]

    items = [("B", 1.0, box(300, 100)), ("A", 1.0, box(50, 100)), ("C", 1.0, box(50, 300))]
    ordered = [t for t, _, _ in E._sort_reading_order(items)]
    check("引擎-3 同行按 x、跨行按 y 排序", ordered == ["A", "B", "C"])
    check("引擎-3 无坐标结果不崩", len(E._sort_reading_order([("x", 1.0, None)])) == 1)

    # ---- 引擎-1 RGB→BGR 连续且通道正确 ----
    img = QImage(4, 2, QImage.Format_RGB888)
    img.fill(0)
    img.setPixelColor(0, 0, __import__("PyQt5.QtGui", fromlist=["QColor"]).QColor(10, 20, 30))
    bgr = E.qimage_to_bgr(img)
    check("引擎-1 返回连续数组", bgr.flags["C_CONTIGUOUS"])
    check("引擎-1 通道序为 BGR", tuple(bgr[0, 0]) == (30, 20, 10))

    # ---- 换行方式三态（原 N4「自动合并换行」已移入结果窗，改为循环切换）----
    _L = ["这是一个很长的句子被", "截图切成了两行。", "下一段开始"]
    check(
        "换行 整段：全部连成一段",
        apply_wrap(_L, WRAP_JOIN) == ["这是一个很长的句子被截图切成了两行。下一段开始"],
    )
    check(
        "换行 按句：句末标点后断行",
        apply_wrap(_L, WRAP_SENTENCE) == ["这是一个很长的句子被截图切成了两行。", "下一段开始"],
    )
    check("换行 原图：每个识别框一行", apply_wrap(_L, WRAP_ORIGINAL) == _L)
    check(
        "换行 原图模式原样保留(含空行缩进,§33.1 A10)",
        apply_wrap(["a", "", "  "], WRAP_ORIGINAL) == ["a", "", "  "],
    )
    check("换行 格式化模式仍清洗空行", apply_wrap(["a", "", "  "], WRAP_JOIN) == ["a"])
    check(
        "换行 小数不被按句拆开",
        apply_wrap(["版本 v1.5 已发布"], WRAP_SENTENCE) == ["版本 v1.5 已发布"],
    )
    check(
        "换行 英文句号后接空白才断",
        apply_wrap(["Hello world.", "Next one"], WRAP_SENTENCE) == ["Hello world.", "Next one"],
    )
    check(
        "换行 中英边界补空格",
        apply_wrap(["中文结尾", "English start"], WRAP_JOIN) == ["中文结尾 English start"],
    )
    check(
        "换行 中文之间不补空格",
        apply_wrap(["前半句", "后半句"], WRAP_JOIN) == ["前半句后半句"],
    )

    # ---- P20 幽灵放大镜 ----
    ov0 = OverlayWindow(scr, QPixmap.fromImage(_sample_image(640, 360)), cfg=cfg)
    check("P20 初始不画放大镜(_mouse_pos=None)", ov0._mouse_pos is None)
    ov0.start()
    app.processEvents()
    check("P20 start() 后按真实指针初始化", ov0._mouse_pos is not None)
    ov0.cancelled.emit()
    app.processEvents()

    # ---- P5 标注预览落点（WYSIWYG，dpr=2） ----
    base = QImage(400, 400, QImage.Format_RGB888)
    base.fill(0)
    cw = CanvasWidget(base, 2.0, mosaic_block=10)
    cw.set_tool(TOOL_PEN)
    # 笔画按设备像素存储：(160,200)-(240,200)；修复后应落在逻辑 (80,100)-(120,100)，即画布中心行
    cw._current = {
        "kind": "pen",
        "pts": [QPointF(160, 200), QPointF(240, 200)],
        "color": "#ff0000",
        "width": 20,
    }
    cw.mouseReleaseEvent(QEvent(QEvent.MouseButtonRelease))
    shot = QImage(cw.size(), QImage.Format_RGB888)
    shot.fill(0)
    cw.render(shot)
    xs, ys = [], []
    for y in range(shot.height()):
        for x in range(shot.width()):
            if shot.pixelColor(x, y).red() > 100:
                xs.append(x)
                ys.append(y)
    cx = (min(xs) + max(xs)) / 2 if xs else -1
    cy = (min(ys) + max(ys)) / 2 if ys else -1
    check("P5 预览墨迹落在逻辑坐标中心", bool(xs) and abs(cx - 100) <= 6 and abs(cy - 100) <= 8)
    cw.deleteLater()

    # ---- P25 清空标注 + 栈空置灰 ----
    cw2 = CanvasWidget(QImage(200, 200, QImage.Format_RGB888), 1.0)
    tb = EditorToolbar()
    tb.set_undo_redo_enabled(False, False)
    check("P25 栈空时撤销/重做置灰", not tb.btn_undo.isEnabled() and not tb.btn_redo.isEnabled())
    cw2.strokes.append(
        {"kind": "pen", "pts": [QPointF(10, 10), QPointF(20, 20)], "color": "#000", "width": 4}
    )
    states = []
    cw2.stackChanged.connect(lambda a, b: states.append((a, b)))
    cw2.clear_all()
    check("P25 clear_all 清空笔画", cw2.strokes == [])
    check("P25 clear_all 发出 (False,False)", states and states[-1] == (False, False))
    cw2.clear_all()
    check("P25 空栈重复清空不报错", True)
    cw2.deleteLater()
    tb.deleteLater()

    # ---- UX-8 橡皮擦像素级擦除（像真实橡皮，不是整条删除）----
    cw3 = CanvasWidget(QImage(300, 300, QImage.Format_RGB888), 1.0)
    cw3.strokes.append(
        {"kind": "pen", "pts": [QPointF(50, 50), QPointF(150, 50)], "color": "#000", "width": 6}
    )
    cw3.strokes.append(
        {
            "kind": "shape",
            "shape": "rect",
            "start": QPointF(10, 100),
            "end": QPointF(90, 180),
            "rect": QRectF(10, 100, 80, 80),
            "color": "#000",
            "width": 4,
        }
    )
    cw3._rebuild_layer()
    cw3.set_tool(TOOL_ERASER)
    # 点击笔画中部，strokes 不应被删除
    cw3.mousePressEvent(
        __import__("PyQt5.QtGui", fromlist=["QMouseEvent"]).QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(100, 50),
            QPointF(100, 50),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    check("UX-8 橡皮擦不删除 strokes", len(cw3.strokes) == 2)
    # layer 上被擦区域应变透明
    layer_px = cw3._layer.toImage().pixel(100, 50)
    check("UX-8 点击后 layer 像素变透明", (layer_px >> 24) & 0xFF == 0)
    # 拖动继续擦
    cw3.mouseMoveEvent(
        __import__("PyQt5.QtGui", fromlist=["QMouseEvent"]).QMouseEvent(
            QEvent.MouseMove,
            QPointF(120, 50),
            QPointF(120, 50),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    layer_px2 = cw3._layer.toImage().pixel(120, 50)
    check("UX-8 拖动后新位置也变透明", (layer_px2 >> 24) & 0xFF == 0)
    cw3.mouseReleaseEvent(
        __import__("PyQt5.QtGui", fromlist=["QMouseEvent"]).QMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(120, 50),
            QPointF(120, 50),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    check("UX-8 释放后 strokes 仍不变", len(cw3.strokes) == 2)
    # undo 重建 layer，擦除效果消失
    cw3.undo()
    layer_px3 = cw3._layer.toImage().pixel(100, 50)
    check("UX-8 undo 后 layer 恢复不透明", (layer_px3 >> 24) & 0xFF > 0)
    cw3.deleteLater()

    # ---- 工具条不应继承遮罩的「选区内移动」光标（按钮上必须回到箭头）----
    ovc = OverlayWindow(scr, QPixmap.fromImage(_sample_image(1280, 720)), cfg=cfg)
    ovc.sel = QRectF(100, 80, 500, 300)
    ovc._finalize()
    ovc._on_edit_toggle(True)
    ovc.setCursor(Qt.SizeAllCursor)  # 模拟指针停在选区内
    tbtns = ovc.toolbar.findChildren(QToolButton)
    check("工具条 自身光标为箭头", ovc.toolbar.cursor().shape() == Qt.ArrowCursor)
    check(
        "工具条 按钮不继承移动光标",
        bool(tbtns) and all(b.cursor().shape() == Qt.ArrowCursor for b in tbtns),
    )
    ovc.hide()
    ovc.deleteLater()
    app.processEvents()

    # ---- UX-16 ~ UX-21：渲染/交互探针（已拆分到 scripts/probes/ux_suite.py；
    #      第二轮审计 P2-05：原 main() 977 行、两套重复底图构造）----
    from probes.ux_suite import Ctx
    from probes.ux_suite import run as run_ux_suite

    run_ux_suite(Ctx(app=app, scr=scr, cfg=cfg, check=check, skip=skip))

    # ---- UX-22 第二轮修复回归（橡皮双圈光标 / IPC 断开清理 / 文件名 i18n）----
    # 1) 橡皮光标：外圈按 max(8,档位) 兜底，内圈按真实擦除直径（强调色虚线）
    import snapocr.i18n as _i18n2
    import snapocr.utils.singleinstance as _si2
    from snapocr.ui import theme as _theme2

    cw_e = CanvasWidget(_sample_image(200, 200), 1.0, mosaic_block=10)
    cw_e.line_width = 2  # 细档：擦除直径 2px，外圈兜底 8px
    cw_e._update_eraser_cursor()
    pm_e = cw_e.cursor().pixmap()
    img_e = pm_e.toImage()
    acc = _theme2.current().accent

    def _near(c, ref, tol=40):
        return (
            abs(c.red() - ref.red()) <= tol
            and abs(c.green() - ref.green()) <= tol
            and abs(c.blue() - ref.blue()) <= tol
        )

    has_inner = any(
        _near(img_e.pixelColor(x, y), acc)
        for x in range(img_e.width())
        for y in range(img_e.height())
    )
    check("UX-22 橡皮细档光标含真实擦除圈", has_inner)
    check("UX-22 橡皮细档外圈兜底 8px", pm_e.width() == 10)
    cw_e.line_width = 16  # 加粗档：内圈与外圈重合，不再画内圈
    cw_e._update_eraser_cursor()
    check("UX-22 橡皮加粗档光标 18px", cw_e.cursor().pixmap().width() == 18)
    cw_e.deleteLater()

    # 2) IPC：客户端发半截报文后断开，服务端不得残留挂起 socket
    _old_key2 = _si2.KEY
    _si2.KEY = "snapocr.probe.disconnect.v1"
    srv2 = _si2.SingleInstance()
    srv2.listen()
    cl2 = QLocalSocket()
    cl2.connectToServer(_si2.KEY)
    cl2.waitForConnected(600)
    cl2.write(b'{"bad json')
    cl2.flush()
    cl2.waitForBytesWritten(300)
    app.processEvents()
    cl2.disconnectFromServer()
    t2 = QElapsedTimer()
    t2.start()
    while t2.elapsed() < 600 and srv2._pending:
        app.processEvents()
    check("UX-22 IPC 断开后清理挂起状态", not srv2._pending)
    with contextlib.suppress(Exception):
        srv2._server.close()
    _si2.KEY = _old_key2

    # 3) 默认保存文件名走 i18n（中文环境与旧字面量完全一致）
    _i18n2.init_lang("en")
    check(
        "UX-22 默认文件名英文",
        (_i18n2.tr("default_filename") % "20260101_120000") == "screenshot_20260101_120000.png",
    )
    _i18n2.init_lang("zh")
    check(
        "UX-22 默认文件名中文不变",
        (_i18n2.tr("default_filename") % "20260101_120000") == "截图_20260101_120000.png",
    )
    app.processEvents()

    # ---- 编辑区展开/折叠：行A按钮间距恒定 + 高度动画 ----
    tb2 = EditorToolbar()
    tb2.setWindowFlags(Qt.Window)  # 脱离父级，独立 adjustSize
    tb2.show()

    def _rowA_boxes():
        """行A各按钮的 (x, width) 列表（折叠态与展开态应完全一致）。"""
        out = []
        for b in (tb2.btn_edit, tb2.btn_ocr, tb2.btn_copy, tb2.btn_save, tb2.btn_cancel):
            g = b.geometry()
            out.append((g.x(), g.width()))
        return out

    boxes_folded = _rowA_boxes()
    check("间距 初始为折叠态", tb2.rowB_widget.maximumHeight() == 0)
    h_collapsed = tb2.height()
    tb2.set_expanded(True, animate=False)
    check("间距 展开后行A按钮位置与宽度不变", boxes_folded == _rowA_boxes())
    h_full = tb2.height()
    check("间距 展开态高度大于折叠态", h_full > h_collapsed)
    # 动画：从当前高度向目标高度过渡
    tb2.set_expanded(False, animate=False)
    tb2.set_expanded(True)  # animate=True
    check(
        "动画 展开时构造 QPropertyAnimation（时长/属性/目标正确）",
        tb2._rowb_anim is not None
        and tb2._rowb_anim.duration() == EXPAND_ANIM_MS
        and tb2._rowb_anim.targetObject() is tb2.rowB_widget
        and tb2._rowb_anim.endValue() == tb2.rowB_widget.sizeHint().height()
        and tb2._rowb_anim.startValue() == 0,
    )
    tb2.set_expanded(True, animate=False)  # 收尾：直接到目标态，避免遗留运行中动画
    check(
        "动画 收尾为展开态",
        tb2.rowB_widget.maximumHeight() == tb2.rowB_widget.sizeHint().height(),
    )
    tb2.set_expanded(False, animate=False)
    check("间距 折叠后恢复高度", tb2.height() == h_collapsed)
    tb2.deleteLater()
    app.processEvents()

    # ---- R2 单实例三态 ----
    check(
        "R2 三态常量存在",
        (SingleInstance.FORWARDED, SingleInstance.NO_INSTANCE, SingleInstance.UNCERTAIN)
        == ("forwarded", "no-instance", "uncertain"),
    )
    # 该断言依赖全局前置条件「当前没有任何实例在跑」（例如开发时开着托盘程序即不成立）。
    # 先做只读探测：不满足则跳过，避免误报失败、也避免把 --capture 注入真实实例。
    if _instance_running():
        skip(
            "R2 无实例时返回 NO_INSTANCE",
            "检测到已有 SnapOCR 实例在运行，该断言的前提不成立",
        )
    else:
        check(
            "R2 无实例时返回 NO_INSTANCE",
            SingleInstance().try_connect(["--capture"]) == SingleInstance.NO_INSTANCE,
        )

    # ---- P26/P27/P9/P10/UX-9/UX-11/UX-13/N4 设置窗 ----
    # 隔离副作用：_apply 会调用 set_autostart 写注册表/桌面项，测试中改为空操作
    import snapocr.platform.autostart as _autostart

    _autostart.set_autostart = lambda enabled: True
    sd = SettingsDialog(cfg)
    groups = [g.title() for g in sd.findChildren(QGroupBox)]
    check("P26 开机自启独立成组", tr("startup_group") in groups)
    check(
        "P26 快捷键组不再含自启",
        sd.autostart_cb.parent() is not None
        and sd.autostart_cb.parent() is not sd.hotkey_edit.parent(),
    )
    check("UX-9 马赛克块可调", sd.mosaic_spin.minimum() == 6 and sd.mosaic_spin.maximum() == 40)
    check("UX-13 释放模型开关存在", sd.release_cb is not None)
    check("换行 设置页已无「自动合并换行」项", not hasattr(sd, "merge_cb"))
    check("UX-11 恢复默认按钮存在", sd.btn_reset is not None)
    emitted = []
    sd.settingsApplied.connect(lambda b: emitted.append(b))
    sd.hotkey_edit.clear()  # 清空热键
    sd._apply()
    check("P9 清空热键回落默认值", cfg.get("hotkey") == DEFAULTS["hotkey"])
    check("P27 信号带 bool 参数", emitted and emitted[-1] is False)
    sd2 = SettingsDialog(cfg)
    emitted2 = []
    sd2.settingsApplied.connect(lambda b: emitted2.append(b))
    sd2.hotkey_edit.setText("Ctrl+Alt+Shift+Z")
    sd2._apply()
    check("P27 改快捷键时置 True", emitted2 and emitted2[-1] is True)
    cfg.set("lang", "en")
    from snapocr import i18n

    i18n.init_lang("en")
    check("P10 语言切换可即时生效", i18n.tr("copy") == "Copy image")
    i18n.init_lang("zh")
    cfg.set("mosaic_block", 33)
    sd3 = SettingsDialog(cfg)
    sd3._restore_defaults()
    check("UX-11 恢复默认写盘生效", cfg.get("mosaic_block") == DEFAULTS["mosaic_block"])
    check("UX-11 控件同步回默认", sd3.mosaic_spin.value() == DEFAULTS["mosaic_block"])
    sd.deleteLater()
    sd2.deleteLater()
    sd3.deleteLater()

    # ---- 死配置清理 / 新增配置 ----
    check(
        "死配置已移除",
        all(k not in DEFAULTS for k in ("highlight_color", "text_color", "close_after_copy")),
    )
    check(
        "新增配置就位",
        all(k in DEFAULTS for k in ("ocr_max_dim", "ocr_release_after")),
    )
    # P3d：pin 键曾因"贴图"功能移除而删除；2026-10-27 预览窗"钉住"功能合法复用，
    # 断言改为"pin 系列键成对存在且被引用"（不再是残留）
    check(
        "P3d i18n pin 键已由钉住功能复用(非残留)",
        "pin" in i18n._ZH
        and "unpin" in i18n._ZH
        and "pin" in i18n._EN
        and "unpin" in i18n._EN
        and "pin_tip" in i18n._ZH,
    )

    # ---- P1c bench 参数越界保护 ----
    import snapocr.tests.bench as bench

    saved_argv = sys.argv[:]
    saved_get = E.get_engine, E.qimage_to_bgr, E.recognize_sync
    calls = {"n": 0}

    def fake_rec(cfg_, bgr):
        calls["n"] += 1
        return [("t", 1.0, None)], 0.01

    E.get_engine = lambda cfg_: object()
    E.qimage_to_bgr = lambda qi: None
    E.recognize_sync = fake_rec
    try:
        for argv in (["run.py", "--bench"], ["run.py", "--bench", "abc"]):
            calls["n"] = 0
            sys.argv = argv
            bench.run_bench(app, cfg)
            check("P1c %s 不越界" % " ".join(argv[1:]), calls["n"] == 3)
    finally:
        sys.argv = saved_argv
        E.get_engine, E.qimage_to_bgr, E.recognize_sync = saved_get

    # ---- P1a/P1b 静态复核（导入路径与 stdout 判空） ----
    bsrc = _read_text(os.path.join(ROOT, "src", "snapocr", "tests", "bench.py"))
    ssrc = _read_text(os.path.join(ROOT, "src", "snapocr", "tests", "selftest.py"))
    check(
        "P1a bench 相对导入正确",
        "from .selftest import" in bsrc and "from ..ocr import engine as E" in bsrc,
    )
    check(
        "P1b bench/selftest 判空 stdout",
        "if sys.stdout is not None" in bsrc and "if sys.stdout is not None" in ssrc,
    )
    check("P2 自检模型断言已放宽", "或内置" in ssrc)

    # ---- P4 OCR 线程回收 ----
    from PyQt5.QtCore import QObject as _QO
    from PyQt5.QtCore import QThread

    from snapocr.app import CaptureController

    ctl = CaptureController.__new__(CaptureController)
    _QO.__init__(ctl)
    ctl.app = type("A", (), {"cfg": cfg})()
    from PyQt5.QtWidgets import QLabel as _QL

    ctl.app.toast = _QL()
    ctl.app.toast.hide()
    ctl.app.toast.pop = lambda *a, **k: None
    ctl.overlays = []
    ctl.result = None
    ctl.worker = None
    ctl._hiding = []
    for _ in range(2):
        ctl.run_ocr(_sample_image(320, 160), None, scr)
        for _ in range(600):
            app.processEvents()
            if ctl.worker is None:
                break
            import time as _t

            _t.sleep(0.02)
    for _ in range(40):
        app.processEvents()
    live = [o for o in ctl.children() if isinstance(o, QThread)]
    check("P4 OCR 后 QThread 无残留", len(live) == 0)
    if ctl.result is not None:
        ctl.result.close()
    app.processEvents()

    # ---- 流式输出：det 完成给框数、逐框按阅读顺序回调、终态与同步路径一致 ----
    bgr = E.qimage_to_bgr(_sample_image(760, 300))
    E.get_engine(cfg)
    sync_res, _ = E.recognize_sync(cfg, bgr)
    seen = {"found": [], "lines": []}
    strm_res, _ = E.recognize_stream(
        cfg,
        bgr,
        on_found=lambda n: seen["found"].append(n),
        on_line=lambda it, d, t: seen["lines"].append((it[0], d, t)),
    )
    check("流式 on_found 只回调一次", len(seen["found"]) == 1)
    check("流式 框数覆盖全部结果", seen["found"][0] >= len(strm_res))
    check(
        "流式 逐条进度递增",
        [d for _, d, _ in seen["lines"]] == list(range(1, len(seen["lines"]) + 1)),
    )
    check("流式 结果非空", len(strm_res) > 0)
    check(
        "流式 与同步结果内容一致（忽略空白差异）",
        [re.sub(r"\s+", "", r[0]) for r in sync_res]
        == [re.sub(r"\s+", "", r[0]) for r in strm_res],
    )

    rws = ResultWindow(cfg=cfg)
    rws.begin_stream()
    check("流式 初始提示为定位中", tr("ocr_locating") in rws.meta.text())
    rws.stream_found(2)
    check("流式 det 完成后提示框数", tr("ocr_found", 2) in rws.meta.text())
    rws.stream_line("第一行文字", 1, 2)
    check("流式 首行已追加", "第一行文字" in rws.text.toPlainText())
    rws.stream_line("第二行文字", 2, 2)
    check("流式 进度文案更新", tr("ocr_progress", 2, 2) in rws.meta.text())
    rws.set_results([("第一行文字", 1.0, None), ("第二行文字", 1.0, None)], 0.42)
    check("流式 终态由完整结果覆盖", "耗时" in rws.meta.text() or "s" in rws.meta.text())

    # 结果窗内循环切换换行方式：整段 → 按句 → 原图 → 整段
    rws.set_results(
        [("第一段被截断", 1.0, None), ("接着上一行。", 1.0, None), ("第二段", 1.0, None)], 0.42
    )
    check("换行 结果窗默认原图换行(2 换行)", rws.text.toPlainText().count("\n") == 2)
    check("换行 按钮名固定为格式化换行", rws.btn_wrap.text() == tr("wrap_button"))
    rws.cycle_wrap()
    check("换行 点一次→整段(0 换行)", rws.text.toPlainText().count("\n") == 0)
    rws.cycle_wrap()
    check("换行 再点→按句(1 换行)", rws.text.toPlainText().count("\n") == 1)
    rws.cycle_wrap()
    check("换行 再点回到原图(2 换行)", rws.text.toPlainText().count("\n") == 2)
    check("换行 按钮名点击后不变", rws.btn_wrap.text() == tr("wrap_button"))
    rws.deleteLater()
    app.processEvents()

    # ---- P6 无实例时 --exit 直接退出 ----
    # 前置条件与 R2 相同：有实例在跑时，--exit 会被**转发并真的关闭那个实例**
    # （开发时开着托盘程序跑门禁＝自己的程序被关掉），必须先探测再决定跑不跑。
    if _instance_running():
        skip(
            "P6 无实例 --exit 立即退出",
            "检测到已有 SnapOCR 实例在运行，--exit 会被转发并关闭它",
        )
    else:
        try:
            r = subprocess.run(
                [sys.executable, os.path.join(ROOT, "src", "run.py"), "--exit"],
                cwd=ROOT,
                capture_output=True,
                timeout=25,
            )
            check("P6 无实例 --exit 立即退出", r.returncode == 0)
        except subprocess.TimeoutExpired:
            check("P6 无实例 --exit 立即退出", False)

    # ---- P3e requirements 无 BOM ----
    raw = _read_head(os.path.join(ROOT, "requirements.txt"), 3)
    check("P3e requirements 无 BOM", raw != b"\xef\xbb\xbf")

    # ---- 瘦身-D / S-C2 spec 复核 ----
    spec_src = _read_text(os.path.join(ROOT, "deploy", "snapocr.spec"))
    ns = {}
    m = re.search(r"_KEEP_PLUGIN_DIRS = .*?\n\n\na\.datas", spec_src, re.S)
    if m:
        exec(m.group(0).replace("\n\na.datas", ""), ns)
        keep = ns["_keep_qt_data"]
        check(
            "瘦身-D 保留 platforms 插件",
            keep(("PyQt5\\Qt5\\plugins\\platforms\\qwindows.dll", "", "")),
        )
        check(
            "瘦身-D 保留 imageformats/qpng",
            keep(("PyQt5\\Qt5\\plugins\\imageformats\\qpng.dll", "", "")),
        )
        check(
            "瘦身-D 剔除 imageformats/qsvg",
            not keep(("PyQt5\\Qt5\\plugins\\imageformats\\qsvg.dll", "", "")),
        )
        check(
            "瘦身-D 剔除 translations", not keep(("PyQt5\\Qt5\\translations\\qt_zh_CN.qm", "", ""))
        )
        check("瘦身-D 保留非插件数据", keep(("resources\\models\\det.onnx", "", "")))
    else:
        check("瘦身-D 过滤器存在", False)
    check("S-C2 spec 打包 resources/models", "resources/models" in spec_src)

    # ---- 应用图标与托盘图标（第十二轮） ----
    ico_path = os.path.join(ROOT, "resources", "app.ico")
    raw = _read_head(ico_path, 6 + 16 * 8)
    n_ico = int.from_bytes(raw[4:6], "little")
    dims = [raw[6 + i * 16] or 256 for i in range(n_ico)]
    check("图标 ICO 含多档尺寸(>=7)", n_ico >= 7)
    check("图标 ICO 覆盖 16 与 256", min(dims) == 16 and max(dims) == 256)
    check(
        "图标各尺寸均可原生渲染",
        all(not icons.pixmap("app", size=n).isNull() for n in (16, 24, 32, 48, 256)),
    )
    app_src = _read_text(os.path.join(ROOT, "src", "snapocr", "app.py"))
    check("托盘图标与应用图标同源", 'pixmap("app"' in app_src)
    check(
        "旧的线稿相机图标已移除",
        "camera_line" not in _read_text(os.path.join(ROOT, "src", "snapocr", "ui", "icons.py")),
    )

    # ---- OCR 结果窗「复制文字」反馈（第十二轮） ----
    rw = ResultWindow(cfg=cfg)
    rw.show()
    app.processEvents()
    rw.set_results([("测试文本 ABC 123", 0.99, None)], 0.1)
    rw.copy_text()
    app.processEvents()
    check("结果窗复制成功有提示", rw._toast.isVisible() and rw._toast.text() == tr("copied"))
    rw.set_results([], 0.1)
    rw.copy_text()
    app.processEvents()
    check("结果窗空内容不误报已复制", rw._toast.text() == tr("ocr_empty"))
    rw.close()
    rw.deleteLater()

    # ---- 信创安装器署名（第十二轮） ----
    deb_src = _read_text(os.path.join(ROOT, "deploy", "linux", "build_deb.sh"))
    check(
        "deb 安装器署名含单位名",
        "Maintainer: 中共枣庄市委组织部" in deb_src and "开发单位：中共枣庄市委组织部" in deb_src,
    )

    # ---- 回归守住项：深浅主题渲染（不依赖 WM_SETTINGCHANGE 广播，避免无窗口进程收不到） ----
    from snapocr.ui import theme as _theme
    from snapocr.ui.theme import Theme

    dq = _theme.qss_settings(Theme(dark=True, accent="#0067c0"))
    lq = _theme.qss_settings(Theme(dark=False, accent="#0067c0"))
    check("主题 深色 QSS 深底浅字", "#202020" in dq and "#ffffff" in dq)
    check("主题 浅色 QSS 浅底深字", "#f3f3f3" in lq and "#1b1b1b" in lq)
    sd4 = SettingsDialog(cfg)
    sd4.retheme(Theme(dark=True, accent="#0067c0"))
    check("主题 深色下设置窗套用深色样式", "#202020" in sd4.styleSheet())
    sd4.retheme(Theme(dark=False, accent="#0067c0"))
    check("主题 浅色下设置窗套用浅色样式", "#f3f3f3" in sd4.styleSheet())
    sd4.deleteLater()

    # ---- §33 自测轮修复项（A1~A11 / C1~C3；拆分到 scripts/probes/round33_suite.py，
    #      主文件已近 800 行上限，沿用 ux_suite 的 Ctx 注入模式）----
    from probes.round33_suite import Ctx as _Ctx33
    from probes.round33_suite import run as run_round33

    run_round33(_Ctx33(app=app, scr=scr, cfg=cfg, check=check, skip=skip, cfg_path=tmp_cfg))

    print("\n== 修复项探针: PASS=%d FAIL=%d SKIP=%d ==" % (len(OK), len(FAIL), len(SKIP)))
    if SKIP:
        print("跳过项（环境不满足）:", ", ".join(SKIP))
    if FAIL:
        print("失败项:", ", ".join(FAIL))
    with contextlib.suppress(OSError):
        os.remove(tmp_cfg)  # 清理隔离配置
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
