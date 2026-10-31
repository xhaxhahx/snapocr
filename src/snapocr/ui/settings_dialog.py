# -*- coding: utf-8 -*-
"""设置对话框：热键 / 启动 / 保存目录 / OCR 参数 / 语言。跟随系统主题。"""

import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import DEFAULTS
from ..i18n import tr
from . import theme
from .editor import EdgeAwareComboBox

_MOD_KEYS = {
    Qt.Key_Control,
    Qt.Key_Alt,
    Qt.Key_Shift,
    Qt.Key_Meta,
    Qt.Key_AltGr,
    Qt.Key_NumLock,
    Qt.Key_CapsLock,
}


class HotkeyEdit(QLineEdit):
    """快捷键录入框：点击后直接按键盘，按键序列实时录入（Esc 清空）。"""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText(tr("hotkey_hint"))
        if text:
            self.setText(text)

    def keyPressEvent(self, ev):
        k, m = ev.key(), int(ev.modifiers())
        if k in _MOD_KEYS or k == Qt.Key_unknown:
            # 只按了修饰键：显示半成品
            self.setText(QKeySequence(m).toString(QKeySequence.NativeText))
            return
        if k == Qt.Key_Escape and m == Qt.NoModifier:
            self.clear()
            return
        if k == Qt.Key_Backspace and m == Qt.NoModifier:
            self.clear()
            return
        if not (
            m & (int(Qt.ControlModifier) | int(Qt.AltModifier) | int(Qt.MetaModifier))
        ) and not (Qt.Key_F1 <= k <= Qt.Key_F24):
            # 无修饰键的单键（如 A）会被 RegisterHotKey/XGrabKey 接受，注册后
            # 全系统按该键即触发截屏、打字被打断，录入阶段直接拒绝（§33.1 A6）；
            # F1-F24 单键不受限。修饰键状态不吞，保持"半成品"显示。
            return
        seq = QKeySequence(k | m)
        txt = seq.toString(QKeySequence.PortableText)
        self.setText(txt)


