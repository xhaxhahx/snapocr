# -*- coding: utf-8 -*-
"""框选遮罩：每块屏一个全屏窗口。

流程：拖动框选（或悬停自动识别窗口→单击选中）→ 松手进入"编辑态"——
选区可 8 向手柄微调/框内拖动移动，悬浮工具条贴在选区下方，
「编辑」按钮展开/收起标注工具（画笔/涂色/文字/矩形/椭圆/箭头/马赛克，
直接画在遮罩的选区上）。右键选区外/Esc = 取消。

历史注记：必须用 Qt.Window 而非 Qt.Tool——部分环境(如 RDP/虚拟机 DWM)不合成
全屏 Tool 窗口，导致遮罩不可见（详见 docs/05-测试报告.md）。"""

import os
import time

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QLabel, QWidget

from ..i18n import tr
from ..platform import windowdetect
from . import clipboard as clip
from . import theme
from .clipboard import ask_filename as _ask_filename
from .editor import TOOL_SELECT, CanvasWidget, EditorToolbar
from .preview_dialog import PreviewDialog

HANDLE_R = 5  # 手柄半径（逻辑px）
MAG_BOX = 120  # 放大镜边长（逻辑px）
# 放大倍数：MAG_BOX/ MAG_ZOOM = 采样边长（逻辑px）。5 倍 → 采样 24px，
# 比原先 8 倍（仅采样 15px）能多看到一圈上下文，定位窗口/控件边缘更稳。
MAG_ZOOM = 5
SNAP_PX = 8  # 窗口/控件边缘吸附阈值（逻辑px）


