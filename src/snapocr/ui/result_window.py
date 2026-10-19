# -*- coding: utf-8 -*-
"""OCR 结果窗口：可编辑文本、复制、另存、重新识别。"""

import os
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..utils.logger import get_logger
from . import theme

log = get_logger()

# 换行方式：结果窗内一键循环切换，默认「原图换行」（见 docs/03 §5）
WRAP_JOIN = "join"  # 整段：不按符号换行，全部连成一段
WRAP_SENTENCE = "sentence"  # 按句换行：句末标点后断行
WRAP_ORIGINAL = "original"  # 原图换行：每个识别框一行，保持截图排版
WRAP_ORDER = (WRAP_JOIN, WRAP_SENTENCE, WRAP_ORIGINAL)

# 中文句末标点一律断行；英文半角需后接空白/结尾，避免把 1.5、v1.2 拆开
_SENT_END_CJK = "。！？；…"
_SENT_END_ASCII = "!?;"


def _join_all(lines):
    """把多行拼成一整段。

    补空格的两种情况（避免"张Screenshot"这种粘连）：
    1. 两侧都是 ASCII 字母数字（英文词之间）；
    2. 一侧是中文、另一侧是 ASCII 字母数字（中英边界）。
    中文与中文之间直接相连，中文标点后也不补空格。
    """
    out = ""
    for ln in lines:
        s = str(ln).strip()
        if not s:
            continue
        if out:
            prev, cur = out[-1], s[0]
            prev_latin = prev.isascii() and prev.isalnum()
            cur_latin = cur.isascii() and cur.isalnum()
            need_space = (cur_latin and not prev.isspace()) or (prev_latin and not cur.isascii())
            if need_space:
                out += " "
        out += s
    return out


def _split_sentences(text):
    """按句末标点切分（标点保留在句尾）。"""
    out, buf = [], ""
    for i, ch in enumerate(text):
        buf += ch
        nxt = text[i + 1] if i + 1 < len(text) else ""
        is_end = (
            ch in _SENT_END_CJK
            or ch in _SENT_END_ASCII
            or (ch == "." and (not nxt or nxt.isspace()))
        )
        if is_end:
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return [s for s in out if s]


def apply_wrap(lines, mode):
    """按换行方式把识别行重排为展示行。空行一律丢弃。"""
    raw = [str(x).strip() for x in lines]
    raw = [s for s in raw if s]
    if mode == WRAP_ORIGINAL:
        return raw
    text = _join_all(raw)
    if not text:
        return []
    if mode == WRAP_SENTENCE:
        return _split_sentences(text) or [text]
    return [text]


