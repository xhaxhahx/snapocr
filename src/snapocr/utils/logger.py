# -*- coding: utf-8 -*-
"""滚动文件日志 + 全局异常钩子。"""

import logging
import logging.handlers
import os
import sys
import traceback

from .. import APP_DISPLAY
from ..paths import log_dir

_LOG = None


def get_logger() -> logging.Logger:
    global _LOG
    if _LOG is not None:
        return _LOG
    logger = logging.getLogger("snapocr")
    logger.setLevel(logging.INFO)
    try:
        # utf-8-sig：写入 BOM，记事本打开中文不乱码（旧日志需滚动或手删后生效）
        fh = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir(), "snapocr.log"),
            maxBytes=1024 * 512,
            backupCount=3,
            encoding="utf-8-sig",
        )
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(fh)
    except Exception:
        # 日志文件不可写（只读目录）：降级为仅 stderr
        pass
    if hasattr(sys, "stderr") and sys.stderr:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh)
    logger.propagate = False
    _LOG = logger
    return logger


def install_excepthook(dialog=True):
    log = get_logger()

    def hook(t, v, tb):
        log.error("未处理异常:\n%s", "".join(traceback.format_exception(t, v, tb)))
        if dialog:
            try:
                from PyQt5.QtWidgets import QApplication, QMessageBox

                if QApplication.instance() is not None:
                    box = QMessageBox()
                    box.setIcon(QMessageBox.Critical)
                    box.setWindowTitle(APP_DISPLAY)
                    box.setText("程序遇到未处理的错误，详情见日志文件。")
                    box.setDetailedText("".join(traceback.format_exception(t, v, tb)))
                    box.exec_()
            except Exception:
                # 错误弹窗自身失败时不能再抛，否则递归
                pass

    sys.excepthook = hook
