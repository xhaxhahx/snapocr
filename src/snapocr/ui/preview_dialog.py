# -*- coding: utf-8 -*-
"""截图预览确认窗（借鉴 Firefox Screenshots 预览窗）：
图片 + 复制/另存/重试/取消，快捷键标注，操作期间按钮防抖禁用。"""

import os
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..i18n import tr
from ..paths import pictures_dir
from . import theme

MAX_PREVIEW_W, MAX_PREVIEW_H = 640, 420


class PreviewDialog(QWidget):
    copyDone = pyqtSignal()  # 已复制，会话结束
    saveDone = pyqtSignal()  # 已另存，会话结束
    retried = pyqtSignal()  # 重试：回到编辑
    cancelled = pyqtSignal()  # 取消：仅关闭预览

    def __init__(self, image: QImage, cfg, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        # 预览窗全是按钮（复制/另存/重试/取消），无输入法需求：禁关联避免任务栏
        # 语言栏闪现导致托盘图标位移（与遮罩同一处理，详见 overlay.py 同处注释）
        self.setAttribute(Qt.WA_InputMethodEnabled, False)
        self.image = image
        self.cfg = cfg
        self._busy = False
        self.setWindowTitle(tr("preview_title"))
        self.retheme(theme.current())
        theme.manager.changed.connect(self.retheme)

        root = QVBoxLayout(self)
        root.setObjectName("previewRoot")
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        self.title = QLabel(tr("preview_title"), objectName="previewTitle")
        self.meta = QLabel("", objectName="previewMeta")
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.meta)
        root.addLayout(head)

        scaled = self._scaled_pixmap()
        self.view = QLabel()
        self.view.setPixmap(scaled)
        self.view.setFixedSize(scaled.size())
        self.view.setObjectName("previewView")
        root.addWidget(self.view, 1)

        btns = QHBoxLayout()
        self.btn_copy = QPushButton(tr("preview_copy") + "  (Ctrl+C)", objectName="primary")
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

    # ---------- 主题 ----------
    def retheme(self, t):
        self.setStyleSheet(
            """
            #previewRoot { background: %(bg)s; }
            #previewTitle { font-size: 14px; font-weight: 600; color: %(text)s; }
            #previewMeta { font-size: 12px; color: %(sub)s; }
            #previewView { background: %(card)s; border: 1px solid %(border)s;
                           border-radius: 6px; }
            QPushButton { background: %(card)s; border: 1px solid %(border)s;
                          border-radius: 6px; padding: 6px 14px; color: %(text)s; }
            QPushButton:hover { background: %(hover)s; border: 2px solid %(accent)s;
                                padding: 5px 13px; }
            QPushButton:pressed { background: %(card)s; border: 1px solid %(accent)s;
                                  padding: 6px 14px; }
            QPushButton:disabled { color: %(sub)s; }
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

    def _scaled_pixmap(self):
        pm = QPixmap.fromImage(self.image)
        w, h = pm.width(), pm.height()
        scale = min(1.0, MAX_PREVIEW_W / max(1, w), MAX_PREVIEW_H / max(1, h))
        if scale < 1.0:
            pm = pm.scaled(
                int(w * scale), int(h * scale), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        return pm

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

    def keyPressEvent(self, ev):
        k, m = ev.key(), ev.modifiers()
        if self._busy:
            return
        ctrl = m & Qt.ControlModifier
        if k == Qt.Key_Escape:
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
