# -*- coding: utf-8 -*-
"""标注工具条与画布。工具直接嵌入截屏遮罩使用（工具条浮于遮罩之上，
支持编辑菜单展开/收起）。画笔/涂色(荧光笔)/文字/矩形/椭圆/箭头/马赛克，
撤销重做、复制到剪贴板、保存、一键 OCR。所有笔画坐标以设备像素存储。"""

import math
import sys

from PyQt5.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QCursor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFontComboBox,
    QFrame,
    QHBoxLayout,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from . import icons, theme

# 重导出：探针与旧调用方仍从 ui.editor 导入这些符号（内部已改用 color_picker）
from .color_picker import COLORS, STANDARD_COLORS, ColorPickerPopup  # noqa: F401

TOOL_SELECT = "select"
TOOL_PEN = "pen"
TOOL_HIGHLIGHT = "highlight"
TOOL_TEXT = "text"
TOOL_RECT = "rect"
TOOL_ELLIPSE = "ellipse"
TOOL_ARROW = "arrow"
TOOL_MOSAIC = "mosaic"
TOOL_ERASER = "eraser"

# 文字字重：QFont.Weight 值 + i18n 键
TEXT_WEIGHTS = [
    (QFont.Light, "weight_light"),
    (QFont.Normal, "weight_normal"),
    (QFont.Bold, "weight_bold"),
]

# 档位：(px, i18n 键)。用户可见文案必须走 tr()（docs/10 §4.3-19），中英在 i18n.py 齐备。
WIDTHS = [(2, "width_thin"), (5, "width_medium"), (10, "width_thick"), (16, "width_bold")]
TEXT_SIZES = [14, 18, 24, 32]

# 编辑区展开/折叠动画时长（ms）
EXPAND_ANIM_MS = 190


def _clamp_popup_to_screen(combo):
    """把下拉弹出容器横向钳回所在屏幕的可用区（纵向的上下翻转 Qt 自带）。

    Qt 默认把弹出列表左对齐到下拉框：列表比下拉框宽（字体名、长条目）且下拉框
    贴近屏幕右缘时，列表会溢出到屏幕外（2026-10-26 用户实测）。
    """
    popup = combo.view().window()
    g = popup.geometry()
    scr = QApplication.screenAt(combo.mapToGlobal(QPoint(0, 0))) or QApplication.primaryScreen()
    ag = scr.availableGeometry()
    x = min(max(g.x(), ag.left()), ag.right() - g.width() + 1)
    if x != g.x():
        popup.move(x, g.y())


class EdgeAwareComboBox(QComboBox):
    """弹出列表靠边自适应的下拉框（工具条粗细/字号、设置页倍率/语言等共用）。"""

    def showPopup(self):
        super().showPopup()
        _clamp_popup_to_screen(self)


class EdgeAwareFontComboBox(QFontComboBox):
    """字体下拉的同款靠边自适应——字体名普遍长于框宽，是最常见的溢出场景。"""

    def showPopup(self):
        super().showPopup()
        _clamp_popup_to_screen(self)


