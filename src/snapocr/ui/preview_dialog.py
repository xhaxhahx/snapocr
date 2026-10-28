# -*- coding: utf-8 -*-
"""截图预览确认窗（借鉴 Firefox Screenshots 预览窗）：
图片 + 复制/另存/重试/取消，快捷键标注，操作期间按钮防抖禁用。"""

import os
import time

from PyQt5.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..paths import pictures_dir
from . import theme

MAX_PREVIEW_W, MAX_PREVIEW_H = 640, 420


class PreviewCanvas(QWidget):
    """预览图画布：滚轮缩放 + 图片超出可视区时左键拖动。

    绘制规则（对应 2026-10-27 的需求验收点）：

    - **适配窗口时保持原始纵横比**：基准缩放取 `min(视口宽/图宽, 视口高/图高)`（contain）；
    - **锚点在左上角**：图片左上角对齐视口左上角，不居中——这样缩放/调整窗口时
      内容不会左右跳动；
    - **滚轮以图片为对象缩放**：`zoom` 是相对"适配尺寸"的倍数，范围 [1, 8]，
      `zoom=1` 即刚好适配；放大后超出部分可拖动查看；
    - **窗口尺寸变化时图片跟随**：`zoom=1` 时始终重新适配；放大态下保持缩放倍数，
      只把拖动偏移 clamp 回合法范围（不会出现"拖丢了看不到图"）。
    """

    MIN_ZOOM = 1.0
    MAX_ZOOM = 8.0
    WHEEL_STEP = 1.15

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self._img = image
        self._zoom = self.MIN_ZOOM
        self._offset = QPoint(0, 0)
        self._drag_from = None  # 拖动起点（相对图片左上角的偏移）
        # 缩放结果缓存：scaled() 实测 1080p 4.6ms、4K 22.5ms，每帧重算会让拖动
        # 掉到 45fps 以下（4K 甚至 22ms/帧）。缓存键 = 绘制尺寸 + zoom，
        # 拖动/重绘命中缓存，只有滚轮与窗口尺寸变化才重算一次。
        self._cache_key = None
        self._cache_img = None
        self.setObjectName("previewView")
        # QSS 的 background/border 只对"样式化背景"生效，自定义 QWidget 必须显式开启
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(120, 80)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

    # ---------- 几何 ----------
    def _fit_scale(self) -> float:
        iw, ih = self._img.width(), self._img.height()
        if iw <= 0 or ih <= 0 or self.width() <= 0 or self.height() <= 0:
            return 1.0
        return min(self.width() / iw, self.height() / ih)

    def draw_size(self) -> QSize:
        s = self._fit_scale() * self._zoom
        return QSize(max(1, int(self._img.width() * s)), max(1, int(self._img.height() * s)))

    def _can_pan(self) -> bool:
        d = self.draw_size()
        return d.width() > self.width() or d.height() > self.height()

    def _clamp_offset(self):
        d = self.draw_size()
        min_x = min(0, self.width() - d.width())
        min_y = min(0, self.height() - d.height())
        self._offset.setX(max(min_x, min(0, self._offset.x())))
        self._offset.setY(max(min_y, min(0, self._offset.y())))
        self._update_cursor()

    def _update_cursor(self):
        if self._drag_from is not None:
            self.setCursor(Qt.ClosedHandCursor)
        else:
            self.setCursor(Qt.OpenHandCursor if self._can_pan() else Qt.ArrowCursor)

    # ---------- 绘制 ----------
    def _render_image(self) -> QImage:
        """按当前绘制尺寸取（或重算）缩放后的图；拖动/重绘走缓存。"""
        d = self.draw_size()
        key = (d.width(), d.height(), self._zoom)
        if key != self._cache_key:
            self._cache_key = key
            self._cache_img = self._img.scaled(d, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return self._cache_img

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self._zoom < 4.0)
        p.drawImage(self._offset, self._render_image())
        p.end()

    # ---------- 交互 ----------
    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        if not delta:
            return
        step = self.WHEEL_STEP if delta > 0 else 1.0 / self.WHEEL_STEP
        new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom * step))
        if abs(new_zoom - self._zoom) < 1e-4:
            ev.accept()
            return
        self._zoom = new_zoom
        self._clamp_offset()
        self.update()
        ev.accept()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._can_pan():
            self._drag_from = ev.pos() - self._offset
            self._update_cursor()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_from is not None:
            self._offset = ev.pos() - self._drag_from
            self._clamp_offset()
            self.update()
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._drag_from is not None:
            self._drag_from = None
            self._update_cursor()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def resizeEvent(self, ev):
        # zoom=1 时 draw_size 跟着视口走（自动重新适配）；放大态只需把偏移收回合法范围
        self._clamp_offset()
        super().resizeEvent(ev)