def _make_cross_cursor():
    """小尺寸高对比十字光标：黑描边 + 白芯，任意背景可辨（替代全屏十字线）。"""
    from PyQt5.QtGui import QCursor, QPainter, QPen, QPixmap

    size = 19
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    c = size // 2
    for w, col in ((5, QColor(0, 0, 0, 200)), (2, QColor("#ffffff"))):
        p.setPen(QPen(col, w, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(0, c, size - 1, c)
        p.drawLine(c, 0, c, size - 1)
    p.end()
    return QCursor(pm, c, c)


class OverlayWindow(QWidget):
    """单屏遮罩 + 内嵌标注画布。"""

    ocrRequested = pyqtSignal(object, QRectF, object)  # 原始选区图, 全局矩形, 屏
    cancelled = pyqtSignal()  # 用户取消（Esc/右键外/取消按钮）
    finished = pyqtSignal()  # 会话自然结束（完成/复制/保存后）
    selectionMoved = pyqtSignal()  # 选区被移动（用于关闭结果窗等联动）

    def __init__(self, screen, pm, cfg, ocr_busy_signal=None):
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Window
            | Qt.NoDropShadowWindowHint,
        )
        self.screen = screen
        self.pm = pm  # 已抓屏 QPixmap（带 DPR）
        self.dpr = self.pm.devicePixelRatio() or 1.0
        self.img = self.pm.toImage()  # 物理像素
        self.img.setDevicePixelRatio(1.0)
        self.screen_rect = screen.geometry()  # 全局逻辑坐标
        self.setGeometry(self.screen_rect)
        self._cross_cursor = _make_cross_cursor()
        # paintEvent 每帧全窗口重画（底图 + 暗化层，无透出区域）：声明不透明，让 Qt
        # 跳过系统背景擦除。减少与 DWM 表面交互的路径差异——系统主题切换会重建合成
        # 缓存，少一次擦除就少一处不同步的机会（用户实测集显环境切主题后拖影必现）。
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        # 截图会话与输入法无关：遮罩只收 Esc/Enter/F1，无合成输入需求。默认所有
        # 窗口都可被输入法关联，activateWindow 后 Windows TSF 会在任务栏语言栏显示
        # 输入法标识，占位导致托盘图标左移、关闭后又右移，用户点托盘时位置错位
        # 点空。禁掉输入法关联后 TSF 不为本窗口（含子控件工具条）建 IME 上下文，
        # 任务栏不再出现标识；键盘事件（keyPressEvent）不受影响，需要真正输入文字的
        # TEXT 工具 QTextEdit 仍单独启用输入法。
        self.setAttribute(Qt.WA_InputMethodEnabled, False)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.PreventContextMenu)  # 右键手势归遮罩，禁系统菜单
        self.setCursor(self._cross_cursor)
        self.cfg = cfg

        self.sel = None  # QRectF 局部逻辑坐标
        self.dragging = False  # 正在手动框选
        self.finalized = False  # 选区已确认（编辑态）
        self.hover_rect = None  # 窗口自动识别高亮（idle 阶段）
        self.drag_start = QPointF()
        self.press_pos = QPointF()
        self.drag_mode = None  # None/'move'/'resize'
        self.resize_dir = ""
        self.move_offset = QPointF()
        self.expanded = False
        self._right_press = False
        self._mouse_pos = None  # 未知真实指针位置前不画放大镜（避免屏幕中心幽灵框）
        self._last_detect_t = 0.0  # 实例属性：多屏多遮罩互不干扰
        self._snap_target = None  # 边缘吸附目标（窗口/控件矩形）
        self._last_snap_t = 0.0
        self._mag_rect = None  # 放大镜当前脏矩形（只重绘小窗，4K 下省整屏重绘）
        self._mag_label = None  # 编辑态手柄缩放时的置顶放大镜标签（U6，懒创建）
        # 选区移动/缩放按帧合并（§33.2 C3）：高轮询鼠标（125~1000Hz）下每个
        # move 事件全链重算（整图 copy + 全笔画重建，实测约 10ms/事件）会打满
        # 单核；同一帧只执行最后一次位置
        self._move_coalesce = QTimer(self)
        self._move_coalesce.setSingleShot(True)
        self._move_coalesce.setInterval(16)
        self._move_coalesce.timeout.connect(self._apply_pending_move)
        self._pending_move_pos = None

        self._hint_font = QFont()
        self._hint_font.setPixelSize(12)

        self.canvas = None  # 编辑态创建
        self.toolbar = EditorToolbar(self)
        self.toolbar.hide()
        self.toolbar.editToggled.connect(self._on_edit_toggle)
        self.toolbar.toolChanged.connect(self._on_tool)
        self.toolbar.colorChanged.connect(self._on_color)
        self.toolbar.widthChanged.connect(self._on_width)
        self.toolbar.textSizeChanged.connect(self._on_text_size)
        self.toolbar.textWeightChanged.connect(self._on_text_weight)
        self.toolbar.fontChanged.connect(self._on_font)
        self.toolbar.undoClicked.connect(lambda: self.canvas and self.canvas.undo())
        self.toolbar.redoClicked.connect(lambda: self.canvas and self.canvas.redo())
        self.toolbar.clearClicked.connect(lambda: self.canvas and self.canvas.clear_all())
        self.toolbar.ocrClicked.connect(self._ocr)
        self.toolbar.set_ocr_active(False)
        self.toolbar.copyClicked.connect(self._copy)
        self.toolbar.copyFileClicked.connect(self._copy_as_file)
        self.toolbar.saveClicked.connect(self._save)
        self.toolbar.cancelClicked.connect(self.cancelled)

        self.toast = QLabel(self)
        self.toast.setObjectName("toast")
        self.toast.setAttribute(Qt.WA_TransparentForMouseEvents)  # 永不挡十字/点击
        self.toast.hide()  # 修复：默认可见时会在左上角留一块灰块
        self._preview = None  # 预览确认窗

        # OCR 进行中 → 「OCR识别」按钮呈现蓝底激活态
        if ocr_busy_signal is not None:
            ocr_busy_signal.connect(self.toolbar.set_ocr_active)

        self.retheme(theme.current())
        theme.manager.changed.connect(self.retheme)

    # ---------- 主题 ----------
    def retheme(self, t):
        self._t = t
        self.toast.setStyleSheet(
            "#toast { background: rgba(20,22,26,225); color: #ffffff;"
            " border-radius: 6px; padding: 6px 14px; font-size: 12px; }"
        )
        # 主题切换（setStyleSheet 触发 unpolish/polish）会让 Qt 对整个窗口做全量重贴，
        # 而不是只贴脏矩形区。脏矩形机制下 backing store 的历史帧（历次放大镜 tile 的
        # 旧边缘）平时不上屏，此刻会一起被贴出，形成"竖条拖影"（本地 dpr=1/2 难复现，
        # 集显 + 系统 DWM 合成缓存重建的环境下必现）。切主题时同步全量重绘一次冲掉残留。
        self._mag_rect = None
        if self.isVisible():
            self.repaint()

    # ---------- 生命周期 ----------
    def start(self):
        # 用真实指针位置初始化放大镜；指针不在本屏（多屏）时保持 None，不画
        from PyQt5.QtGui import QCursor

        lp = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(lp):
            self._mouse_pos = QPointF(lp)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)
        theme.apply_window_chrome(self, rounded=False)  # 全屏遮罩不要 Win11 圆角

    def release_buffers(self):
        """会话结束立即释放抓屏缓冲（4K 双屏可达数百 MB 瞬态占用）。"""
        self._mag_rect = None
        self.pm = QPixmap()
        self.img = QImage()

    MAX_CAPTURE_DIM = 12000  # 尺寸钳制（借鉴 Firefox MAX_CAPTURE_DIMENSION）：防异常区域

    BORDER_W = 2  # 选区边框宽度（边框环画在遮罩层，画布从内缩矩形开始）

    def _content_rect(self) -> QRectF:
        """选区内缩边框后的内容矩形（画布区域）。"""
        return self.sel.adjusted(self.BORDER_W, self.BORDER_W, -self.BORDER_W, -self.BORDER_W)

    def crop_image(self) -> object:
        """原始选区（不含标注），物理像素。"""
        r = self._dev_rect(self._content_rect())
        r = r.intersected(self.img.rect())
        if r.width() > self.MAX_CAPTURE_DIM or r.height() > self.MAX_CAPTURE_DIM:
            r = r.intersected(
                QRectF(0, 0, self.MAX_CAPTURE_DIM, self.MAX_CAPTURE_DIM).toAlignedRect()
            )
        return self.img.copy(r)

    def composite(self):
        """含标注的合成图。"""
        if self.canvas is None:
            return self.crop_image()
        return self.canvas.render_to_image()

    def _dev_rect(self, sel):
        return QRectF(
            sel.left() * self.dpr,
            sel.top() * self.dpr,
            sel.width() * self.dpr,
            sel.height() * self.dpr,
        ).toAlignedRect()

    def global_rect(self) -> QRectF:
        return self.sel.translated(self.screen_rect.topLeft())

    # ---------- 编辑态建立 ----------
    def _finalize(self):
        self.finalized = True
        self.hover_rect = None
        self.setCursor(Qt.ArrowCursor)  # 编辑态改用常规指针（手柄/移动随悬停变化）
        img = self.crop_image()
        self.canvas = CanvasWidget(
            img, self.dpr, mosaic_block=int(self.cfg.get("mosaic_block", 10)), parent=self
        )
        # 重新框选后新画布沿用工具条当前的颜色/粗细/字号/字重/字体：工具条是会话内的
        # 状态持有者（画布随 teardown 销毁重建，曾回默认红/中档，与色片显示不一致）
        self.canvas.color = self.toolbar.btn_color._hex
        self.canvas.line_width = self.toolbar.width_combo.currentData() or 5
        self.canvas.text_size = self.toolbar.size_combo.currentData() or 18
        self.canvas.text_weight = self.toolbar.weight_combo.currentData() or QFont.Normal
        self.canvas.text_font = self.toolbar.font_combo.currentFont().family()
        self.canvas.setGeometry(self._content_rect().toRect())
        self.canvas.show()
        self.canvas.stackChanged.connect(self.toolbar.set_undo_redo_enabled)
        self.toolbar.set_undo_redo_enabled(False, False)
        self.toolbar.set_tool(TOOL_SELECT)
        self._on_edit_toggle(True)  # 编辑菜单默认展开
        self.toolbar.show()
        self.toolbar.raise_()
        self._update_all()

    def _set_canvas_passthrough(self):
        """选择工具/未展开时画布对鼠标透明 → 遮罩处理移动/微调；绘制工具激活才接管。"""
        active = self.expanded and self.toolbar.current_tool not in (TOOL_SELECT, None)
        self.canvas.setAttribute(Qt.WA_TransparentForMouseEvents, not active)

    def _on_edit_toggle(self, exp):
        self.expanded = exp
        # set_expanded 内部播放高度动画，并按目标高度逐帧重定位，不用在此处再 reposition
        self.toolbar.set_expanded(exp)
        self._set_canvas_passthrough()

    def _on_tool(self, kind):
        self.toolbar.set_tool(kind)
        self.canvas.set_tool(None if kind == TOOL_SELECT else kind)
        self._set_canvas_passthrough()
        self._reposition_toolbar()
        self.cfg.set("last_tool", kind)

    def _on_color(self, hexc):
        self.canvas.color = hexc
        self.toolbar.set_color(hexc)
        self.cfg.set("pen_color", hexc)

    def _on_width(self, w):
        self.canvas.line_width = w
        self.toolbar.set_width(w)
        if self.canvas.tool in ("pen", "highlight", "mosaic"):
            self.canvas._update_brush_cursor()

    def _on_text_size(self, s):
        self.canvas.text_size = s

    def _on_text_weight(self, weight):
        self.canvas.text_weight = weight

    def _on_font(self, family):
        self.canvas.text_font = family

    # ---------- 工具条定位 ----------
    def _reposition_toolbar(self, h_override=None):
        """把工具条放到选区下方；空间不足翻到上方，都不够则贴屏幕底边。

        h_override：展开/折叠动画期间传入"目标总高"，位置一次性按最终高度定点，
        避免动画中途因高度增长而把工具条翻转位置造成抖动。
        """
        ts_w = self.toolbar.width()
        ts_h = self.toolbar.height() if h_override is None else h_override
        x = self.sel.right() - ts_w
        x = max(4, min(x, self.width() - ts_w - 4))
        y = self.sel.bottom() + 8
        if y + ts_h > self.height() - 4:
            y = self.sel.top() - ts_h - 8
            if y < 4:
                y = self.height() - ts_h - 4
        self.toolbar.move(int(x), int(y))

    # ---------- 绘制 ----------
    def _update_all(self):
        """全窗口重绘（显式目标矩形，外扩 1 逻辑像素）。

        为什么不用无参 `update()`：dpr≠1（125%/150%/200% 缩放）时 Qt 把逻辑 dirty
        rect 换算成设备像素存在 rounding——若 backing store 宽 = ceil(w*dpr) 而
        dirty 宽 = floor(w*dpr)，最右/最下一列设备像素**永远不在脏区里**，拖动选区
        时该列残留上一帧内容，表现为**竖条残影**（客户机实测，100% 缩放不出现，
        因 dpr=1 无 rounding）。外扩 1 逻辑像素（≥1 设备像素）可覆盖该缺口。
        """
        self.update(QRect(0, 0, self.width(), self.height()).adjusted(-1, -1, 1, 1))

    def paintEvent(self, ev):
        t = getattr(self, "_t", None) or theme.current()
        accent = t.accent
        p = QPainter(self)
        # 底图显式铺满目标矩形（不用 drawPixmap(0,0,pm) 的隐式尺寸）：
        # dpr≠1 时 pixmap 逻辑尺寸与窗口逻辑尺寸的 rounding 可能差 1 设备像素，
        # 隐式绘制会漏掉最右/最下一列 → 竖条残影。显式 target rect 由 Qt 拉伸铺满。
        p.drawPixmap(
            QRect(0, 0, self.width(), self.height()),
            self.pm,
            QRect(0, 0, self.pm.width(), self.pm.height()),
        )
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        # 兼容性关键：表面须含不透明区域，否则部分环境 DWM 丢弃首帧
        p.fillRect(0, 0, self.width(), 2, accent)
        # 窗口自动识别高亮（未框选时的悬停）
        if self.hover_rect is not None and not self.dragging and not self.finalized:
            self._draw_rect_border(p, self.hover_rect, accent, 2)
        if self.sel is not None and not self.sel.isEmpty():
            # Qt 语义：drawPixmap(point, pixmap, sourceRect) 的 **sourceRect 是 pixmap 的
            # 设备像素矩形**，point 才用当前 painter 坐标（QWidget 的 painter 原生即逻辑
            # 坐标，本类无 scale）。sel 是逻辑坐标，sourceRect 必须经 _dev_rect 转换；
            # dpr≠1（125%/150%/200% 缩放）时直接传 sel 会取错源区，且 QPixmap 的 dpr 使
            # 目标绘制尺寸 = 源尺寸/dpr，导致选区内只有左上角约 1/dpr² 面积有内容、
            # 其余仍是暗化层（用户实测 #91221b = #ff3b30 × 0.57 暗化系数，精确吻合）。
            # 注：crop_image() 同样用 _dev_rect；本方法曾漏转。
            # PyQt5 重载陷阱：drawPixmap(QPointF, QPixmap, QRect) 不存在（QPointF 只配
            # QRectF），_dev_rect 返回 QRect 需再包一层，否则 TypeError 且进程 exit 127。
            p.drawPixmap(self.sel.topLeft(), self.pm, QRectF(self._dev_rect(self.sel)))
            self._draw_rect_border(p, self.sel, accent, 2)
            if self.finalized:
                self._draw_handles(p)
            self._draw_size_label(p)
        # 放大镜：未进入编辑态全程跟随（悬停与拖动中）
        if not self.finalized and self._mouse_pos is not None:
            self._draw_magnifier(p, self._mouse_pos)
        p.end()

    @staticmethod
    def _draw_rect_border(p, rect, color, width):
        """沿矩形四边绘制 width 像素实心边框环（与画布内容矩形严丝合缝）。"""
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        x1, y1 = rect.left(), rect.top()
        x2, y2 = rect.right(), rect.bottom()
        p.fillRect(QRectF(x1, y1, x2 - x1, width), color)  # 上
        p.fillRect(QRectF(x1, y2 - width, x2 - x1, width), color)  # 下
        p.fillRect(QRectF(x1, y1, width, y2 - y1), color)  # 左
        p.fillRect(QRectF(x2 - width, y1, width, y2 - y1), color)  # 右

    def _draw_handles(self, p):
        t = getattr(self, "_t", None) or theme.current()
        p.setPen(QPen(t.accent, 1.5))
        p.setBrush(QColor("#ffffff"))
        for pt in self._handle_points():
            p.drawEllipse(pt, HANDLE_R, HANDLE_R)

    def _handle_points(self):
        r = self.sel
        x1, y1, x2, y2 = r.left(), r.top(), r.right(), r.bottom()
        xm, ym = r.center().x(), r.center().y()
        return [
            QPointF(x1, y1),
            QPointF(xm, y1),
            QPointF(x2, y1),
            QPointF(x2, ym),
            QPointF(x2, y2),
            QPointF(xm, y2),
            QPointF(x1, y2),
            QPointF(x1, ym),
        ]

    _DIRS = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

    def _draw_size_label(self, p):
        if self.sel is None or self.sel.isEmpty():
            return
        t = getattr(self, "_t", None) or theme.current()
        text = "%d × %d" % (round(self.sel.width()), round(self.sel.height()))
        p.setFont(self._hint_font)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 14
        h = fm.height() + 6
        x = self.sel.left()
        y = self.sel.top() - h - 6
        if y < 2:
            y = self.sel.top() + 6
        p.setPen(Qt.NoPen)
        p.setBrush(t.accent)
        p.drawRoundedRect(QRectF(x, y, w, h), 4, 4)
        p.setPen(QColor(t.on_accent))
        p.drawText(QRectF(x, y, w, h), Qt.AlignCenter, text)

    def _magnifier_rect(self, pos):
        """放大镜外框（逻辑坐标）；贴边时自动翻到指针另一侧。"""
        if pos is None:
            return None
        box = MAG_BOX
        bx = pos.x() + 18
        by = pos.y() + 18
        if bx + box > self.width() - 4:
            bx = pos.x() - 18 - box
        if by + box > self.height() - 4:
            by = pos.y() - 18 - box
        return QRectF(bx, by, box, box)

    def _update_magnifier_dirty(self, new_pos, extra=None):
        """只重绘放大镜小窗（旧框∪新框），避免 4K 下每次移动整屏重绘。

        extra：额外需要一并重绘的区域（如悬停高亮环变化，R3），与放大镜旧新框取并集。

        两条硬约束（均来自 2026-10-21 客户机实测 + 本地 QT_SCALE_FACTOR=1.25 复现）：

        1. **余量必须 ≥8 逻辑像素**：dpr≠1 时 Qt 把逻辑 dirty rect 换算设备像素
           存在 rounding，叠加放大镜 1.5px 笔宽、drawImage 的 dpr 缩放边缘与
           toAlignedRect 取整，±3 会让放大镜经过的每一行残留一条未暗化底图
           （竖条/横条拖影，步距=鼠标每帧位移）。实测 ±3 残影 2747px、±8 为 0px。
        2. **位置跳变（贴边缘触发 _magnifier_rect 翻转）必须走全量**：翻转使旧/新
           框单帧相距可达 136px（by 从 pos.y()-138 跳到 pos.y()+18），又高又窄的
           dirty 矩形在设备像素 rounding 下会漏列，逐帧累积成整列竖条
           （客户机报告"贴边缘滑动有竖线、开始框选后放大镜变两个"——后者即
           hover 期残留的放大镜碎片与新放大镜叠加）。跳变帧走 _update_all()
           彻底消除；贴边缘是少数情况，全量开销可忽略。
        """
        old = self._mag_rect
        new = self._magnifier_rect(new_pos)
        self._mag_rect = new
        if old is None and new is None and extra is None:
            return
        if old is None or new is None or abs(new.x() - old.x()) > 40 or abs(new.y() - old.y()) > 40:
            # 首帧 / 指针越界 / 翻转跳变：全量重绘，不做局部脏区
            self._update_all()
            return
        r = old.united(new) if (old is not None and new is not None) else (new or old)
        if extra is not None:
            r = r.united(extra)
        self.update(r.toAlignedRect().adjusted(-8, -8, 8, 8))

    def _magnifier_tile(self, pos):
        """放大镜取景 tile（源区裁剪+放大）；指针越界源区为空时返回 None。

        历史注记：曾有"源区不变时复用缩放图"的缓存，但 key 含光标锚定的
        src.x/y——移动时每帧必变、200 帧仅命中 1 次（R4 实测），纯开销已删；
        copy+scale 本身实测仅 0.016ms。IgnoreAspectRatio（非等比扩展）：
        指针贴屏幕边缘时 src 被裁成非正方形，等比扩展会产出超出目标框的
        tile、超出脏区的部分永久残留（客户机"贴边缘出竖线"的根因）；
        放大镜语义就是把 src 拉伸填满方框，各向异性拉伸才是正确行为。
        """
        box = MAG_BOX
        half_dev = int(box / (2 * MAG_ZOOM) * self.dpr)
        c = QPointF(pos.x() * self.dpr, pos.y() * self.dpr)
        src = self.img.rect().intersected(
            QRectF(c.x() - half_dev, c.y() - half_dev, half_dev * 2, half_dev * 2).toAlignedRect()
        )
        if src.isEmpty():
            return None
        tile = self.img.copy(src).scaled(
            int(box * self.dpr), int(box * self.dpr), Qt.IgnoreAspectRatio, Qt.FastTransformation
        )
        tile.setDevicePixelRatio(self.dpr)
        return tile

    def _draw_magnifier(self, p, pos):
        box = MAG_BOX
        tile = self._magnifier_tile(pos)
        if tile is None:
            # 越界（指针暂离图像）：本次不画，但**不**清 _mag_rect —— 若上一帧画过
            # 放大镜，保留旧框才能在下次移动时以 old∪new 正确清除，否则旧 tile 会永久
            # 留在 backing store 里，被主题切换的全窗口重贴一次性贴出（残影）。
            return
        r = self._magnifier_rect(pos)
        self._mag_rect = r
        bx, by = r.left(), r.top()
        p.drawImage(QPointF(bx, by), tile)
        p.setPen(QPen(QColor("#ffffff"), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(bx, by, box, box))
        t = getattr(self, "_t", None) or theme.current()
        p.setPen(QPen(t.accent, 1))
        cx, cy = bx + box / 2, by + box / 2
        p.drawLine(QPointF(cx - 8, cy), QPointF(cx + 8, cy))
        p.drawLine(QPointF(cx, cy - 8), QPointF(cx, cy + 8))

    def _teardown_canvas(self):
        """退出编辑态：移除画布与工具条（重新框选/取消时复用）。"""
        if self.canvas is not None:
            self.canvas.hide()
            self.canvas.deleteLater()
            self.canvas = None
        self._hide_resize_magnifier()
        self.toolbar.hide()
        if self._preview is not None and self._preview.isVisible():
            self._preview.close()

    # ---------- 窗口/控件自动识别 ----------

    def _compute_window_rect(self, pos):
        """控件级下钻（原生子窗口）+ 顶层窗口矩形；物理坐标 → 本遮罩逻辑坐标。"""
        # mapToGlobal 返回的**已是全局坐标**（含屏幕偏移），不能再叠加
        # screen_rect.left()/top()：副屏（如左=1920）会得到 3940 而非 2020，
        # 表现为副屏悬停不高亮、单击选不中窗口、边缘吸附无目标（探针实证）。
        # 主屏 left=0 会掩盖该错误，故只在多屏上暴露。
        gp = self.mapToGlobal(pos.toPoint() if hasattr(pos, "toPoint") else pos)
        dpr = self.dpr
        phys = (gp.x() * dpr, gp.y() * dpr)
        rect = windowdetect.descend_rect_at(phys[0], phys[1])
        if not rect:
            return None
        # 物理 → 本遮罩逻辑坐标
        r = QRectF(
            (rect[0] - self.screen_rect.left() * dpr) / dpr,
            (rect[1] - self.screen_rect.top() * dpr) / dpr,
            (rect[2] - rect[0]) / dpr,
            (rect[3] - rect[1]) / dpr,
        )
        return r.intersected(QRectF(self.rect()))

    def _detect_window(self, pos):
        """悬停高亮用：带 250ms 节流（节流内直接返回上一次结果）。

        250ms（R2，原 120ms）：探测在 UI 线程同步跑 EnumWindows+DWM 下钻，
        本机中位 0.38ms、RDP/集显环境下可达数毫秒——节流越松，规律性顿挫越少；
        高亮框本身是粗粒度提示，4Hz 跟随足够。吸附探测（_snap_target_at）
        保持 120ms 不放：缩放交互期间贴边即时性更敏感。
        """

        now = time.monotonic()
        if now - self._last_detect_t < 0.25:
            return self.hover_rect
        self._last_detect_t = now
        return self._compute_window_rect(pos)

    def _snap_target_at(self, pos):
        """边缘吸附目标：独立节流（与悬停高亮解耦），无则 None。"""

        now = time.monotonic()
        if now - self._last_snap_t >= 0.12:
            self._last_snap_t = now
            self._snap_target = self._compute_window_rect(pos) if pos is not None else None
        return self._snap_target

    # ---------- 交互 ----------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton:
            # 右键按下只记录、不立即取消：等释放仍在遮罩上时才取消，
            # 避免遮罩瞬间消失后右键释放落到桌面、带出系统右键菜单
            if self.canvas is not None:
                self.canvas._commit_pending_text()
            self._right_press = True
            return
        if ev.button() != Qt.LeftButton:
            return
        if self.canvas is not None:
            self.canvas._commit_pending_text()
        if self.finalized:
            pos = ev.pos()
            d = self._hit_handle(pos)
            if d:
                self.drag_mode = "resize"
                self.resize_dir = d
            elif self.sel.contains(pos):
                self.drag_mode = "move"
                self.move_offset = QPointF(self.sel.topLeft()) - QPointF(pos)
            else:
                # 选区外左键拖动 = 重新框选（关闭画布，回到框选阶段替换旧选区）
                self._teardown_canvas()
                self.finalized = False
                self.dragging = True
                self.drag_start = QPointF(pos)
                self.press_pos = QPointF(pos)
                self.sel = QRectF(self.drag_start, self.drag_start)
                self.setCursor(self._cross_cursor)
            self.press_pos = QPointF(pos)
            return
        # 框选开始
        self.dragging = True
        self.drag_start = QPointF(ev.pos())
        self.press_pos = QPointF(ev.pos())
        self.sel = QRectF(self.drag_start, self.drag_start)
        self._update_all()

    def mouseMoveEvent(self, ev):
        pos = ev.pos()
        self._mouse_pos = QPointF(pos)
        if self.dragging:
            old_sel = self.sel
            self.sel = QRectF(self.drag_start, QPointF(pos)).normalized()
            self._update_drag_dirty(old_sel, self.sel)
            return
        if self.finalized:
            if self.drag_mode in ("move", "resize"):
                # 帧合并：只记最后一次位置，16ms 定时器到点统一执行（释放时同步补执行）
                self._pending_move_pos = QPointF(pos)
                self._move_coalesce.start()
            else:
                self._update_cursor(QPointF(pos))
            return
        # idle：窗口自动识别悬停高亮（节流内不重判，但十字光标每帧重绘）
        if self.canvas is None:
            h = self._detect_window(pos)
            if h != self.hover_rect:
                # 高亮框变化：只重绘旧∪新高亮环（含外沿，R3），不再整屏
                old_h = self.hover_rect
                self.hover_rect = h
                extra = None
                m = self.BORDER_W * 2  # 高亮环宽 2px 的外沿余量
                for r in (old_h, h):
                    if r is not None:
                        rr = r.adjusted(-m, -m, m, m)
                        extra = rr if extra is None else extra.united(rr)
                self._update_magnifier_dirty(QPointF(pos), extra=extra)
            else:
                self._update_magnifier_dirty(QPointF(pos))  # 否则只重绘放大镜小窗

    def _snap_translate(self, new_tl, target):
        """整体平移吸附：选区左/右、上/下任一边落入阈值即整体对齐该边。"""
        w, h = self.sel.width(), self.sel.height()
        x, y = new_tl.x(), new_tl.y()
        if abs(x - target.left()) <= SNAP_PX:
            x = target.left()
        elif abs(x + w - target.right()) <= SNAP_PX:
            x = target.right() - w
        if abs(y - target.top()) <= SNAP_PX:
            y = target.top()
        elif abs(y + h - target.bottom()) <= SNAP_PX:
            y = target.bottom() - h
        return QPointF(x, y)

    @staticmethod
    def _snap_val(v, edges):
        """把坐标吸附到最近的候选边（阈值内），否则原样返回。"""
        best, best_d = v, SNAP_PX
        for e in edges:
            d = abs(v - e)
            if d < best_d:
                best, best_d = e, d
        return best

    def _update_drag_dirty(self, old_sel, new_sel):
        """拖动框选的脏区重绘（R1）：新旧选区并集（含边框环与尺寸标签外沿）∪ 放大镜旧新框。

        原实现每个 move 事件整屏重绘（P23 只优化了 idle 悬停路径）；4K/多屏
        RDP 软件光栅下整屏成本按 10~20 倍放大即掉帧。选区从同一角点拖出时
        新旧基本包含，并集近似就是选区本身，脏区从整屏缩到选区量级。
        """
        m_old = self._mag_rect
        m_new = self._magnifier_rect(self._mouse_pos)
        self._mag_rect = m_new
        dirty = None
        for r in (old_sel, new_sel):
            if r is not None and not r.isNull():
                # -24 逻辑余量：覆盖 2px 边框环、选区上方 h+6 的尺寸标签与 dpr 取整
                rr = r.adjusted(-24, -24, 24, 24)
                dirty = rr if dirty is None else dirty.united(rr)
        for r in (m_old, m_new):
            if r is not None:
                dirty = r if dirty is None else dirty.united(r)
        if dirty is None:
            self._update_all()
            return
        self.update(dirty.toAlignedRect().adjusted(-8, -8, 8, 8))

    def _apply_pending_move(self):
        """执行被合并到本帧的最后一次移动/缩放位置（释放时也同步补执行）。"""
        pos, self._pending_move_pos = self._pending_move_pos, None
        if pos is None or not self.finalized or self.drag_mode not in ("move", "resize"):
            return
        if self.drag_mode == "move":
            nl = QPointF(pos) + self.move_offset
            w, h = self.sel.width(), self.sel.height()
            x = max(0.0, min(nl.x(), self.width() - w))
            y = max(0.0, min(nl.y(), self.height() - h))
            self._move_sel_to(QPointF(x, y))
        else:
            self._resize(pos)

    def _move_sel_to(self, new_tl):
        target = self._snap_target_at(self._mouse_pos)
        if target is not None:
            new_tl = self._snap_translate(new_tl, target)
        delta = QPointF(new_tl.x() - self.sel.left(), new_tl.y() - self.sel.top())
        if abs(delta.x()) < 0.01 and abs(delta.y()) < 0.01:
            return  # 吸附把位置钉回原处：无实际位移，不当作"移动选区"
        self.selectionMoved.emit()  # 真实位移发生 → 联动关闭结果窗（§33.1 A9）
        self.sel.moveTopLeft(new_tl)
        if self.canvas is not None:
            # 取景框语义：框移到哪，内容就取屏幕冻结图的哪块（笔画锚定屏幕位置）
            self.canvas.setGeometry(self._content_rect().toRect())
            self.canvas.set_base(self.img.copy(self._dev_rect(self._content_rect())))
            self.canvas.shift_strokes(-delta.x() * self.dpr, -delta.y() * self.dpr)
        self._reposition_toolbar()
        self._update_all()

    def _resize(self, pos):
        r = QRectF(self.sel)
        d = self.resize_dir
        target = self._snap_target_at(self._mouse_pos)
        edges_x = (target.left(), target.right()) if target is not None else ()
        edges_y = (target.top(), target.bottom()) if target is not None else ()
        if "w" in d:
            r.setLeft(min(self._snap_val(pos.x(), edges_x), r.right() - 10))
        if "e" in d:
            r.setRight(max(self._snap_val(pos.x(), edges_x), r.left() + 10))
        if "n" in d:
            r.setTop(min(self._snap_val(pos.y(), edges_y), r.bottom() - 10))
        if "s" in d:
            r.setBottom(max(self._snap_val(pos.y(), edges_y), r.top() + 10))
        r.setLeft(max(0.0, r.left()))
        r.setTop(max(0.0, r.top()))
        r.setRight(min(float(self.width() - 1), r.right()))
        r.setBottom(min(float(self.height() - 1), r.bottom()))
        self.sel = r.normalized()
        if self.canvas is not None:
            delta = QPointF(r.left() - self.canvas.x(), r.top() - self.canvas.y())
            self.canvas.setGeometry(self._content_rect().toRect())
            self.canvas.set_base(self.img.copy(self._dev_rect(self._content_rect())))
            self.canvas.shift_strokes(-delta.x() * self.dpr, -delta.y() * self.dpr)
        self._reposition_toolbar()
        self._update_all()
        self._update_resize_magnifier()  # U6：手柄缩放期间跟随的像素级放大镜

    def _update_resize_magnifier(self):
        """编辑态手柄缩放时的放大镜（U6）。

        遮罩父绘层会被画布子控件盖住（children 恒在 parent 之上），故这里用
        懒创建的置顶 QLabel 承载；仅缩放手势期间可见——这是最需要像素级
        对齐的时刻（框选阶段的父绘放大镜不受影响）。
        """
        if self._mouse_pos is None:
            return
        r = self._magnifier_rect(self._mouse_pos)
        tile = self._magnifier_tile(self._mouse_pos)
        if r is None or tile is None:
            self._hide_resize_magnifier()
            return
        if self._mag_label is None:
            self._mag_label = QLabel(self)
            self._mag_label.setObjectName("magLabel")
            self._mag_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            self._mag_label.setStyleSheet(
                "#magLabel { border: 1px solid #ffffff; background: transparent; }"
            )
        self._mag_label.setPixmap(QPixmap.fromImage(tile))
        self._mag_label.setGeometry(r.toRect())
        self._mag_label.raise_()  # 画布重建后仍在画布之上
        self._mag_label.show()

    def _hide_resize_magnifier(self):
        if self._mag_label is not None:
            self._mag_label.hide()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.RightButton:
            # 右键在遮罩上释放：选区内/外都取消（遮罩全程盖住手势，系统菜单无从谈起）
            if getattr(self, "_right_press", False):
                self._right_press = False
                if self.canvas is not None:
                    self.canvas._commit_pending_text()
                self.cancelled.emit()
            return
        if ev.button() != Qt.LeftButton:
            return
        if self.dragging:
            self.dragging = False
            # 健壮性：快速拖拽可能没有任何中间 move 事件，用释放点重建选区
            self.sel = QRectF(self.drag_start, QPointF(ev.pos())).normalized()
            moved = (QPointF(ev.pos()) - self.press_pos).manhattanLength() >= 4
            if not moved and self.hover_rect is not None and not self.finalized:
                self.sel = QRectF(self.hover_rect)  # 单击选中识别到的窗口
            if self.sel is None or self.sel.width() < 8 or self.sel.height() < 8:
                self.sel = None
                self._update_all()
                return
            self._finalize()
            return
        if self.finalized and self.drag_mode:
            was_resize = self.drag_mode == "resize"
            if self._pending_move_pos is not None:  # 释放即定格：合并中的最后位置立即生效
                self._move_coalesce.stop()
                self._apply_pending_move()
            self.drag_mode = None
            self._update_cursor(QPointF(ev.pos()))
            if was_resize:
                # 缩放结束：收掉跟随的放大镜标签并重绘一次清痕迹
                self._hide_resize_magnifier()
                self._update_all()

    def mouseDoubleClickEvent(self, ev):
        # 双击选区 = 复制并结束（常见习惯）
        if (
            ev.button() == Qt.LeftButton
            and self.finalized
            and self.sel is not None
            and self.sel.contains(ev.pos())
        ):
            self._done()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            if self.canvas is not None:
                self.canvas._commit_pending_text()
            self.cancelled.emit()
        elif ev.key() in (Qt.Key_Return, Qt.Key_Enter) and self.finalized:
            # Enter = 主动作（完成 → 预览）
            self._done()
        elif ev.key() == Qt.Key_F1:
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.information(
                self, tr("shortcuts"), tr("shortcuts_text", self.cfg.get("hotkey"))
            )
        else:
            super().keyPressEvent(ev)

    def _hit_handle(self, pos):
        if self.sel is None:
            return None
        for d, pt in zip(self._DIRS, self._handle_points()):
            if (QPointF(pos) - pt).manhattanLength() <= HANDLE_R + 3:
                return d
        return None

    def _update_cursor(self, pos):
        d = self._hit_handle(pos)
        if d:
            cursors = {
                "nw": Qt.SizeFDiagCursor,
                "se": Qt.SizeFDiagCursor,
                "ne": Qt.SizeBDiagCursor,
                "sw": Qt.SizeBDiagCursor,
                "n": Qt.SizeVerCursor,
                "s": Qt.SizeVerCursor,
                "e": Qt.SizeHorCursor,
                "w": Qt.SizeHorCursor,
            }
            self.setCursor(cursors[d])
        elif self.sel is not None and self.sel.contains(pos):
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.ArrowCursor)  # 选区外用箭头

    # ---------- 动作 ----------
    def hideEvent(self, ev):
        # 遮罩被关闭时兜底收掉预览窗，避免孤儿窗口
        if self._preview is not None and self._preview.isVisible():
            self._preview.close()
        super().hideEvent(ev)

    def _toast(self, text):
        self.toast.setText(text)
        self.toast.adjustSize()
        self.toast.move((self.width() - self.toast.width()) // 2, self.height() - 80)
        self.toast.show()
        self.toast.raise_()
        QTimer.singleShot(1400, self.toast.hide)

    def _copy(self):
        # 写入后回读校验（被占用时重试），失败如实提示，不再无条件报"已复制"
        ok = clip.set_image(self.composite())
        self._toast(tr("copied") if ok else tr("copy_failed"))

    def _copy_as_file(self):
        """把标注图复制为 JPG 文件到剪贴板（弹窗输入文件名，默认同保存默认名）。"""
        text = _ask_filename(self, tr("default_filename_jpg"))
        if text is None:
            return
        self.canvas._commit_pending_text()
        path = clip.copy_image_as_file(self.composite(), text)
        self._toast(
            tr("copied_as_file", os.path.basename(path))
            if path
            else tr("copy_file_failed", text.strip())
        )

    def _save(self):
        from PyQt5.QtWidgets import QFileDialog

        from ..paths import pictures_dir

        default_dir = self.cfg.get("save_dir") or pictures_dir()
        name = tr("default_filename") % time.strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("save"), os.path.join(default_dir, name), "PNG (*.png);;JPEG (*.jpg)"
        )
        if not path:
            return
        img = self.composite()
        if path.lower().endswith((".jpg", ".jpeg")):
            ok = img.save(path, "JPG", 90)  # 默认 75% 偏糊，显式提到 90%
        else:
            ok = img.save(path)
        if ok:
            self.cfg.set("save_dir", os.path.dirname(path))
            self._toast(tr("saved", path))
        else:
            self._toast(tr("save_failed", path))

    def _ocr(self):
        self.canvas._commit_pending_text()
        # 所见即所得（U1）：OCR 读含标注的合成图——马赛克遮住的内容不再被
        # "绕过识别"（隐私直觉陷阱）；无标注时 composite 与原始裁剪像素一致
        self.ocrRequested.emit(self.composite(), self.global_rect(), self.screen)

    def _done(self):
        """完成 → 预览确认窗（复制/另存/重试），借鉴 Firefox 预览流。"""
        if self._preview is not None and self._preview.isVisible():
            self._preview.raise_()
            return
        if self._preview is not None:  # 上一轮已关闭的预览窗：回收，避免对象堆积
            self._preview.deleteLater()
            self._preview = None
        self.canvas._commit_pending_text()
        img = self.composite()
        pv = PreviewDialog(img, self.cfg)
        pv.copyDone.connect(lambda: (pv.close(), self.finished.emit()))
        pv.saveDone.connect(lambda: (pv.close(), self.finished.emit()))
        pv.retried.connect(lambda: None)  # 关闭预览，回到编辑
        self._preview = pv
        pv.show_near(self.screen)