class EditorToolbar(QWidget):
    toolChanged = pyqtSignal(str)
    colorChanged = pyqtSignal(str)
    widthChanged = pyqtSignal(int)
    textSizeChanged = pyqtSignal(int)
    textWeightChanged = pyqtSignal(int)
    fontChanged = pyqtSignal(str)
    editToggled = pyqtSignal(bool)  # 编辑菜单展开/收起
    undoClicked = pyqtSignal()
    redoClicked = pyqtSignal()
    clearClicked = pyqtSignal()
    ocrClicked = pyqtSignal()
    copyClicked = pyqtSignal()
    copyFileClicked = pyqtSignal()
    saveClicked = pyqtSignal()
    cancelClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("edToolbar")
        # 工具条是遮罩的子控件，会继承遮罩的 SizeAllCursor（选区内移动手势）。
        # 显式声明箭头：子按钮未单独设光标时随之继承，避免"鼠标在按钮上仍显示移动光标"。
        self.setCursor(Qt.ArrowCursor)
        self._rows = QVBoxLayout(self)
        self._rows.setContentsMargins(8, 6, 8, 6)
        self._rows.setSpacing(4)
        self._tool_buttons = {}
        self._plain_buttons = []  # (btn, icon_name) 撤销/重做等图标按钮
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.current_tool = TOOL_SELECT

        # --- 行A（常驻，文字按钮）：编辑切换 | OCR | 复制 | 保存 | 取消 ---
        rowA = QHBoxLayout()
        rowA.setSpacing(4)
        self._rows.addLayout(rowA)

        self.btn_edit = QToolButton(objectName="btnEdit")
        self.btn_edit.setText(" " + tr("edit"))
        self.btn_edit.setCheckable(True)
        self.btn_edit.setProperty("textBtn", True)
        self.btn_edit.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        # 图标约束到 16px + 固定高：图标按钮自然高度(29)比行 A 纯文字按钮(26)高 3px
        self.btn_edit.setIconSize(QSize(16, 16))
        self.btn_edit.setFixedHeight(26)
        self.btn_edit.clicked.connect(lambda: self.editToggled.emit(self.btn_edit.isChecked()))
        rowA.addWidget(self.btn_edit)

        sepA = QFrame()
        sepA.setObjectName("sep")
        sepA.setFixedSize(1, 26)
        rowA.addWidget(sepA)

        self.btn_ocr = QToolButton(objectName="btnOcr")
        self.btn_ocr.setText(" " + tr("ocr"))
        self.btn_ocr.setCheckable(True)  # 识别进行中 = 蓝底激活态
        self.btn_ocr.setProperty("textBtn", True)
        self.btn_ocr.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_ocr.clicked.connect(self.ocrClicked)
        rowA.addWidget(self.btn_ocr)

        self.btn_copy = QToolButton()
        self.btn_copy.setText(tr("copy"))
        self.btn_copy.setProperty("textBtn", True)
        self.btn_copy.setToolTip(tr("copy") + " (Ctrl+C)")
        self.btn_copy.clicked.connect(self.copyClicked)
        rowA.addWidget(self.btn_copy)

        self.btn_copyfile = QToolButton()
        self.btn_copyfile.setText(tr("copy_file"))
        self.btn_copyfile.setProperty("textBtn", True)
        self.btn_copyfile.setToolTip(tr("copy_file_img_tip"))
        self.btn_copyfile.clicked.connect(self.copyFileClicked)
        rowA.addWidget(self.btn_copyfile)

        self.btn_save = QToolButton()
        self.btn_save.setText(tr("save"))
        self.btn_save.setProperty("textBtn", True)
        self.btn_save.setToolTip(tr("save") + " (Ctrl+S)")
        self.btn_save.clicked.connect(self.saveClicked)
        rowA.addWidget(self.btn_save)

        self.btn_cancel = QToolButton()
        self.btn_cancel.setText(tr("cancel"))
        self.btn_cancel.setProperty("textBtn", True)
        self.btn_cancel.setToolTip(tr("cancel") + " (Esc)")
        self.btn_cancel.clicked.connect(self.cancelClicked)
        rowA.addWidget(self.btn_cancel)
        # 行A 纯文字按钮统一 26px：Linux 下 QToolButton 默认仅 13px，与带图标的
        # 「编辑」按钮（固定 26）不齐（2026-10-29 UOS 实测）。
        for _btn in (
            self.btn_ocr,
            self.btn_copy,
            self.btn_copyfile,
            self.btn_save,
            self.btn_cancel,
        ):
            _btn.setFixedHeight(26)
        # 压缩多余空间到右侧：否则工具条宽度随行B变化时，行A按钮会被均分拉宽、间距变大
        rowA.addStretch(1)

        # --- 行B（展开时显示）：工具 | 撤销重做 | 颜色线宽字号 ---
        self.rowB_widget = QWidget()
        rowB = QHBoxLayout(self.rowB_widget)
        rowB.setContentsMargins(0, 0, 0, 0)
        rowB.setSpacing(4)
        self._rows.addWidget(self.rowB_widget)
        self.rowB_widget.setMaximumHeight(0)  # 初始收起；高度动画只改这一个值
        self._rowb_anim = None

        def tool_btn(kind, tip):
            b = QToolButton(objectName="t_" + kind)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setFixedSize(34, 34)
            self._group.addButton(b)
            b.clicked.connect(lambda _=False, k=kind: self._on_tool_btn(k))
            self._tool_buttons[kind] = b
            rowB.addWidget(b)
            return b

        tool_btn(TOOL_SELECT, tr("edit"))
        tool_btn(TOOL_PEN, tr("tool_pen"))
        tool_btn(TOOL_HIGHLIGHT, tr("tool_highlight"))
        tool_btn(TOOL_TEXT, tr("tool_text"))
        tool_btn(TOOL_RECT, tr("tool_rect"))
        tool_btn(TOOL_ELLIPSE, tr("tool_ellipse"))
        tool_btn(TOOL_ARROW, tr("tool_arrow"))
        tool_btn(TOOL_MOSAIC, tr("tool_mosaic"))
        tool_btn(TOOL_ERASER, tr("tool_eraser"))

        sepB = QFrame()
        sepB.setObjectName("sep")
        sepB.setFixedSize(1, 26)
        rowB.addWidget(sepB)

        self.btn_undo = QToolButton()
        self.btn_undo.setToolTip(tr("undo") + " (Ctrl+Z)")
        self.btn_undo.setFixedSize(34, 34)
        self.btn_undo.clicked.connect(self.undoClicked)
        rowB.addWidget(self.btn_undo)
        self._plain_buttons.append((self.btn_undo, "undo"))
        self.btn_redo = QToolButton()
        self.btn_redo.setToolTip(tr("redo") + " (Ctrl+Y)")
        self.btn_redo.setFixedSize(34, 34)
        self.btn_redo.clicked.connect(self.redoClicked)
        rowB.addWidget(self.btn_redo)
        self._plain_buttons.append((self.btn_redo, "redo"))

        self.btn_clear = QToolButton()
        self.btn_clear.setToolTip(tr("clear"))
        self.btn_clear.setFixedSize(34, 34)
        self.btn_clear.clicked.connect(self.clearClicked)
        rowB.addWidget(self.btn_clear)
        self._plain_buttons.append((self.btn_clear, "clear"))

        sepB2 = QFrame()
        sepB2.setObjectName("sep")
        sepB2.setFixedSize(1, 26)
        rowB.addWidget(sepB2)

        self._build_rowB_selectors(rowB, parent)

        self.set_expanded(False, animate=False)
        self.retheme(theme.current())
        theme.manager.changed.connect(self.retheme)

    def _build_rowB_selectors(self, rowB, parent):
        """行 B 的颜色芯片与四个下拉（粗细/字号/字重/字体）。

        从 __init__ 拆出（构造器曾达 202 行，宪法 §4.1 单函数 200 行上限）。
        """
        # 颜色芯片按钮 → 双列色板弹窗（左：标准色，右：色谱）
        self.btn_color = QToolButton(objectName="btnColor")
        self.btn_color.setToolTip(tr("color"))
        self.btn_color.setFixedSize(34, 34)
        self.btn_color.clicked.connect(self._open_color_popup)
        init_color = COLORS[0]
        if parent is not None:
            c = parent.cfg.get("pen_color")
            if isinstance(c, str) and QColor(c).isValid():
                # 记住上次使用的画笔颜色（pen_color 原为"只写不读"死键，
                # 2026-10-26 按用户要求接通，跨会话生效）
                init_color = c
        self._set_color_chip(init_color)
        rowB.addWidget(self.btn_color)

        self.width_combo = EdgeAwareComboBox()
        for w, key in WIDTHS:
            self.width_combo.addItem(tr(key), w)
        self.width_combo.setCurrentIndex(1)  # 默认「中」(5px)，与画布初始 line_width 一致
        self.width_combo.setFixedWidth(58)
        # 高度与 34x34 工具按钮齐平：QComboBox 默认高度随字体/样式涨到 ~38px，破坏行 B 对齐
        self.width_combo.setFixedHeight(34)
        self.width_combo.setToolTip(tr("width_hint"))
        self.width_combo.currentIndexChanged.connect(
            lambda i: self.widthChanged.emit(self.width_combo.itemData(i))
        )
        rowB.addWidget(self.width_combo)

        self.size_combo = EdgeAwareComboBox()
        for s in TEXT_SIZES:
            self.size_combo.addItem("%d px" % s, s)
        self.size_combo.setCurrentIndex(1)  # 默认 18px，与画布初始 text_size 一致
        self.size_combo.setFixedWidth(64)
        self.size_combo.setFixedHeight(34)
        self.size_combo.setToolTip(tr("text_size_hint"))
        self.size_combo.currentIndexChanged.connect(
            lambda i: self.textSizeChanged.emit(self.size_combo.itemData(i))
        )
        rowB.addWidget(self.size_combo)
        self.size_combo.hide()

        # 文字字重（粗细）：仅文字工具激活时显示
        self.weight_combo = EdgeAwareComboBox()
        for weight, key in TEXT_WEIGHTS:
            self.weight_combo.addItem(tr(key), weight)
        self.weight_combo.setCurrentIndex(1)  # 默认常规
        self.weight_combo.setFixedWidth(58)
        self.weight_combo.setFixedHeight(34)
        self.weight_combo.setToolTip(tr("text_weight_hint"))
        self.weight_combo.currentIndexChanged.connect(
            lambda i: self.textWeightChanged.emit(self.weight_combo.itemData(i))
        )
        rowB.addWidget(self.weight_combo)
        self.weight_combo.hide()

        self.font_combo = EdgeAwareFontComboBox()
        self.font_combo.setFixedWidth(170)
        self.font_combo.setFixedHeight(34)
        self.font_combo.setToolTip(tr("font_hint"))
        self.font_combo.setCurrentFont(QFont("Microsoft YaHei"))
        self.font_combo.currentFontChanged.connect(lambda f: self.fontChanged.emit(f.family()))
        rowB.addWidget(self.font_combo)
        rowB.addStretch(1)  # 同上：保持按钮间距不随工具条宽度变化
        self.font_combo.hide()

    # ---- 颜色芯片/色板弹窗 ----
    def _set_color_chip(self, hexc):
        pm = QPixmap(20, 20)
        pm.fill(QColor(hexc))
        p = QPainter(pm)
        p.setPen(QPen(QColor("#888888"), 1))
        p.drawRect(0, 0, 19, 19)
        p.end()
        self.btn_color.setIcon(QIcon(pm))
        self.btn_color._hex = hexc

    def _open_color_popup(self):
        popup = ColorPickerPopup(self.btn_color._hex)
        popup.colorLive.connect(self._on_color_picked)  # 拖动实时上色
        popup.colorSelected.connect(self._on_color_picked)  # 标准色点选后关窗
        popup.popup_below(self.btn_color)

    def _on_color_picked(self, hexc):
        self._set_color_chip(hexc)
        self.colorChanged.emit(hexc)

    # ---- OCR 激活态 ----
    def set_ocr_active(self, active):
        self.btn_ocr.setChecked(bool(active))

    # ---- 展开/收起 ----
    def set_expanded(self, exp, animate=True):
        """展开/收起编辑区。默认播放高度动画（向下展开 / 向上折叠）。

        动画只改 rowB_widget 的 maximumHeight，行A按钮位置与间距全程不受影响。
        """
        self.btn_edit.setChecked(exp)
        self._animate_rowb(bool(exp), animate)

    def _animate_rowb(self, exp, animate):
        self.rowB_widget.setVisible(True)  # 动画期间必须可见，靠 maximumHeight 收放
        full = self.rowB_widget.sizeHint().height()
        target = full if exp else 0
        start = self.rowB_widget.maximumHeight()
        if start == target:
            # 已处于目标状态：尺寸不会再变，但**选区可能刚换过**——例如拖动选区后
            # 不退出、立即重新框选，此时工具条已是展开态，原先直接 return 会让它
            # 停在旧选区的位置上（2026-10-27 用户反馈截图：选区在下方、操作栏在上方）。
            # 这里按当前（=最终）尺寸重定位一次，位置才对得上。
            p = self.parent()
            # 构造期（EditorToolbar.__init__ 里就调 set_expanded）父窗口的 toolbar
            # 还没赋值，此时不能重定位——用 "父窗口的 toolbar 就是自己" 作为就绪判据。
            if p is not None and getattr(p, "toolbar", None) is self:
                p._reposition_toolbar()
            return
        if not animate:
            self.rowB_widget.setMaximumHeight(target)
            self._on_rowb_anim_step()
            return
        if self._rowb_anim is not None:
            self._rowb_anim.stop()
        anim = QPropertyAnimation(self.rowB_widget, b"maximumHeight", self)
        anim.setDuration(EXPAND_ANIM_MS)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic if exp else QEasingCurve.InCubic)
        anim.valueChanged.connect(self._on_rowb_anim_step)
        self._rowb_anim = anim
        # 位置只需按"目标高度"定一次：动画期间高度渐变但坐标固定，才不会中途翻转或抖动
        target_total = self.height() - self.rowB_widget.height() + target
        p = self.parent()
        if p is not None and hasattr(p, "_reposition_toolbar"):
            p._reposition_toolbar(target_total)
        anim.start()

    def _on_rowb_anim_step(self):
        # 每帧同步工具条尺寸（位置由动画开始时一次性定点，期间保持不变）
        self.adjustSize()

    # ---- 撤销/重做可用态（栈空置灰，消除"按钮坏了"的误解） ----
    def set_undo_redo_enabled(self, can_undo, can_redo):
        self.btn_undo.setEnabled(bool(can_undo))
        self.btn_redo.setEnabled(bool(can_redo))

    def _on_tool_btn(self, kind):
        self.current_tool = kind
        self.toolChanged.emit(kind)

    # ---- 主题 ----
    def retheme(self, t):
        self.setStyleSheet(theme.qss_toolbar(t, "edToolbar"))
        for kind, b in self._tool_buttons.items():
            ic = {
                "select": "select",
                "pen": "pen",
                "highlight": "highlight",
                "text": "text",
                "rect": "rect",
                "ellipse": "ellipse",
                "arrow": "arrow",
                "mosaic": "mosaic",
                "eraser": "eraser",
            }[kind]
            b.setIcon(icons.dual_icon(ic, t.icon, t.on_accent))
        for btn, name in self._plain_buttons:
            btn.setIcon(icons.icon(name, t.icon))
        self.btn_edit.setIcon(icons.dual_icon("pen", t.icon, t.on_accent))
        self._set_color_chip(self.btn_color._hex)

    # ---- 状态同步 ----
    def set_tool(self, kind):
        b = self._tool_buttons.get(kind)
        if b:
            b.setChecked(True)
        self.current_tool = kind
        is_text = kind == TOOL_TEXT
        self.size_combo.setVisible(is_text)
        self.weight_combo.setVisible(is_text)
        self.font_combo.setVisible(is_text)
        self.width_combo.setVisible(not is_text)
        self.adjustSize()

    def set_color(self, hexc):
        self._set_color_chip(hexc)

    def set_width(self, w):
        vals = [x for x, _ in WIDTHS]
        i = vals.index(w) if w in vals else 1
        self.width_combo.blockSignals(True)
        self.width_combo.setCurrentIndex(i)
        self.width_combo.blockSignals(False)