class SettingsDialog(QWidget):
    settingsApplied = pyqtSignal(bool)  # True=截屏快捷键发生了变化

    def __init__(self, cfg, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowCloseButtonHint)
        self.cfg = cfg
        self._old_hotkey = cfg.get("hotkey")
        self.setWindowTitle(tr("settings_title"))
        self.resize(520, 580)
        self.retheme(theme.current())
        theme.manager.changed.connect(self.retheme)

        root = QVBoxLayout(self)
        root.setObjectName("settingsRoot")
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        # --- 快捷方式组（仅快捷键） ---
        g1 = QGroupBox(tr("hotkey"))
        f1 = QFormLayout(g1)
        self.hotkey_edit = HotkeyEdit(cfg.get("hotkey"))
        f1.addRow(tr("hotkey"), self.hotkey_edit)
        root.addWidget(g1)

        # --- 启动组（开机自启独立成组，不再挤在快捷键里） ---
        g0 = QGroupBox(tr("startup_group"))
        f0 = QFormLayout(g0)
        self.autostart_cb = QCheckBox(tr("autostart"))
        f0.addRow("", self.autostart_cb)
        root.addWidget(g0)

        # --- OCR 组 ---
        g2 = QGroupBox(tr("ocr_group"))
        f2 = QFormLayout(g2)
        self.cls_cb = QCheckBox(tr("use_cls"))
        f2.addRow(self.cls_cb)
        self.release_cb = QCheckBox(tr("release_after_ocr"))
        f2.addRow(self.release_cb)
        self.scale_combo = EdgeAwareComboBox()
        for v, n in [(1.0, "×1.0"), (1.5, "×1.5"), (2.0, "×2.0")]:
            self.scale_combo.addItem(n, v)
        f2.addRow(tr("small_scale"), self.scale_combo)
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 16)
        f2.addRow(tr("threads"), self.threads_spin)
        root.addWidget(g2)

        # --- 路径管理组（默认保存目录单列；2026-10-29 从"界面"组拆出）---
        g3 = QGroupBox(tr("paths_group"))
        f3 = QFormLayout(g3)
        dirrow = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText(os.path.join("~", "Pictures"))
        browse = QPushButton(tr("browse"))
        browse.clicked.connect(self._browse)
        dirrow.addWidget(self.dir_edit, 1)
        dirrow.addWidget(browse)
        f3.addRow(tr("save_dir"), dirrow)
        root.addWidget(g3)

        # --- 界面组（语言；马赛克块大小已迁至截图工具条，马赛克工具激活时出现）---
        g4 = QGroupBox(tr("ui_group"))
        f4 = QFormLayout(g4)
        self.lang_combo = EdgeAwareComboBox()
        self.lang_combo.addItem(tr("lang_default"), "")
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("English", "en")
        f4.addRow(tr("language"), self.lang_combo)
        root.addWidget(g4)

        root.addStretch(1)

        btns = QHBoxLayout()
        self.btn_reset = QPushButton(tr("restore_defaults"))
        self.btn_ok = QPushButton(tr("ok"), objectName="primary")
        self.btn_cancel = QPushButton(tr("cancel"))
        btns.addWidget(self.btn_reset)
        btns.addStretch(1)
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        root.addLayout(btns)

        self.btn_reset.clicked.connect(self._restore_defaults)
        self.btn_ok.clicked.connect(self._apply)
        self.btn_cancel.clicked.connect(self.close)

        self._reload_widgets()

    # ---------- 取值/回填 ----------
    def _reload_widgets(self):
        """把 cfg 当前值回填到各控件（初始化与"恢复默认"共用）。"""
        c = self.cfg
        self.hotkey_edit.setText(c.get("hotkey") or "")
        self.autostart_cb.setChecked(bool(c.get("autostart")))
        self.cls_cb.setChecked(bool(c.get("ocr_use_cls")))
        self.release_cb.setChecked(bool(c.get("ocr_release_after", False)))
        self.scale_combo.setCurrentIndex(
            {1.0: 0, 1.5: 1, 2.0: 2}.get(float(c.get("ocr_small_scale", 1.0)), 0)
        )
        self.threads_spin.setValue(int(c.get("ocr_threads", 0)))
        self.dir_edit.setText(c.get("save_dir") or "")
        # 马赛克块大小不再属于设置页：已迁至截图工具条（马赛克工具激活时出现）
        self.lang_combo.setCurrentIndex({"": 0, "zh": 1, "en": 2}.get(c.get("lang", ""), 0))

    def showEvent(self, ev):
        theme.apply_window_chrome(self, dark_title=theme.current().dark)
        super().showEvent(ev)

    def retheme(self, t):
        self.setStyleSheet(theme.qss_settings(t))
        # 保险：QSS 覆盖不到的原生区域（滚动条/边距）也用主题底色
        from PyQt5.QtGui import QColor, QPalette

        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(t.bg))
        pal.setColor(QPalette.Base, QColor(t.card))
        pal.setColor(QPalette.WindowText, QColor(t.text))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(
            self, tr("save_dir"), self.dir_edit.text() or os.path.expanduser("~")
        )
        if d:
            self.dir_edit.setText(d)

    def _restore_defaults(self):
        """恢复默认值：写盘并回填控件（控件即时回默认即是最好的反馈，不弹模态框）。

        开机自启**不参与**恢复默认：它由安装页选择/系统状态决定（sync_autostart_cfg
        对齐），属于装机选择而非应用偏好——用户点"恢复默认"+确定不应被悄悄关掉
        开机自启（2026-10-29 体验轮实测陷阱）。
        """
        keep_autostart = self.cfg.get("autostart")
        self.cfg.reset()
        if keep_autostart:
            self.cfg.set("autostart", True)
        self._reload_widgets()

    def _apply(self):
        # 热键允许留空 = 不启用全局快捷键（2026-10-29 需求：初始无热键，用户
        # 在设置里录入并保存后才生效；删除/清空后保存即注销）。不再回落默认值。
        new_hotkey = self.hotkey_edit.text().strip()
        hotkey_changed = new_hotkey != self._old_hotkey
        self.cfg.set("hotkey", new_hotkey)
        self.cfg.set("autostart", self.autostart_cb.isChecked())
        self.cfg.set("ocr_use_cls", self.cls_cb.isChecked())
        self.cfg.set("ocr_release_after", self.release_cb.isChecked())
        self.cfg.set("ocr_small_scale", float(self.scale_combo.currentData()))
        self.cfg.set("ocr_threads", int(self.threads_spin.value()))
        self.cfg.set("save_dir", self.dir_edit.text().strip())
        # mosaic_block 由截图工具条写入（设置页不再经手，避免两处入口互覆）
        self.cfg.set("lang", self.lang_combo.currentData() or "")
        # 语言切换即时生效（已打开窗口需各自的 retranslate，新开窗口立即跟随）
        from ..i18n import init_lang

        init_lang(self.lang_combo.currentData() or "")
        from ..platform.autostart import set_autostart

        if not set_autostart(self.autostart_cb.isChecked()):
            QMessageBox.warning(self, tr("settings_title"), tr("autostart_failed"))
        self.settingsApplied.emit(hotkey_changed)
        self.close()
