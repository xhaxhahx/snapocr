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
    QFrame,
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
        # 无边框 + 自绘标题栏：钉住按钮要放在最小化左边、与系统按钮同款——
        # 原生标题栏无法插入自定义按钮（2026-10-27 需求）
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        # 预览窗全是按钮（复制/另存/重试/取消），无输入法需求：禁关联避免任务栏
        # 语言栏闪现导致托盘图标位移（与遮罩同一处理，详见 overlay.py 同处注释）
        self.setAttribute(Qt.WA_InputMethodEnabled, False)
        self.image = image
        self.cfg = cfg
        self._busy = False
        # 钉住：会话结束后窗口仍保留（2026-10-27 需求）。不钉住时随任务结束关闭。
        self.pinned = False
        self._session_ended = False  # 会话已结束（遮罩销毁）：重试不可用
        self._drag_pos = None  # 标题栏拖动窗口的起点（全局坐标）
        self.setWindowTitle(tr("preview_title"))
        self.retheme(theme.current())
        theme.manager.changed.connect(self.retheme)

        root = QVBoxLayout(self)
        root.setObjectName("previewRoot")
        root.setContentsMargins(1, 1, 1, 1)  # 自绘边框留 1px
        root.setSpacing(0)

        # ---- 自绘标题栏：标题 | 图钉 | 最小化 | 关闭 ----
        bar_widget = QWidget(objectName="previewTitleBar")
        bar_widget.setFixedHeight(34)
        bar_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bar = QHBoxLayout(bar_widget)
        bar.setContentsMargins(12, 0, 0, 0)
        bar.setSpacing(0)
        self.title = QLabel(tr("preview_title"), objectName="previewTitle")
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)  # 拖动窗口需要
        bar.addWidget(self.title)
        bar.addStretch(1)
        self.meta = QLabel("", objectName="previewMeta")
        self.meta.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.meta.setStyleSheet("margin-right: 10px;")
        bar.addWidget(self.meta)
        self.btn_pin = QPushButton(objectName="titleBtn")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip(tr("pin_tip"))
        self.btn_pin.toggled.connect(self._on_pin_toggled)
        bar.addWidget(self.btn_pin)
        self.btn_min = QPushButton(objectName="titleBtn")
        self.btn_min.setToolTip(tr("minimize"))
        self.btn_min.clicked.connect(self._minimize_or_finish)
        bar.addWidget(self.btn_min)
        self.btn_close = QPushButton(objectName="titleBtn")
        self.btn_close.setToolTip(tr("close"))
        self.btn_close.clicked.connect(self.close)
        bar.addWidget(self.btn_close)
        self._update_title_icons()
        root.addWidget(bar_widget)

        # 标题栏与内容的分隔线
        sep = QFrame(objectName="titleSep")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        body = QVBoxLayout()
        body.setContentsMargins(13, 11, 13, 11)
        body.setSpacing(8)

        # 画布自适应窗口（Expanding），最小尺寸沿用旧行为的初始大小；
        # 图片由 PreviewCanvas 按"保持纵横比 + 左上锚点"绘制，支持滚轮缩放与拖动。
        self.view = PreviewCanvas(self.image)
        self.view.setMinimumSize(*self._initial_view_size())
        body.addWidget(self.view, 1)

        btns = QHBoxLayout()
        self.btn_copy = QPushButton(tr("preview_copy") + "  (Ctrl+C)", objectName="primary")
        self.btn_file = QPushButton(tr("copy_as_jpg"))
        self.btn_save = QPushButton(tr("preview_save"))
        self.btn_retry = QPushButton(tr("preview_retry"))
        self.btn_cancel = QPushButton(tr("preview_cancel"))
        for b in (self.btn_copy, self.btn_file, self.btn_save, self.btn_retry, self.btn_cancel):
            btns.addWidget(b)
        body.addLayout(btns)
        root.addLayout(body)

        self.btn_copy.clicked.connect(self._copy)
        self.btn_file.clicked.connect(self._copy_as_file)
        self.btn_save.clicked.connect(self._save)
        self.btn_retry.clicked.connect(self._retry)
        self.btn_cancel.clicked.connect(self._cancel)

    # ---------- 主题 ----------
    def retheme(self, t):
        self.setStyleSheet(
            """
            #previewRoot { background: %(bg)s; border: 1px solid %(border)s; }
            #previewTitleBar { background: %(bg)s; }
            #previewTitle { font-size: 14px; font-weight: 600; color: %(text)s; }
            #previewMeta { font-size: 12px; color: %(sub)s; }
            #titleSep { background: %(border)s; }
            #previewView { background: %(card)s; border: 1px solid %(border)s;
                           border-radius: 6px; }
            QPushButton { background: %(card)s; border: 1px solid %(border)s;
                          border-radius: 6px; padding: 6px 14px; color: %(text)s; }
            QPushButton:hover { background: %(hover)s; border: 2px solid %(accent)s;
                                padding: 5px 13px; }
            QPushButton:pressed { background: %(card)s; border: 1px solid %(accent)s;
                                  padding: 6px 14px; }
            QPushButton:disabled { color: %(sub)s; }
            /* 标题栏按钮：无边框方块、悬停变色，与系统标题栏按钮同款；
               图钉钉住态整钮变强调色 */
            QPushButton#titleBtn { background: transparent; border: none; border-radius: 0;
                                   padding: 0; }
            QPushButton#titleBtn { min-width: 46px; max-width: 46px; min-height: 34px;
                                   max-height: 34px; }
            QPushButton#titleBtn:hover { background: %(hover)s; border: none; padding: 0; }
            QPushButton#titleBtn:pressed { background: %(border)s; border: none; padding: 0; }
            QPushButton#titleBtn:checked { background: %(accent)s; border: none; padding: 0; }
            QPushButton#primary { background: %(accent)s; border: 1px solid transparent;
                                  color: %(on_acc)s; font-weight: 600; }
            QPushButton#primary:hover { background: %(accent_h)s; border: 2px solid %(accent)s;
                                        padding: 5px 13px; }
        """
            % {
                "bg": t.bg,
                "card": t.card,
                "text": t.text,
                "sub": t.subtext,
                "border": t.border,
                "hover": t.hover,
                "accent": t.accent_css,
                "accent_h": t.accent_hover,
                "on_acc": t.on_accent,
            }
        )
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
        self.pinned = bool(pinned)
        self.btn_pin.setToolTip(tr("unpin_tip") if self.pinned else tr("pin_tip"))
        self._update_title_icons()

    def _minimize_or_finish(self):
        """点最小化 = 结束截图会话（遮罩/画布回收）：钉住窗保留在屏上，未钉住则关闭。

        不做真最小化——无边框窗最小化后没有任务栏按钮且遮罩会挡住桌面（2026-10-28
        GUI 实测），用户会被困在暗化屏幕外；结束会话与钉住语义一致。
        两种情况都发 finished（宿主按 pinned 决定预览窗去留，见 overlay._on_preview_finished）。"""
        self.finished.emit()

    def _update_title_icons(self):
        """重画三个标题栏图标（图钉/最小化/关闭）——用当前主题色。

        钉住态：按钮底变强调色，图钉图标改用 on_accent（强调色上的可读色），
        否则同色图标在蓝底上不可见（2026-10-27 GUI 实测发现）。
        retheme 在 __init__ 早期（按钮创建前）也会被调：hasattr 守卫跳过。"""
        if not hasattr(self, "btn_pin"):
            return
        from PyQt5.QtGui import QIcon

        from .icons import pixmap as _icon_pm

        t = theme.current()
        self.btn_pin.setIcon(QIcon(_icon_pm("pin", t.on_accent if self.pinned else t.icon)))
        self.btn_min.setIcon(QIcon(_icon_pm("minimize", t.icon)))
        self.btn_close.setIcon(QIcon(_icon_pm("close_line", t.icon)))

    def mousePressEvent(self, ev):
        # 标题栏区域（顶部 40px 内且不在按钮上）按下 → 开始拖动窗口
        if ev.button() == Qt.LeftButton and ev.pos().y() <= 40:
            w = self.childAt(ev.pos())
            if not isinstance(w, QPushButton):
                self._drag_pos = ev.globalPos() - self.frameGeometry().topLeft()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_pos is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPos() - self._drag_pos)
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._drag_pos = None
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        # 双击标题栏 = 切换最大化（与系统标题栏习惯一致）
        if ev.pos().y() <= 40 and not isinstance(self.childAt(ev.pos()), QPushButton):
            self.showNormal() if self.isMaximized() else self.showMaximized()
            return
        super().mouseDoubleClickEvent(ev)

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
        elif k == Qt.Key_C and ctrl:
            self._copy()
        elif k == Qt.Key_S and ctrl:
            self._save()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self._copy()
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