class PreviewDialog(QWidget):
    copyDone = pyqtSignal()  # 已复制，会话结束
    saveDone = pyqtSignal()  # 已另存，会话结束
    finished = pyqtSignal()  # 最小化按钮：结束会话（宿主按 pinned 决定预览窗去留）
    retried = pyqtSignal()  # 重试：回到编辑
    cancelled = pyqtSignal()  # 取消：仅关闭预览
    closed = pyqtSignal()  # 窗口已关闭（钉住态关闭后宿主需重新判定进程去留）

    def __init__(self, image: QImage, cfg, parent=None):
        # 原生标题栏（不用 Frameless）：系统自带最小化/最大化/关闭，明暗主题随
        # `theme.apply_window_chrome` 一并适配——与 OCR 结果窗一致的窗口外观
        # （2026-10-28 用户要求"照搬结果窗的颜色与边框逻辑，标题栏要有最大化"）。
        # 置顶只在未钉住时生效：钉住 ≠ 总在最前，见 _on_pin_toggled。
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        # 预览窗全是按钮（复制/另存/重试/取消），无输入法需求：禁关联避免任务栏
        # 语言栏闪现导致托盘图标位移（与遮罩同一处理，详见 overlay.py 同处注释）
        self.setAttribute(Qt.WA_InputMethodEnabled, False)
        self.image = image
        self.cfg = cfg
        self._busy = False
        # 钉住：会话结束后窗口仍保留（2026-10-27 需求）。不钉住时随任务结束关闭。
        self.pinned = False
        self._session_ended = False  # 会话已结束（遮罩销毁）：重试不可用
        self.setWindowTitle(tr("preview_title"))
        self.retheme(theme.current())
        theme.manager.changed.connect(self.retheme)

        # 与 OCR 结果窗同构：根布局（#resultRoot）+ 标题行 + 内容 + 按钮行，
        # 直接复用 theme.qss_result 的颜色/边框规则，明暗主题自动跟随。
        root = QVBoxLayout(self)
        root.setObjectName("resultRoot")
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        self.title = QLabel(tr("preview_title"), objectName="resultTitle")
        self.meta = QLabel("", objectName="resultMeta")
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.meta)
        # 图钉：钉住 = 不随截图任务关闭；与"总在最前"无关（用户澄清）
        self.btn_pin = QPushButton(objectName="pinBtn")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip(tr("pin_tip"))
        self.btn_pin.toggled.connect(self._on_pin_toggled)
        head.addWidget(self.btn_pin)
        root.addLayout(head)

        # 画布自适应窗口（Expanding），最小尺寸沿用旧行为的初始大小；
        # 图片由 PreviewCanvas 按"保持纵横比 + 左上锚点"绘制，支持滚轮缩放与拖动。
        self.view = PreviewCanvas(self.image)
        self.view.setMinimumSize(*self._initial_view_size())
        root.addWidget(self.view, 1)

        btns = QHBoxLayout()
        # 与 OCR 结果窗的「复制文本」同款普通按钮：不加 primary 强调色，
        # 文字也不带快捷键后缀（2026-10-28 用户要求"只要复制图片这4个字"）
        self.btn_copy = QPushButton(tr("preview_copy"))
        self.btn_file = QPushButton(tr("copy_as_jpg"))
        self.btn_save = QPushButton(tr("preview_save"))
        self.btn_retry = QPushButton(tr("preview_retry"))
        self.btn_cancel = QPushButton(tr("preview_cancel"))
        for b in (self.btn_copy, self.btn_file, self.btn_save, self.btn_retry, self.btn_cancel):
            btns.addWidget(b)
        root.addLayout(btns)

        self.btn_copy.clicked.connect(self._copy)
        self.btn_file.clicked.connect(self._copy_as_file)
        self.btn_save.clicked.connect(self._save)
        self.btn_retry.clicked.connect(self._retry)
        self.btn_cancel.clicked.connect(self._cancel)

    def retheme(self, t):
        """照搬 OCR 结果窗的配色与边框（`theme.qss_result`）并同步窗口调色板。

        结果窗用的是「统一样式表 + QPalette + setAutoFillBackground」三件套：
        样式表管控件外观，调色板管原生绘制部分（背景/文字），缺一在明暗切换时
        都会留下浅色块（2026-10-28 用户要求"颜色与边框逻辑照搬结果窗"）。
        """
        from PyQt5.QtGui import QColor, QPalette

        extra = """
#pinBtn { padding: 4px 12px; font-size: 12px; }
#pinBtn:checked { background: %(accent)s; border: 1px solid transparent;
                  color: %(on_acc)s; font-weight: 600; }
#previewView { background: %(card)s; border: 1px solid %(border)s; border-radius: 8px; }
""" % {
            "accent": t.accent_css,
            "on_acc": t.on_accent,
            "card": t.card,
            "border": t.border,
        }
        self.setStyleSheet(theme.qss_result(t) + extra)
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(t.bg))
        pal.setColor(QPalette.Base, QColor(t.card))
        pal.setColor(QPalette.WindowText, QColor(t.text))
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        self._update_title_icons()

    def _initial_view_size(self):
        """初始视口尺寸：按 MAX_PREVIEW_W/H 等比适配（预览窗初始大小沿用旧行为）。"""
        iw, ih = self.image.width(), self.image.height()
        if iw <= 0 or ih <= 0:
            return MAX_PREVIEW_W, MAX_PREVIEW_H
        scale = min(1.0, MAX_PREVIEW_W / iw, MAX_PREVIEW_H / ih)
        return max(120, int(iw * scale)), max(80, int(ih * scale))

    # ---------- 钉住 ----------
    def set_session_ended(self):
        """会话已结束（遮罩已销毁）：禁用「重试」——它无法回到编辑器，点了只会关窗。

        钉住窗的寿命长于遮罩，用户可能在会话结束后才去点按钮；不禁用会让
        "重试"看起来可用却只是把窗口关掉（2026-10-28 行为测试发现）。
        """
        self._session_ended = True
        self.btn_retry.setEnabled(False)
        self.btn_retry.setToolTip(tr("retry_unavailable"))

    def _on_pin_toggled(self, pinned):
        """钉住 = 不随截图任务关闭窗口，**不等于总在最前**（2026-10-28 用户澄清）。

        钉住后取消 `WindowStaysOnTopHint`，否则它一直压在别的窗口上；未钉住时仍
        置顶——那时它是截图流程的一部分，需要浮在遮罩之上。setWindowFlag 会让
        Qt 隐藏窗口，因此随后必须重新 show。
        """
        self.pinned = bool(pinned)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, not self.pinned)
        self.show()
        self.btn_pin.setToolTip(tr("unpin_tip") if self.pinned else tr("pin_tip"))
        self._update_title_icons()

    def _update_title_icons(self):
        """重画图钉图标：钉住态用强调色上的可读色（否则同色图标在蓝底上不可见）。"""
        if not hasattr(self, "btn_pin"):
            return
        from PyQt5.QtGui import QIcon

        from .icons import pixmap as _icon_pm

        t = theme.current()
        self.btn_pin.setIcon(QIcon(_icon_pm("pin", t.on_accent if self.pinned else t.icon)))

    def closeEvent(self, ev):
        """关闭时通知宿主：钉住态下窗口关闭后，once 模式需要重新判定是否退出进程。

        直接调 app 上的钩子而不是只发信号——钉住窗的寿命长于 OverlayWindow，
        会话结束后遮罩已销毁、其信号连接随之失效，只靠 `closed` 信号会让
        "关掉钉住窗后进程不退出"（2026-10-28 实测）。
        """
        self.closed.emit()
        hook = getattr(QApplication.instance(), "on_preview_closed", None)
        if callable(hook):
            hook()
        super().closeEvent(ev)

    # ---------- 展示 ----------
    def show_near(self, screen):
        self.meta.setText("%d × %d" % (self.image.width(), self.image.height()))
        sr = screen.availableGeometry()
        g = self.frameGeometry()
        x = sr.left() + (sr.width() - g.width()) // 2
        y = sr.top() + (sr.height() - g.height()) // 2
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.btn_copy.setFocus()
        theme.apply_window_chrome(self, dark_title=theme.current().dark)

    # ---------- 动作（防抖） ----------
    def _set_busy(self, busy):
        self._busy = busy
        for b in (self.btn_copy, self.btn_file, self.btn_save, self.btn_retry, self.btn_cancel):
            b.setEnabled(not busy)
        # 会话结束后重试始终不可用：否则任何一次动作（复制/另存）结束时的
        # 解除忙碌都会把它重新启用，用户点了只会关窗（2026-10-28 行为测试发现）
        if self._session_ended:
            self.btn_retry.setEnabled(False)

    def keyPressEvent(self, ev):
        k, m = ev.key(), ev.modifiers()
        if self._busy:
            return
        ctrl = m & Qt.ControlModifier
        if k == Qt.Key_Escape:
            # 钉住态：Esc **不关窗**（docs/03 §4：Esc / 右键取消 / 操作按钮都不会杀掉
            # 钉住的窗口）。「取消」按钮仍会关闭——那是用户明确的关闭意图，
            # 与 Esc 的"退出当前操作"语义不同，所以两者不能共用 _cancel。
            if self.pinned:
                self.btn_copy.setFocus()
                return
            self._cancel()
        elif k == Qt.Key_S and ctrl:
            self._save()
        else:
            super().keyPressEvent(ev)

    def _copy(self):
        if self._busy:
            return
        self._set_busy(True)
        from . import clipboard as clip

        ok = clip.set_image(self.image)
        self._set_busy(False)
        if ok:
            self.copyDone.emit()
        else:
            # 剪贴板被占用：留在预览窗并如实报错，不再假装复制成功
            self.meta.setText(tr("copy_failed"))

    def _copy_as_file(self):
        """把预览图复制为 JPG 文件到剪贴板（弹窗输入文件名，默认同保存默认名）。"""
        if self._busy:
            return
        from . import clipboard as clip

        text = clip.ask_filename(self, "default_filename_jpg")
        if text is None:
            return
        self._set_busy(True)
        path = clip.copy_image_as_file(self.image, text)
        self._set_busy(False)
        if path:
            self.copyDone.emit()  # 与「复制」同语义：成功即结束会话
        else:
            self.meta.setText(tr("copy_file_failed", text.strip()))

    def _save(self):
        if self._busy:
            return

        default_dir = (self.cfg.get("save_dir") if self.cfg else "") or pictures_dir()
        name = tr("default_filename") % time.strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("preview_save"), os.path.join(default_dir, name), "PNG (*.png);;JPEG (*.jpg)"
        )
        if not path:
            return
        self._set_busy(True)
        if path.lower().endswith((".jpg", ".jpeg")):
            ok = self.image.save(path, "JPG", 90)  # 默认 75% 偏糊，显式提到 90%
        else:
            ok = self.image.save(path)
        self._set_busy(False)
        if ok:
            if self.cfg:
                self.cfg.set("save_dir", os.path.dirname(path))
            self.saveDone.emit()
        else:
            self.meta.setText(tr("save_failed", path))
            QTimer.singleShot(
                2500,
                lambda: self.meta.setText("%d × %d" % (self.image.width(), self.image.height())),
            )

    def _retry(self):
        if self._busy:
            return
        self.retried.emit()
        self.close()

    def _cancel(self):
        if self._busy:
            return
        self.cancelled.emit()
        self.close()
