# -*- coding: utf-8 -*-
"""颜色选择：色板常量 + 饱和度/亮度方块 + 色相条 + 双列色板弹窗。

从 `ui/editor.py` 拆出（2026-10-27 全面回归）：该文件已达 1,256 行，
这三个组件与画布/工具条无耦合（只依赖 Qt 与 i18n），独立成模块后
editor.py 降到约 1,050 行，颜色选择相关改动也集中在一处。

对外只暴露 `COLORS` / `STANDARD_COLORS` / `ColorPickerPopup`；
`_SVArea` / `_HueStrip` 为内部实现细节。
"""

from PyQt5.QtCore import QPointF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr

COLORS = ["#ff3b30", "#ff9500", "#ffd60a", "#34c759", "#2f7cf6", "#af52de", "#1d1d1f", "#ffffff"]

STANDARD_COLORS = [
    *COLORS,
    "#8e8e93",
    "#a2845e",
    "#5ac8fa",
    "#ff2d55",
    "#00c7be",
    "#5e5ce6",
    "#bf5af2",
    "#64d2ff",
]


class _SVArea(QWidget):
    """饱和度/亮度渐变方块（色谱选择）。"""

    colorPicked = pyqtSignal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(132, 120)
        self._hue = 0.0
        self._sat = 1.0
        self._val = 1.0

    def set_hue(self, h):
        self._hue = h
        self.update()
        self._emit_live()

    def set_color(self, c):
        """预置当前颜色（打开色板时把光标放到实际位置，不发信号）。"""
        if not c.isValid():
            return
        h, s, v = c.hsvHueF(), c.hsvSaturationF(), c.valueF()
        self._hue = h if h >= 0 else 0.0
        self._sat = min(1.0, max(0.0, s))
        self._val = min(1.0, max(0.0, v))
        self.update()

    def current_color(self) -> QColor:
        return QColor.fromHsvF(min(0.9999, self._hue), self._sat, self._val)

    def _emit_live(self):
        self.colorPicked.emit(self.current_color())

    def paintEvent(self, ev):
        p = QPainter(self)
        for x in range(0, self.width(), 4):
            for y in range(0, self.height(), 4):
                c = QColor.fromHsvF(self._hue, min(1.0, x / self.width()), 1.0 - y / self.height())
                p.fillRect(x, y, 4, 4, c)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(Qt.NoBrush)
        cx = self._sat * self.width()
        cy = (1 - self._val) * self.height()
        p.drawEllipse(QPointF(cx, cy), 5, 5)
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawEllipse(QPointF(cx, cy), 6, 6)
        p.end()

    def mousePressEvent(self, ev):
        self._pick(ev.pos())

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.LeftButton:
            self._pick(ev.pos())

    def _pick(self, pos):
        self._sat = min(1.0, max(0.0, pos.x() / self.width()))
        self._val = min(1.0, max(0.0, 1 - pos.y() / self.height()))
        self.update()
        self._emit_live()


class _HueStrip(QWidget):
    huePicked = pyqtSignal(float)

    def __init__(self, parent=None, hue=0.0):
        super().__init__(parent)
        self.setFixedSize(16, 120)
        self._hue = min(0.9999, max(0.0, float(hue)))

    def set_hue(self, hue):
        """外部设定当前色相（打开色板时预置当前颜色，否则用户看不到位置）。"""
        self._hue = min(0.9999, max(0.0, float(hue)))
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        for y in range(0, self.height(), 2):
            p.fillRect(0, y, self.width(), 2, QColor.fromHsvF(min(0.9999, y / self.height()), 1, 1))
        # 当前色相标记：左右各一条短横线（白描边 + 黑芯，亮暗背景都可辨）
        cy = self._hue * self.height()
        p.setPen(QPen(QColor("#ffffff"), 3))
        p.drawLine(QPointF(-1, cy), QPointF(self.width() + 1, cy))
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawLine(QPointF(-1, cy), QPointF(self.width() + 1, cy))
        p.end()

    def mousePressEvent(self, ev):
        self._pick(ev.pos())

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.LeftButton:
            self._pick(ev.pos())

    def _pick(self, pos):
        self.huePicked.emit(min(0.9999, max(0.0, pos.y() / self.height())))


