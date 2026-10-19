# -*- coding: utf-8 -*-
"""剪贴板写入 + 回读校验。

背景：剪贴板被其他程序（剪贴板管理器 / RDP / Office）短暂占用时，Qt 的
QClipboard.setImage/setText 会静默失败；原实现仍然提示「已复制」，用户粘贴得到空内容，
信任一次性受损。这里统一改为「写入 → 回读校验 → 失败重试 → 如实返回结果」。
"""

import time

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
