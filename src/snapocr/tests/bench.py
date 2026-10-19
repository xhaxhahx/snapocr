# -*- coding: utf-8 -*-
"""OCR 基准测试：样图→识别，输出耗时。
用法: python -m snapocr --bench [次数]
"""

import sys
import time


def run_bench(app, cfg):
    if sys.stdout is not None:  # 打包版(console=False) 双击启动时 stdout 为 None
        sys.stdout.reconfigure(encoding="utf-8")
    from ..ocr import engine as E
    from .selftest import _sample_image

    img = _sample_image()
    bgr = E.qimage_to_bgr(img)
    t0 = time.perf_counter()
    E.get_engine(cfg)
    print("引擎加载: %.2fs" % (time.perf_counter() - t0))
    # 次数参数：缺省/越界/非数字一律回落 3（照抄 main.py 处理 --gallery 的写法）
    n = 3
    if "--bench" in sys.argv:
        i = sys.argv.index("--bench")
        if i + 1 < len(sys.argv):
            try:
                n = max(1, int(sys.argv[i + 1]))
            except ValueError:
                n = 3
    times = []
    for i in range(n):
        res, el = E.recognize_sync(cfg, bgr)
        times.append(el)
        print("第%d次: %.3fs, %d 行" % (i + 1, el, len(res)))
    if times:
        print("平均: %.3fs (不含首次)" % (sum(times[1:]) / max(1, len(times) - 1)))
    return 0
