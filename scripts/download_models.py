# -*- coding: utf-8 -*-
"""模型下载脚本（仅构建机联网执行，产物随包离线分发）。

策略 A（首选，可靠）: 从已安装的 rapidocr wheel 复制其内置默认模型
                （rapidocr 3.10 内置 PP-OCRv6 small det/rec + ch_ppocr_mobile_v2.0_cls）
                到 resources/models/。这是当前随包分发的实际来源。
策略 B（备选，尽力而为）: 从 ModelScope 直链拉取。该直链不保证长期可用，
                失败不应中断流程（缺模型时引擎会自动回落到 wheel 内置模型）。

用法: python scripts/download_models.py
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "resources", "models")


def via_rapidocr():
    from rapidocr import RapidOCR

    RapidOCR()  # 触发默认模型下载
    import rapidocr

    pkg_dir = os.path.dirname(rapidocr.__file__)
    found = {}
    for base, _, files in os.walk(pkg_dir):
        for f in files:
            if f.endswith(".onnx"):
                low = f.lower()
                if "det" in low and "det" not in found:
                    found["det"] = os.path.join(base, f)
                elif "rec" in low and "rec" not in found:
                    found["rec"] = os.path.join(base, f)
                elif ("cls" in low or "ch_ppocr_mobile_v2.0_cls" in low) and "cls" not in found:
                    found["cls"] = os.path.join(base, f)
    # 兜底：用户缓存目录
    cache = os.path.join(os.path.expanduser("~"), ".cache", "rapidocr")
    if len(found) < 2 and os.path.isdir(cache):
        for base, _, files in os.walk(cache):
            for f in files:
                if f.endswith(".onnx"):
                    low = f.lower()
                    for kind in ("det", "rec", "cls"):
                        if kind in low and kind not in found:
                            found[kind] = os.path.join(base, f)
    return found


MODELSCOPE_URLS = {
    # 尽力而为的备选直链；ModelScope 路径随仓库调整，可能 404（失败不致命）
    "det": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/master/onnx/PP-OCRv6/det/det.onnx",
    "rec": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/master/onnx/PP-OCRv6/rec/rec.onnx",
    "cls": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/master/onnx/PP-OCRv6/cls/ch_PP-OCRv5_mobile_cls.onnx",
}


def via_modelscope():
    import urllib.request

    found = {}
    os.makedirs(DEST, exist_ok=True)
    for kind, url in MODELSCOPE_URLS.items():
        dst = os.path.join(DEST, "%s.onnx" % kind)
        if os.path.isfile(dst) and os.path.getsize(dst) > 100000:
            found[kind] = dst
            continue
        print("下载 %s ..." % url)
        # urlretrieve 不支持 timeout：用 urlopen 显式限时，避免网络挂起卡死构建机
        with urllib.request.urlopen(url, timeout=30) as resp, open(dst, "wb") as f:
            shutil.copyfileobj(resp, f)
        found[kind] = dst
    return found


def main():
    os.makedirs(DEST, exist_ok=True)
    found = {}
    try:
        found = via_rapidocr()
    except Exception as e:
        print("rapidocr 下载失败，改走 ModelScope: %s" % e)
    if len(found) < 2:
        try:
            found = via_modelscope()
        except Exception as e:
            print(
                "ModelScope 直链不可用（%s）；请确认已 pip install rapidocr，"
                "策略 A 会从 wheel 内置模型复制" % e
            )
    if "rec" not in found and "det" not in found:
        print("未能获取模型")
        return 1
    for kind, src in found.items():
        dst = os.path.join(DEST, "%s.onnx" % kind)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
        sz = os.path.getsize(dst) / 1048576
        print("已放置 %s -> %s (%.1f MB)" % (os.path.basename(src), dst, sz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