class ColorPickerPopup(QFrame):
    """双列色板弹窗：左列常用标准色，右列自由色谱（明度饱和度 + 色相条）。
    拖动色谱实时发 colorLive（不关窗）；点标准色发 colorSelected 并关闭。"""

    colorSelected = pyqtSignal(str)
    colorLive = pyqtSignal(str)

    def __init__(self, current, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("colorPopup")
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # 当前色：用于高亮标准色并在色谱上预置位置。此前该参数完全未使用，
        # 打开色板时用户看不到当前颜色在哪（本轮架构检查发现）。
        cur = QColor(current) if current else QColor(STANDARD_COLORS[0])
        if not cur.isValid():
            cur = QColor(STANDARD_COLORS[0])
        cur_hex = cur.name()

        grid = QGridLayout()
        grid.setSpacing(4)
        for i, hexc in enumerate(STANDARD_COLORS):
            b = QToolButton()
            b.setFixedSize(24, 24)
            pm = QPixmap(20, 20)
            pm.fill(QColor(hexc))
            p = QPainter(pm)
            p.setPen(QPen(QColor("#888888"), 1))
            p.drawRect(0, 0, 19, 19)
            p.end()
            b.setIcon(QIcon(pm))
            b.setIconSize(QSize(20, 20))
            # 当前色加白色描边（与外圈深色形成对比，深浅主题都可辨）
            if hexc.lower() == cur_hex.lower():
                b.setStyleSheet(
                    "QToolButton{border:2px solid #ffffff;border-radius:4px;"
                    "background:rgba(0,0,0,60);}"
                )
                b.setToolTip(tr("current_color"))
            b.clicked.connect(lambda _=False, hx=hexc: self._pick(hx))
            grid.addWidget(b, i % 8, i // 8)
        root.addLayout(grid)

        col2 = QVBoxLayout()
        col2.setSpacing(6)
        self._sv = _SVArea()
        self._hue = _HueStrip(hue=cur.hsvHueF() if cur.hsvHueF() >= 0 else 0.0)
        self._sv.set_color(cur)
        self._sv.colorPicked.connect(lambda c: self.colorLive.emit(c.name()))
        self._hue.huePicked.connect(self._sv.set_hue)  # 拖色相条也实时发色
        col2.addWidget(self._sv)
        col2.addWidget(self._hue)
        root.addLayout(col2)

        self.setStyleSheet("""
            #colorPopup { background: #2d3139; border: 1px solid #454b56;
                          border-radius: 8px; }
            QToolButton { background: transparent; border: 1px solid #555;
                          border-radius: 4px; }
            QToolButton:hover { border: 2px solid #ffffff; }
        """)

    def popup_below(self, anchor):
        """弹出并做靠边自适应：越右缘改与锚点右缘对齐，越下缘翻到锚点上方。

        原实现直接落在锚点左下角，锚点贴屏幕右缘时弹窗（约 380px 宽）有 107px
        溢出屏幕外（10-22 UX 报告 E-3 实测）；与工具条/放大镜的贴边翻转同策略。
        先 show 再钳制：布局激活前的 width() 是保守值（实测 97px，show 后才是
        真实 216px），按假宽度钳了也白钳。
        """
        self.adjustSize()
        self.show()
        gp = anchor.mapToGlobal(anchor.rect().bottomLeft())
        scr = QApplication.screenAt(gp) or QApplication.primaryScreen()
        ag = scr.availableGeometry()
        x, y = gp.x(), gp.y()
        if x + self.width() > ag.right() + 1:
            # 越右缘：改为与锚点右缘对齐（仍越则贴屏幕左缘）
            x = max(ag.left(), anchor.mapToGlobal(anchor.rect().topRight()).x() - self.width())
        if y + self.height() > ag.bottom() + 1:
            # 越下缘：翻到锚点上方（仍越则贴屏幕上缘）
            y = max(ag.top(), gp.y() - anchor.height() - self.height())
        # 终钳：锚点自身部分出屏等极端情况，弹窗仍完整落在屏内
        x = max(ag.left(), min(x, ag.right() - self.width() + 1))
        y = max(ag.top(), min(y, ag.bottom() - self.height() + 1))
        self.move(x, y)

    def _pick(self, color):
        c = QColor(color) if isinstance(color, str) else color
        self.colorSelected.emit(c.name())
        self.close()
