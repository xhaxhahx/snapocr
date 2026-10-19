# -*- coding: utf-8 -*-
"""OCR 工作线程：加载/识别都在子线程，UI 不卡。"""

import time

from PyQt5.QtCore import QThread, pyqtSignal

from ..utils.logger import get_logger
from . import engine as E

log = get_logger()


class OcrWorker(QThread):
    ok = pyqtSignal(list, float)  # results, elapsed
    fail = pyqtSignal(str)
    loaded = pyqtSignal(float)  # 引擎首次加载耗时
    # 流式反馈：det 完成（文本框数）/ 单条识别完成（文本, 已完成, 总数）
    found = pyqtSignal(int)
    partial = pyqtSignal(str, int, int)

    def __init__(self, cfg, qimage, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.qimage = qimage

    def run(self):
        try:
            if not E.engine_loaded():
                t0 = time.perf_counter()
                E.get_engine(self.cfg)
                self.loaded.emit(time.perf_counter() - t0)
            bgr = E.qimage_to_bgr(self.qimage)
            results, elapsed = E.recognize_stream(
                self.cfg,
                bgr,
                on_found=self.found.emit,
                on_line=lambda item, done, total: self.partial.emit(item[0], done, total),
            )
            self.ok.emit(results, elapsed)
        except E.OcrError as e:
            log.warning("OCR 失败: %s", e)
            self.fail.emit(str(e))
        except Exception as e:
            log.exception("OCR 异常")
            self.fail.emit(repr(e))