class ResultWindow(QWidget):
    rerunRequested = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, cfg=None, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        # 与遮罩同理：窗口本身无输入法需求（按钮/标题），禁用输入法关联避免任务栏
        # 语言栏闪现导致托盘图标位移；可编辑文本区单独显式启用（见 self.text）。
        self.setAttribute(Qt.WA_InputMethodEnabled, False)
        self.cfg = cfg
        self.setWindowTitle(tr("ocr_result"))
        self.resize(480, 400)
        self.retheme(theme.current())
        theme.manager.changed.connect(self.retheme)
        self._results = []
        self._stream_lines = []  # 流式输出期间已到达的文本行（原始，未重排）
        self._wrap_mode = WRAP_ORIGINAL  # 默认「原图换行」：保持截图原本的排版
        self._elapsed = None

        root = QVBoxLayout(self)
        root.setObjectName("resultRoot")
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        head = QHBoxLayout()
        self.title = QLabel(tr("ocr_result"), objectName="resultTitle")
        self.meta = QLabel("", objectName="resultMeta")
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.meta)
        root.addLayout(head)

        self.text = QPlainTextEdit()
        # 结果文本可编辑：本控件单独保留输入法（窗口层已禁，需要处显式开）
        self.text.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.text.setPlaceholderText(tr("ocr_busy"))
        f = QFont("Microsoft YaHei")
        f.setStyleHint(QFont.SansSerif)
        self.text.setFont(f)
        root.addWidget(self.text, 1)

        btns = QHBoxLayout()
        self.btn_copy = QPushButton(tr("ocr_copy_text"))
        self.btn_save = QPushButton(tr("ocr_save_txt"))
        self.btn_wrap = QPushButton("")
        self.btn_wrap.setToolTip(tr("wrap_hint"))
        self.btn_rerun = QPushButton(tr("ocr_retry"))
        self.btn_close = QPushButton(tr("close"))
        btns.addWidget(self.btn_copy)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_wrap)
        btns.addStretch(1)
        btns.addWidget(self.btn_rerun)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        self._sync_wrap_button()
        self.btn_copy.clicked.connect(self.copy_text)
        self.btn_save.clicked.connect(self.save_txt)
        self.btn_wrap.clicked.connect(self.cycle_wrap)
        self.btn_rerun.clicked.connect(self.rerunRequested)
        self.btn_close.clicked.connect(self.close)

        # 轻提示（复制/保存结果反馈）：浮在文本区下沿，不挡鼠标
        self._toast = QLabel(self)
        self._toast.setObjectName("resultToast")
        self._toast.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._toast.hide()

    # ---------- 轻提示 ----------
    def _pop_toast(self, text, msec=1600):
        """在窗口内弹一条短提示（复制成功/失败、保存结果）。"""
        self._toast.setText(text)
        self._position_toast()
        self._toast.show()
        self._toast.raise_()
        QTimer.singleShot(msec, self._toast.hide)

    def _position_toast(self):
        self._toast.adjustSize()
        x = max(8, (self.width() - self._toast.width()) // 2)
        y = max(8, self.height() - self._toast.height() - 54)  # 悬浮在按钮行上方
        self._toast.move(x, y)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._toast.isVisible():
            self._position_toast()

    # ---------- 状态 ----------
    def set_busy(self, elapsed=None):
        """elapsed 非空表示引擎刚加载完成，把冷启动的等待讲清楚（避免"以为卡死"）。"""
        self.meta.setText(
            tr("ocr_model_loaded", elapsed) if elapsed is not None else tr("ocr_running")
        )
        self.text.setPlainText("")
        self.text.setPlaceholderText(tr("ocr_busy"))
        self.btn_copy.setEnabled(False)
        self.btn_save.setEnabled(False)

    # ---------- 换行方式 ----------
    def _raw_lines(self):
        """当前可用的原始识别行：流式期间用已到达的行，终态用完整结果。"""
        if self._stream_lines:
            return list(self._stream_lines)
        return [r[0] for r in self._results]

    def _render_text(self):
        """按当前换行方式重绘文本区，返回实际展示的行。"""
        lines = apply_wrap(self._raw_lines(), self._wrap_mode)
        self.text.setPlainText("\n".join(lines))
        return lines

    def _sync_wrap_button(self):
        """按钮名固定为「格式化换行」，当前态与下一次切换目标放在 tooltip 里。"""
        labels = {
            WRAP_JOIN: tr("wrap_join"),
            WRAP_SENTENCE: tr("wrap_sentence"),
            WRAP_ORIGINAL: tr("wrap_original"),
        }
        idx = WRAP_ORDER.index(self._wrap_mode)
        cur = labels[self._wrap_mode]
        nxt = labels[WRAP_ORDER[(idx + 1) % len(WRAP_ORDER)]]
        self.btn_wrap.setText(tr("wrap_button"))
        self.btn_wrap.setToolTip(tr("wrap_hint", cur, nxt))

    def cycle_wrap(self):
        """原图换行 → 整段 → 按句换行 → 原图换行，循环切换并立即重绘。"""
        idx = WRAP_ORDER.index(self._wrap_mode)
        self._wrap_mode = WRAP_ORDER[(idx + 1) % len(WRAP_ORDER)]
        self._sync_wrap_button()
        if not (self._results or self._stream_lines):
            return
        lines = self._render_text()
        if self._elapsed is not None:
            self.meta.setText(
                tr("ocr_lines", len(lines), sum(len(t) for t in lines), self._elapsed)
            )

    # ---------- 流式反馈 ----------
    def begin_stream(self):
        """进入流式态：清空文本，提示"正在定位"（此阶段 det 尚未完成，无文字可显示）。"""
        self._stream_lines = []
        self._results = []
        self._elapsed = None
        self.text.setPlainText("")
        self.text.setPlaceholderText(tr("ocr_locating"))
        self.meta.setText(tr("ocr_locating"))
        self.btn_copy.setEnabled(False)
        self.btn_save.setEnabled(False)

    def stream_found(self, total):
        """det 完成：告知用户"找到了多少处文字"，把最长的一段静默等待讲清楚。"""
        if total <= 0:
            self.meta.setText(tr("ocr_empty"))
            self.text.setPlaceholderText(tr("ocr_empty"))
            return
        self.meta.setText(tr("ocr_found", total))
        self.text.setPlaceholderText(tr("ocr_running"))

    def stream_line(self, text, done, total):
        """收到一条识别结果：追加并按当前换行方式重绘（与终态同一套规则，结束时不会跳变）。"""
        self._stream_lines.append(text)
        self._render_text()
        self.meta.setText(tr("ocr_progress", done, total))
        # 跟随到底部，让新出现的一行始终可见
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def set_results(self, results, elapsed):
        """results: [(text, score, box), ...] 按阅读顺序。终态以本方法为准。"""
        self._results = results
        self._stream_lines = []  # 终态用完整结果，避免与流式缓存重复
        self._elapsed = elapsed
        texts = self._render_text()
        nchars = sum(len(t) for t in texts)
        self.meta.setText(tr("ocr_lines", len(texts), nchars, elapsed))
        self.btn_copy.setEnabled(bool(texts))
        self.btn_save.setEnabled(bool(texts))
        if not texts:
            self.text.setPlaceholderText(tr("ocr_empty"))

    def set_error(self, msg):
        self._results = []
        self.meta.setText("")
        self.text.setPlainText("")
        self.text.setPlaceholderText(tr("ocr_failed", msg))
        self.btn_copy.setEnabled(False)
        self.btn_save.setEnabled(False)

    # ---------- 动作 ----------
    def copy_text(self):
        t = self.text.toPlainText()
        if not t:
            self._pop_toast(tr("ocr_empty"))
            return
        from . import clipboard as clip

        # 写入后回读校验（被占用时重试），成功/失败都给明确反馈
        self._pop_toast(tr("copied") if clip.set_text(t) else tr("copy_failed"))

    def save_txt(self):
        from ..paths import pictures_dir

        default_dir = ""
        if self.cfg is not None:
            default_dir = self.cfg.get("save_dir") or ""
        if not default_dir:
            default_dir = pictures_dir()
        default = os.path.join(default_dir, "OCR_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
        path, _ = QFileDialog.getSaveFileName(self, tr("ocr_save_txt"), default, "Text (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text.toPlainText())
            if self.cfg is not None:
                self.cfg.set("save_dir", os.path.dirname(path))
            self._pop_toast(tr("saved", path))
        except Exception as e:
            QMessageBox.warning(self, tr("ocr_result"), tr("save_failed", e))

    def showEvent(self, ev):
        theme.apply_window_chrome(self, dark_title=theme.current().dark)
        super().showEvent(ev)

    def retheme(self, t):
        self.setStyleSheet(theme.qss_result(t))
        from PyQt5.QtGui import QColor, QPalette

        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(t.bg))
        pal.setColor(QPalette.Base, QColor(t.card))
        pal.setColor(QPalette.WindowText, QColor(t.text))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(ev)

    def show_near(self, anchor_rect, screen):
        """在锚点矩形（全局逻辑坐标）右侧显示，放不下则屏幕居中。"""
        self.adjustSize()
        g = self.frameGeometry()
        sr = screen.availableGeometry()
        x = int(anchor_rect.right()) + 16
        y = int(anchor_rect.top())
        if x + g.width() > sr.right():
            x = int(anchor_rect.left()) - g.width() - 16
            if x < sr.left():
                x = sr.left() + (sr.width() - g.width()) // 2
        y = max(sr.top() + 8, min(y, sr.bottom() - g.height() - 8))
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, ev):
        self.closed.emit()
        super().closeEvent(ev)