def _poly(pts):
    return QPolygonF(pts)


class CanvasWidget(QWidget):
    """标注画布。绘制对象为传入的底图（截屏区域），坐标为设备像素。"""

    modified = pyqtSignal()
    stackChanged = pyqtSignal(bool, bool)  # (can_undo, can_redo) → 工具条按钮置灰

    def __init__(self, base_img: QImage, dpr: float, mosaic_block=10, parent=None):
        super().__init__(parent)
        self.base = base_img  # 物理像素, dpr=1
        self.dpr = max(dpr, 1.0)
        self.mosaic_block = max(6, int(mosaic_block))
        self.strokes = []
        self.redo_stack = []
        self.tool = None  # None=未选工具（不绘制）
        self.color = COLORS[0]
        self.line_width = 5  # 逻辑px（不可命名 width，会遮蔽 QWidget.width()）；默认适中档
        self.text_size = 18  # 逻辑px
        self.text_font = "Microsoft YaHei"  # 文字工具字体
        self.text_weight = QFont.Normal  # 文字字重（Light/Normal/Bold）
        self._current = None
        self._text_edit = None
        self._text_pos = QPointF()
        self._pixelated = None
        # 标注图层：所有笔画先画进这张透明图，橡皮擦用 CompositionMode_Clear 在层上"打洞"，
        # 因此只擦掉笔刷覆盖到的像素，而不是整条笔画（底图不受影响）。
        self._layer = None
        self._layer_valid = False
        # 拖动/缩放选区期间的笔画层累积位移（设备像素）。
        # 重建 40 笔的 _layer 实测 10.1ms/次（20 笔仅 1.2ms，非线性），
        # 每帧重建会把拖动单帧推到 ~15.6ms；改为只累积位移、平移绘制，
        # 停顿 120ms 后由 _px_timer 统一重建（边缘缺的一窄条肉眼不可见）。
        self._layer_offset = QPointF(0.0, 0.0)
        self._px_timer = QTimer(self)  # 马赛克底图重建防抖（缩放拖动时高频触发）
        self._px_timer.setSingleShot(True)
        self._px_timer.setInterval(120)
        self._px_timer.timeout.connect(self._rebuild_pixelated)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        # 马赛克底图首建走 120ms 防抖（与 set_base 同路）：4K 选区实测同步构建
        # 40.5ms，卡在 _finalize（松手→编辑态）关键路径上；延后一拍无感（§33.2 C2）
        self._px_stale = True  # True = _pixelated 与当前 base 不同步（需局部像素化兜底）
        self._px_timer.start()
        self.setFixedSize(
            QSize(int(base_img.width() / self.dpr), int(base_img.height() / self.dpr))
        )

    # ---------- 基础 ----------
    def set_base(self, img: QImage):
        """取景框语义：选区移动/缩放时替换底图（尺寸随之自适应）。"""
        self.base = img
        self.setFixedSize(QSize(int(img.width() / self.dpr), int(img.height() / self.dpr)))
        # 全图重建有 120ms 防抖（4K 选区约 40ms，拖动中每帧重建会卡）；
        # 防抖期间用 _draw_mosaic_region 对笔画包围盒做局部像素化兜底，
        # 否则马赛克会冻结在拖动起点的旧内容上（2026-10-27 举一反三发现）。
        self._px_stale = True
        self._px_timer.start()
        self.update()

    def shift_strokes(self, dx_dev: float, dy_dev: float):
        """笔画锚定屏幕位置：选区移动/缩放后按位移反向平移所有笔画。"""
        if abs(dx_dev) < 0.5 and abs(dy_dev) < 0.5:
            return
        for s in self.strokes:
            k = s["kind"]
            if k in ("pen", "highlight"):
                s["pts"] = [QPointF(p.x() + dx_dev, p.y() + dy_dev) for p in s["pts"]]
                if k == "highlight":
                    s["cache"] = None
                    s["dirty"] = True
            elif k == "shape":
                s["start"] = QPointF(s["start"].x() + dx_dev, s["start"].y() + dy_dev)
                s["end"] = QPointF(s["end"].x() + dx_dev, s["end"].y() + dy_dev)
                s["rect"].translate(dx_dev, dy_dev)
            elif k == "mosaic":
                s["path"].translate(dx_dev, dy_dev)
            elif k == "text":
                s["pos"] = QPointF(s["pos"].x() + dx_dev, s["pos"].y() + dy_dev)
        # 不立即重建 _layer（40 笔 10.1ms/次，拖动每帧重建会掉帧）：
        # 累积位移让 paintEvent 平移绘制，停顿后由 _px_timer 统一重建。
        self._layer_offset += QPointF(dx_dev, dy_dev)
        self._px_timer.start()
        self.update()

    def _ensure_layer(self):
        if self._layer is None or self._layer.size() != self.base.size():
            self._layer = QPixmap(self.base.size())
            self._layer.fill(Qt.transparent)

    def _rebuild_layer(self):
        self._ensure_layer()
        self._layer_offset = QPointF(0.0, 0.0)
        self._layer.fill(Qt.transparent)
        lp = QPainter(self._layer)
        lp.setRenderHint(QPainter.Antialiasing, True)
        for s in self.strokes:
            self._draw_stroke(lp, s)
        lp.end()

    def _draw_mosaic_region(self, p, s):
        """底图刚换、全图 `_pixelated` 还没跟上时的兜底绘制（拖动/缩放中）。

        只对本笔画的包围盒做像素化：区域通常几百像素见方，成本 1~2ms，
        远低于全图重建的 ~40ms（4K 选区）。这样拖动时马赛克能跟着底图
        正确移动，而不是冻结在拖动起点的旧内容上。

        调用点位于 `paintEvent` 的 `p.scale(1/dpr)` 之后，坐标是**设备像素**。
        """
        path = QPainterPath(s["path"])
        path.setFillRule(Qt.WindingFill)
        bbox = path.boundingRect().toAlignedRect().intersected(self.base.rect())
        if bbox.isEmpty():
            return
        block = max(2, int(self.mosaic_block))
        src = self.base.copy(bbox)
        small = src.scaled(
            max(1, bbox.width() // block),
            max(1, bbox.height() // block),
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
        tile = small.scaled(
            bbox.width(), bbox.height(), Qt.IgnoreAspectRatio, Qt.FastTransformation
        )
        p.save()
        p.setClipPath(path, Qt.IntersectClip)
        p.drawImage(bbox.topLeft(), tile)
        p.restore()

    def _rebuild_pixelated(self):
        try:
            block = self.mosaic_block
            w, h = self.base.width(), self.base.height()
            small = self.base.scaled(
                max(1, w // block),
                max(1, h // block),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
            self._pixelated = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        except Exception:
            self._pixelated = None
        self._px_stale = False
        if not self._layer_offset.isNull():
            self._rebuild_layer()  # 位移已归位：把笔画画到最终坐标上
        self.update()  # 防抖重建后重绘：首建/换底图后让马赛克笔画立即可见

    def set_tool(self, t):
        """t=None 表示未选工具（画布对鼠标透明，由遮罩处理移动）。"""
        self.tool = t
        self._commit_pending_text()
        if t is None:
            self.setCursor(Qt.ArrowCursor)
            return
        if t in (TOOL_PEN, TOOL_HIGHLIGHT, TOOL_MOSAIC):
            self._update_brush_cursor()
            return
        if t == TOOL_ERASER:
            self._update_eraser_cursor()
            return
        cur = {
            "rect": Qt.CrossCursor,
            "ellipse": Qt.CrossCursor,
            "arrow": Qt.CrossCursor,
            "text": Qt.IBeamCursor,
        }.get(t, Qt.ArrowCursor)
        self.setCursor(cur)

    def _update_brush_cursor(self):
        """画笔/涂色/马赛克：与笔刷同径的圆圈光标（双描边保证亮暗背景可见）。"""
        d = max(8, min(128, int(self.line_width)))
        pm = QPixmap(d + 2, d + 2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(1, 1, d, d)
        p.setPen(QPen(QColor(40, 40, 40), 1))
        p.drawEllipse(2, 2, d - 2, d - 2)
        p.end()
        self.setCursor(QCursor(pm, (d + 2) // 2, (d + 2) // 2))

    def _update_eraser_cursor(self):
        """橡皮擦：双圈光标——内圈=实际擦除直径（所见即所得），外圈=最小可见兜底。

        擦除直径 = 档位（细 2 / 中 5 / 粗 10 / 加粗 16）。2px 的圈在屏幕上几乎不可见，
        所以外圈固定 `max(8, 档位)` 保证可辨；**内圈始终按真实擦除直径绘制**，用户看到的
        内圈就是擦掉的范围。历史实现只有外圈（且旧口径"半径=档位"），造成细档光标
        8px、实际只擦 2px 的 4 倍偏差（第二轮审计 P2-01）。
        """
        erase_d = max(1, int(self.line_width))  # 逻辑直径 = 档位
        d = max(8, min(128, erase_d))  # 外圈（可见性兜底）
        pm = QPixmap(d + 2, d + 2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        # 外圈：白 + 深描边，亮暗背景都可辨
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(1, 1, d, d)
        p.setPen(QPen(QColor(40, 40, 40), 1))
        p.drawEllipse(2, 2, d - 2, d - 2)
        # 内圈：真实擦除直径（强调色虚线；与外圈重合时省略）
        if erase_d < d - 2:
            ed = max(2, erase_d)
            off = (d - ed) / 2.0 + 1
            accent = (getattr(self, "_t", None) or theme.current()).accent
            p.setPen(QPen(accent, 1, Qt.DashLine))
            p.drawEllipse(QRectF(off, off, ed, ed))
        p.end()
        self.setCursor(QCursor(pm, (d + 2) // 2, (d + 2) // 2))

    def dev(self, p) -> QPointF:
        return QPointF(p.x() * self.dpr, p.y() * self.dpr)

    def undo(self):
        if self.strokes:
            self.redo_stack.append(self.strokes.pop())
            self._rebuild_layer()
            self._cancel_text_edit()
            self.update()
            self.modified.emit()
        self.stackChanged.emit(bool(self.strokes), bool(self.redo_stack))

    def redo(self):
        if self.redo_stack:
            self.strokes.append(self.redo_stack.pop())
            self._rebuild_layer()
            self.update()
            self.modified.emit()
        self.stackChanged.emit(bool(self.strokes), bool(self.redo_stack))

    def clear_all(self):
        """清空全部标注（含重做栈），一次到位——不必一路 Ctrl+Z。"""
        if not self.strokes and not self.redo_stack:
            return
        self.strokes.clear()
        self.redo_stack.clear()
        self._rebuild_layer()
        self._cancel_text_edit()
        self.update()
        self.stackChanged.emit(False, False)
        self.modified.emit()

    # ---------- 绘制 ----------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        self.base.setDevicePixelRatio(self.dpr)
        p.drawImage(0, 0, self.base)
        self.base.setDevicePixelRatio(1.0)
        # 笔画/高亮缓存/马赛克底图均按设备像素存储：把画笔缩放回逻辑空间，
        # 保证实时预览的墨迹落点与指针重合（WYSIWYG）。render_to_image 为设备空间，不受影响。
        p.scale(1.0 / self.dpr, 1.0 / self.dpr)
        if self._layer is not None:
            if self._layer_offset.isNull():
                p.drawPixmap(0, 0, self._layer)
            else:
                # 拖动/缩放中：笔画层按累积位移平移绘制（松手后重建归位）
                p.drawPixmap(self._layer_offset, self._layer)
        if self._current is not None:
            self._draw_stroke(p, self._current)
        p.end()

    @staticmethod
    def _ui_font():
        # 文字工具的默认字体：Windows 用微软雅黑，Linux 信创用应用字体（Noto/文泉驿）
        if sys.platform == "win32":
            return "Microsoft YaHei"
        try:
            from PyQt5.QtWidgets import QApplication

            fam = QApplication.font().family()
            if fam:
                return fam
        except Exception:
            # 字体探测失败：返回空串由调用方用默认字体
            pass
        return "Noto Sans CJK SC"

    def _draw_stroke(self, p: QPainter, s):
        kind = s["kind"]
        if kind == "pen":
            p.setPen(QPen(QColor(s["color"]), s["width"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(_poly(s["pts"]))
        elif kind == "highlight":
            cache = s.get("cache")
            if cache is None or s.get("dirty"):
                cache = self._render_highlight(s)
                s["cache"] = cache
                s["dirty"] = False
            p.drawImage(0, 0, cache)
        elif kind == "shape":
            p.setPen(QPen(QColor(s["color"]), s["width"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            if s["shape"] == "arrow":
                self._draw_arrow(p, QPointF(s["start"]), QPointF(s["end"]))
            else:
                r = QRectF(s["rect"])
                if s["shape"] == "rect":
                    p.drawRect(r)
                elif s["shape"] == "ellipse":
                    p.drawEllipse(r)
        elif kind == "mosaic":
            if self._px_stale or self._pixelated is None:
                self._draw_mosaic_region(p, s)  # 底图刚换：局部像素化兜底
                return
            p.save()
            path = QPainterPath(s["path"])
            path.setFillRule(Qt.WindingFill)
            p.setClipPath(path, Qt.IntersectClip)
            p.drawImage(0, 0, self._pixelated)
            p.restore()
        elif kind == "text":
            f = QFont(s.get("font") or self._ui_font())
            f.setPixelSize(int(s["size"]))
            f.setWeight(int(s.get("weight", QFont.Normal)))
            p.setFont(f)
            p.setPen(QColor(s["color"]))
            lh = int(s["size"] * 1.35)
            x, y = s["pos"].x(), s["pos"].y()
            for i, line in enumerate(str(s["text"]).split("\n")):
                p.drawText(QPointF(x, y + lh * (i + 1) - int(s["size"] * 0.25)), line)

    def _render_highlight(self, s) -> QImage:
        img = QImage(self.base.size(), QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        pp = QPainter(img)
        pp.setRenderHint(QPainter.Antialiasing, True)
        c = QColor(s["color"])
        c.setAlpha(90)
        pp.setPen(QPen(c, s["width"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        pp.setBrush(Qt.NoBrush)
        pp.setCompositionMode(QPainter.CompositionMode_Source)
        pp.drawPolyline(_poly(s["pts"]))
        pp.end()
        return img

    def _draw_arrow(self, p: QPainter, p1: QPointF, p2: QPointF):
        """箭头：起点=按下点，头部实时指向 p2。样式：细杆 + 小三角头（Firefox 风）。"""

        if (p2 - p1).manhattanLength() < 2:
            return
        w = p.pen().widthF() or 4
        ang = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
        L = max(11.0, w * 2.4)  # 头长
        # 杆画到头部内侧，避免杆盖过箭头尖
        shaft_end = QPointF(p2.x() - L * 0.72 * math.cos(ang), p2.y() - L * 0.72 * math.sin(ang))
        # 杆全宽 = 档位（与其他工具笔宽严格统一；历史实现 w*0.75 使同档箭头偏细）
        shaft_pen = QPen(p.pen().color(), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(shaft_pen)
        p.drawLine(p1, shaft_end)
        a1 = QPointF(p2.x() - L * math.cos(ang - 0.38), p2.y() - L * math.sin(ang - 0.38))
        a2 = QPointF(p2.x() - L * math.cos(ang + 0.38), p2.y() - L * math.sin(ang + 0.38))
        p.setBrush(QColor(p.pen().color()))
        p.drawPolygon(QPolygonF([p2, a1, a2]))

    # ---------- 鼠标 ----------
    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        d = self.dev(ev.pos())
        if self.tool == TOOL_ERASER:
            # 橡皮擦：在标注图层上用 Clear 打洞，像真实橡皮一样只擦接触到的像素。
            # 直径 = 档位（与画笔/矩形等同宽，历史实现是"半径=档位"，擦除圈视觉上
            # 比其他工具粗一倍，违反档位统一）；_current["width"] 存的是直径。
            self._ensure_layer()
            r = max(1, int(self.line_width * self.dpr / 2))
            lp = QPainter(self._layer)
            lp.setCompositionMode(QPainter.CompositionMode_Clear)
            lp.setPen(Qt.NoPen)
            lp.setBrush(Qt.SolidPattern)
            lp.drawEllipse(d, r, r)
            lp.end()
            self._current = {"kind": "erase", "pts": [d], "width": r * 2}
            self.update()
            return
        w = max(2, int(self.line_width * self.dpr))
        if self.tool == TOOL_TEXT:
            if self._text_edit is not None:
                self._commit_text_edit()  # 点击空白处 = 提交已输入的文字
                return
            self._open_text_edit(ev.pos())
            return
        if self.tool == TOOL_PEN:
            self._current = {"kind": "pen", "pts": [d], "color": self.color, "width": w}
        elif self.tool == TOOL_HIGHLIGHT:
            # 涂色与其余工具共用同一档位宽度（严格统一）：历史上曾有 max(w, 10*dpr)
            # 下限，导致细/中/粗三档实际都是 10px、档位形同虚设（用户反馈）。
            self._current = {
                "kind": "highlight",
                "pts": [d],
                "color": self.color,
                "width": w,
            }
        elif self.tool in (TOOL_RECT, TOOL_ELLIPSE, TOOL_ARROW):
            self._current = {
                "kind": "shape",
                "shape": self.tool,
                "start": QPointF(d),
                "end": QPointF(d),
                "rect": QRectF(d, d),
                "color": self.color,
                "width": w,
            }
        elif self.tool == TOOL_MOSAIC:
            path = QPainterPath()
            path.setFillRule(Qt.WindingFill)
            path.addEllipse(d, w / 2, w / 2)
            self._current = {"kind": "mosaic", "path": path, "width": w}
        self.redo_stack.clear()

    def mouseMoveEvent(self, ev):
        if self._current is None:
            return
        d = self.dev(ev.pos())
        k = self._current["kind"]
        if k == "erase":
            self._ensure_layer()
            r = self._current["width"] / 2
            lp = QPainter(self._layer)
            lp.setCompositionMode(QPainter.CompositionMode_Clear)
            lp.setPen(Qt.NoPen)
            lp.setBrush(Qt.SolidPattern)
            lp.drawEllipse(d, r, r)
            lp.end()
            self._current["pts"].append(d)
            self.update()
            return
        if k in ("pen", "highlight"):
            pts = self._current["pts"]
            if (d - pts[-1]).manhattanLength() >= max(2, self._current["width"] / 6):
                pts.append(d)
                if k == "highlight":
                    self._current["dirty"] = True
        elif k == "shape":
            self._current["end"] = QPointF(d)
            if self._current["shape"] != "arrow":
                self._current["rect"] = QRectF(self._current["rect"].topLeft(), d).normalized()
        elif k == "mosaic":
            w = self._current["width"]
            self._current["path"].addEllipse(d, w / 2, w / 2)
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._current is None:
            return
        s = self._current
        self._current = None
        if s["kind"] == "erase":
            # 擦除只修改 layer 像素，不加入 strokes（undo 通过重建 layer 回退）
            self.modified.emit()
            return
        if s["kind"] in ("pen", "highlight") and len(s["pts"]) < 2:
            # 单击成点
            d = s["pts"][0]
            r = s["width"] / 2
            s["pts"] = [QPointF(d.x() - r, d.y()), QPointF(d.x() + r, d.y())]
        if (
            s["kind"] == "shape"
            and s["shape"] == "arrow"
            and (QPointF(s["end"]) - QPointF(s["start"])).manhattanLength() < 4
        ):
            return  # 原地单击不生成箭头
        self.strokes.append(s)
        self._ensure_layer()
        lp = QPainter(self._layer)
        lp.setRenderHint(QPainter.Antialiasing, True)
        self._draw_stroke(lp, s)
        lp.end()
        self.update()
        self.stackChanged.emit(True, False)
        self.modified.emit()

    # ---------- 文字 ----------
    def _commit_pending_text(self):
        """有输入中的文字就提交（有内容），否则丢弃空框。"""
        if self._text_edit is None:
            return
        if self._text_edit.toPlainText().strip():
            self._commit_text_edit()
        else:
            self._cancel_text_edit()

    def _open_text_edit(self, pos_l):
        self._commit_pending_text()
        size = int(self.text_size)
        e = QTextEdit(self)
        e.setObjectName("textInput")
        e.setPlaceholderText(tr("text_input_hint"))
        e.setStyleSheet(
            # 透明背景 + 虚线边框（2026-10-26 用户要求）：输入框覆盖在截图上，
            # 白底会把下方内容糊住，看不清"文字将落在哪"；只留虚线分界即可。
            # viewport 单独置透明：QTextEdit 是 QAbstractScrollArea，背景画在
            # viewport 上，只设自身 background 会留一块浅色底。
            "QTextEdit#textInput { background: transparent; color: %s;"
            " border: 1px dashed %s; font-size: %dpx; padding: 2px;"
            ' font-family: "%s"; font-weight: %d;'
            " selection-background-color: rgba(0,120,215,120); }"
            "QTextEdit#textInput > QWidget { background: transparent; }"
            # 滚动条在透明背景下是一条突兀的灰条，且输入框只有 3.4 行高，
            # 内容超出时靠光标跟随即可，不需要滚动条。
            "QTextEdit#textInput QScrollBar:vertical,"
            " QTextEdit#textInput QScrollBar:horizontal { width: 0; height: 0; }"
            % (
                self.color,
                theme.current().accent_css,
                size,
                self.text_font,
                self.text_weight,
            )
        )
        # 贴右/下缘时钳回画布内：输入框被裁掉就成了盲打（U2，实测曾 91% 不可见）
        w = min(420, max(180, self.width() - int(pos_l.x()) - 8))
        h = int(size * 3.4)
        e.setFixedWidth(w)
        e.setFixedHeight(h)
        e.move(
            min(int(pos_l.x()), max(0, self.width() - w - 4)),
            min(int(pos_l.y()), max(0, self.height() - h - 4)),
        )
        e.setFocus()
        e.installEventFilter(self)
        self._text_edit = e
        self._text_pos = self.dev(pos_l)
        e.show()

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent

        if obj is self._text_edit:
            if event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self._cancel_text_edit()
                    return True
                if (
                    event.key() in (Qt.Key_Return, Qt.Key_Enter)
                    and event.modifiers() & Qt.ControlModifier
                ):
                    self._commit_text_edit()
                    return True
            elif event.type() == QEvent.FocusOut:
                # 失焦（如点到遮罩其他位置）也提交，避免文字丢失
                self._commit_pending_text()
        return super().eventFilter(obj, event)

    def _commit_text_edit(self):
        e = self._text_edit
        if e is None:
            return
        text = e.toPlainText().rstrip()
        self._text_edit = None
        e.deleteLater()
        if text:
            s = {
                "kind": "text",
                "pos": self._text_pos,
                "text": text,
                "color": self.color,
                "font": self.text_font,
                "weight": int(self.text_weight),
                "size": int(self.text_size * self.dpr),
            }
            self.strokes.append(s)
            self._ensure_layer()
            lp = QPainter(self._layer)
            lp.setRenderHint(QPainter.Antialiasing, True)
            self._draw_stroke(lp, s)
            lp.end()
            self.stackChanged.emit(True, False)
            self.modified.emit()
        self.update()

    def _cancel_text_edit(self):
        if self._text_edit is not None:
            self._text_edit.deleteLater()
            self._text_edit = None

    def hideEvent(self, ev):
        self._commit_pending_text()
        super().hideEvent(ev)

    # ---------- 合成 ----------
    def render_to_image(self) -> QImage:
        img = QImage(self.base.size(), QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.drawImage(0, 0, self.base)
        if self._layer is not None:
            p.drawPixmap(0, 0, self._layer)
        p.end()
        return img
