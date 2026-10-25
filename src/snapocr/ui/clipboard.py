# -*- coding: utf-8 -*-
"""剪贴板写入 + 回读校验。

背景：剪贴板被其他程序（剪贴板管理器 / RDP / Office）短暂占用时，Qt 的
QClipboard.setImage/setText 会静默失败；原实现仍然提示「已复制」，用户粘贴得到空内容，
信任一次性受损。这里统一改为「写入 → 回读校验 → 失败重试 → 如实返回结果」。
"""

import os
import shutil
import tempfile
import time

from PyQt5.QtCore import QMimeData, QUrl
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QApplication

TRIES = 3
DELAY_MS = 100


def _pump(ms):
    """重试间隔内保持事件循环转动，避免界面假死。"""
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def set_image(image, tries=TRIES, delay_ms=DELAY_MS) -> bool:
    """写图片到剪贴板并回读校验；成功返回 True。"""
    cb = QGuiApplication.clipboard()
    for i in range(max(1, tries)):
        try:
            cb.setImage(image)
            QApplication.processEvents()
            if not cb.image().isNull():
                return True
        except Exception:
            # 被其他程序占用时 setImage 可能抛异常：继续重试，最终以返回值如实上报
            pass
        if i < tries - 1:
            _pump(delay_ms)
    return False


def set_text(text, tries=TRIES, delay_ms=DELAY_MS) -> bool:
    """写文本到剪贴板并回读校验；成功返回 True。"""
    if not text:
        return False
    cb = QGuiApplication.clipboard()
    for i in range(max(1, tries)):
        try:
            cb.setText(text)
            QApplication.processEvents()
            if cb.text() == text:
                return True
        except Exception:
            # 同上：占用/竞态导致的写入异常交给下一轮重试
            pass
        if i < tries - 1:
            _pump(delay_ms)
    return False


# ---------------- 复制为文件（2026-10-26 新增） ----------------
# 系统剪贴板的"文件复制"（Win=CF_HDROP / X11=text/uri-list）引用的是真实路径，
# 因此必须先落盘再写剪贴板。文件写在系统临时目录，下次启动自动清理。


def _clip_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "SnapOCR", "clipboard")
    os.makedirs(d, exist_ok=True)
    return d


def cleanup_clip_files():
    """清理"复制为文件"的上次残留（启动时调用；本会话刚写的文件不在此列）。"""
    shutil.rmtree(os.path.join(tempfile.gettempdir(), "SnapOCR", "clipboard"), ignore_errors=True)


def _unique_path(name: str) -> str:
    """在临时目录里给名字去重（同名追加 (2)/(3)…），返回完整路径。"""
    d = _clip_dir()
    path = os.path.join(d, name)
    stem, ext = os.path.splitext(name)
    i = 2
    while os.path.exists(path):
        path = os.path.join(d, "%s (%d)%s" % (stem, i, ext))
        i += 1
    return path


def _set_file(path: str) -> bool:
    """把文件以"文件复制"语义写入剪贴板（只带文件，不附带图像/文字数据），回读校验。"""
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(path)])
    cb = QGuiApplication.clipboard()
    for i in range(max(1, TRIES)):
        try:
            cb.setMimeData(md)
            QApplication.processEvents()
            cur = cb.mimeData()
            if (
                cur is not None
                and cur.hasUrls()
                # toLocalFile 返回正斜杠路径（Qt 规范化），与原生路径须按 normpath 比
                and any(
                    os.path.normpath(u.toLocalFile()) == os.path.normpath(path) for u in cur.urls()
                )
            ):
                return True
        except Exception:
            # 与 set_image 同策：占用/竞态交给下一轮重试
            pass
        if i < TRIES - 1:
            _pump(DELAY_MS)
    return False


def copy_image_as_file(image, filename: str):
    """把图片存为 JPG 文件（质量 90，与保存一致）并复制到剪贴板；成功返回文件路径。"""
    name = (filename or "").strip()
    if not name:
        return None
    if not name.lower().endswith((".jpg", ".jpeg")):
        name += ".jpg"
    path = _unique_path(name)
    if not image.save(path, "JPG", 90):
        return None
    return path if _set_file(path) else None


def copy_text_as_file(text: str, filename: str):
    """把文本存为 TXT 文件（utf-8-sig，与另存一致）并复制到剪贴板；成功返回文件路径。"""
    if not text or not (filename or "").strip():
        return None
    name = filename.strip()
    if not name.lower().endswith(".txt"):
        name += ".txt"
    path = _unique_path(name)
    try:
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write(text)
    except OSError:
        return None
    return path if _set_file(path) else None


def ask_filename(parent, default_key: str):
    """「复制为文件」的文件名输入弹窗；确定返回文本，取消/空名返回 None。

    手动构造 QInputDialog 并关闭 WindowContextHelpButtonHint——
    Qt 在 Windows 上默认给标题栏加"?"帮助按钮，对本工具无意义（2026-10-26 用户反馈）。
    """
    import time as _time

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QDialog, QInputDialog

    from ..i18n import tr

    dlg = QInputDialog(parent)
    dlg.setInputMode(QInputDialog.TextInput)
    dlg.setWindowTitle(tr("copy_as_file"))
    dlg.setLabelText(tr("filename_label"))
    dlg.setTextValue(tr(default_key) % _time.strftime("%Y%m%d_%H%M%S"))
    dlg.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    if dlg.exec_() != QDialog.Accepted:
        return None
    text = dlg.textValue().strip()
    return text if text else None
