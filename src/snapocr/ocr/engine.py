# -*- coding: utf-8 -*-
"""RapidOCR(ONNX) 引擎封装：懒加载单例、全离线模型、参数调优。

- 模型从 resources/models 读取（det/cls/rec .onnx），运行期不联网。
- 兼容 rapidocr 2.x / 3.x 的参数接口。
"""

import contextlib
import os
import threading
import time

import numpy as np

# 关键：先加载 onnxruntime 原生库，再让 rapidocr/cv2 稍后加载，
# 避免 OpenCV/ORT 运行时符号抢占导致的 0xC0000005（详见 docs/05-测试报告.md）
with contextlib.suppress(Exception):  # 缺失时交由 get_engine 报出可读错误
    import onnxruntime  # noqa: F401

from ..paths import find_model
from ..utils.logger import get_logger

log = get_logger()

# 见 recognize_stream：上游属性缺失时的兜底阈值（0.0 = 不过滤，需人工核对）
_DEFAULT_TEXT_SCORE = 0.0

_lock = threading.Lock()
_engine = None
_engine_key = None


class OcrError(Exception):
    pass


def _build_params(cfg):
    """rapidocr 3.x 配置键（config.yaml 结构）。

    模型优先用 resources/models 下的离线副本；没有则回落到
    rapidocr wheel 内置的 PP-OCRv6 small（det/rec）+ PP-OCRv4 mobile(cls)，
    两者都是离线随包分发，不联网。
    """
    det = find_model("det")
    rec = find_model("rec")
    cls = find_model("cls")
    threads = int(cfg.get("ocr_threads", 0) or 0)
    # 无论正负都夹到 [1, cpu_count]：手改配置注入越界值会导致线程超订阅（识别更慢甚至卡死）
    try:
        _cpu = os.cpu_count() or 4
    except Exception:
        _cpu = 4
    if threads <= 0:
        threads = max(1, min(4, _cpu))
    threads = max(1, min(threads, _cpu))
    params = {
        "EngineConfig.onnxruntime.intra_op_num_threads": threads,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "Global.log_level": "warning",
    }
    if det:
        params["Det.model_path"] = det
    if rec:
        params["Rec.model_path"] = rec
    if cfg.get("ocr_use_cls", True):
        if cls:
            params["Cls.model_path"] = cls
    else:
        params["Global.use_cls"] = False
    return params


def get_engine(cfg):
    """进程内懒加载单例（在调用线程内初始化 onnxruntime 会话）。"""
    global _engine, _engine_key
    key = (bool(cfg.get("ocr_use_cls", True)), int(cfg.get("ocr_threads", 0) or 0))
    with _lock:
        if _engine is not None and _engine_key == key:
            return _engine
        try:
            from rapidocr import RapidOCR
        except ImportError as e:
            raise OcrError("rapidocr 未安装: %s" % e) from e
        params = _build_params(cfg)
        try:
            eng = RapidOCR(params=params)
        except TypeError:
            # 老接口：直接传 **params
            eng = RapidOCR(**params)
        _engine = eng
        _engine_key = key
        log.info("OCR 引擎就绪 cls=%s threads=%s", key[0], key[1])
        return _engine


def engine_loaded() -> bool:
    """引擎是否已加载（供工作线程判断是否需要上报"首次加载耗时"）。"""
    return _engine is not None


def release_engine():
    global _engine, _engine_key
    with _lock:
        _engine = None
        _engine_key = None
    # 置空引用≠内存归还：onnxruntime 会话对象要等 Python GC 析构才真正释放。
    # 不主动 collect 时旧会话可延迟数轮不回收，表现为"每轮 OCR +13MB 常驻堆积"
    # （docs/15 实测根因①）。释放路径低频，collect 的几十毫秒可接受。
    import gc

    gc.collect()


def qimage_to_bgr(img) -> np.ndarray:
    """QImage(Format_RGB888) → BGR ndarray。"""
    from PyQt5.QtGui import QImage

    if img.format() != QImage.Format_RGB888:
        img = img.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    nbytes = img.sizeInBytes()
    ptr = img.constBits()
    try:
        raw = ptr.asarray(nbytes)  # PyQt5 sip.voidptr
    except AttributeError:
        raw = bytes(ptr)  # 兜底
    arr = np.frombuffer(raw, dtype=np.uint8, count=nbytes)
    arr = arr.reshape(h, img.bytesPerLine())[:, : w * 3].reshape(h, w, 3)
    # RGB→BGR：通道反转是负步长视图（非连续），ascontiguousarray 仅在需要时才拷贝
    return np.ascontiguousarray(arr[:, :, ::-1])


def _clamp_max_dim(bgr: np.ndarray, max_dim: int) -> np.ndarray:
    """最长边超过 max_dim 时等比缩小（4K 多屏拼接直送推理会撑爆内存/极慢）。"""
    if max_dim <= 0:
        return bgr
    h, w = bgr.shape[:2]
    longest = max(h, w)
    if longest <= max_dim:
        return bgr
    import cv2

    s = max_dim / float(longest)
    out = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    log.info("OCR 输入过大(%dx%d)已缩放到 %dx%d 防内存峰值", w, h, out.shape[1], out.shape[0])
    return out


def _sort_reading_order(items):
    """按阅读顺序重排：行（y 聚类，阈值 20px）优先，同行再按 x。
    双栏/卡片版面可避免串行；无坐标的结果保持相对原序（稳定排序）。"""

    def key(item):
        box = item[2]
        if not box:
            return (10**9, 0.0)
        try:
            ys = [float(p[1]) for p in box]
            xs = [float(p[0]) for p in box]
        except Exception:
            return (10**9, 0.0)
        return (round(min(ys) / 20.0), min(xs))

    return sorted(items, key=key)


def recognize_sync(cfg, bgr: np.ndarray):
    """同步识别，返回 (results, elapsed)。results=[(text, score, box), ...]"""
    eng = get_engine(cfg)
    t0 = time.perf_counter()
    # 大图钳制（借鉴 RapidOCR 官方建议）：先钳源图避免放大产生超大临时图，
    # 放大后再钳一次，保证最终送推理的尺寸不超上限
    max_dim = int(cfg.get("ocr_max_dim", 4000) or 4000)
    bgr = _clamp_max_dim(bgr, max_dim)
    scale = float(cfg.get("ocr_small_scale", 1.0) or 1.0)
    if scale > 1.0:
        import cv2

        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        bgr = _clamp_max_dim(bgr, max_dim)
    try:
        result = eng(bgr)
    except Exception as e:
        raise OcrError(str(e)) from e
    elapsed = time.perf_counter() - t0
    out = []
    if result is None:
        return out, elapsed
    # rapidocr 2.x/3.x: RapidOCROutput(txts, scores, boxes) / 元组
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    boxes = getattr(result, "boxes", None)
    if txts is None:
        try:
            res = result[1] if isinstance(result, (list, tuple)) else None
            if res is not None:
                txts = [r[1] for r in res]
                scores = [r[2] for r in res]
                boxes = [r[0] for r in res]
        except Exception:
            txts = None
    if txts:
        for i, t in enumerate(txts):
            score = float(scores[i]) if scores is not None and i < len(scores) else 1.0
            box = None
            if boxes is not None and i < len(boxes):
                box = np.asarray(boxes[i]).tolist()
            out.append((str(t), score, box))
    if out:
        out = _sort_reading_order(out)
    return out, elapsed


def _reading_order_indices(boxes, count):
    """按阅读顺序（y 行聚类 + 同行按 x）返回下标序列，用于逐框识别的输出次序。

    仅决定"先识别哪个框"，不影响最终结果——最终仍走 `_sort_reading_order` 统一排序。
    """
    if boxes is None or len(boxes) != count:
        return list(range(count))

    def key(i):
        try:
            arr = np.asarray(boxes[i], dtype=float)
            return (round(float(arr[:, 1].min()) / 20.0), float(arr[:, 0].min()))
        except Exception:
            return (10**9, 0.0)

    return sorted(range(count), key=key)


def recognize_stream(cfg, bgr: np.ndarray, on_found=None, on_line=None):
    """流式识别：det → cls → 逐框 rec，边识别边回调，用于"让用户看到模型在工作"。

    参数
    ----
    on_found(total): 检测完成时回调，total 为文本框数量（此阶段之前无任何文字可显示）
    on_line(item, done, total): 每识别完一条回调；item=(text, score, box)，
        只回调**通过置信度阈值**的结果，避免界面出现随后又消失的噪声

    返回 (results, elapsed)，其中 results 与 `recognize_sync` 完全一致
    （同阈值过滤、同阅读顺序、同坐标映射）。

    说明：det 占整条流水线约 70%~80% 的时间且无法输出文字，故 `on_found` 是
    "有进展"的最早信号；逐框 rec 与整批 rec 耗时基本相同（实测约 0.8~1.0 倍）。
    """
    eng = get_engine(cfg)
    t0 = time.perf_counter()
    # 与 recognize_sync 保持完全相同的预处理，保证结果一致
    max_dim = int(cfg.get("ocr_max_dim", 4000) or 4000)
    bgr = _clamp_max_dim(bgr, max_dim)
    scale = float(cfg.get("ocr_small_scale", 1.0) or 1.0)
    if scale > 1.0:
        import cv2

        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        bgr = _clamp_max_dim(bgr, max_dim)

    op_record = {}
    try:
        crops, det_res = eng.detect_and_crop(bgr, op_record)
        if getattr(eng, "use_cls", False):
            crops, _cls_res = eng.cls_and_rotate(crops)
    except Exception as e:
        if "result is empty" in str(e):
            # 空白/零检出图：上游 detect_and_crop 抛异常，而 __call__（sync 路径）对同一
            # 输入返回空结果。两条路径对齐：按"未识别到文字"返回，不把上游英文异常
            # 文案当失败直出给用户（2026-10-23 回归轮实证）。消息匹配属上游私有口径
            # （宪法 §4.6），升级 rapidocr 时须复核。
            if on_found is not None:
                on_found(0)
            return [], time.perf_counter() - t0
        raise OcrError(str(e)) from e

    boxes = getattr(det_res, "boxes", None)
    total = len(crops)
    if on_found is not None:
        on_found(total)
    if total == 0:
        return [], time.perf_counter() - t0

    # rapidocr 的文本置信度阈值（3.x: engine.text_score）。这是上游**非公开**属性：
    # 升级 rapidocr 时必须重新核对——一旦改名，这里会静默回落到 _DEFAULT_TEXT_SCORE，
    # 使流式路径的过滤阈值与批量路径（由 rapidocr 内部过滤）不一致。
    threshold = float(getattr(eng, "text_score", _DEFAULT_TEXT_SCORE) or _DEFAULT_TEXT_SCORE)
    order = _reading_order_indices(boxes, total)
    items = []
    for done, idx in enumerate(order, 1):
        text, score = "", 0.0
        try:
            out = eng.recognize_txt([crops[idx]])
            if getattr(out, "txts", None):
                text = str(out.txts[0])
                score = float(out.scores[0]) if getattr(out, "scores", None) else 1.0
        except Exception as e:
            # 单框识别失败不应毁掉整次识别：记日志后跳过该框
            log.warning("单框识别失败(第 %d 个): %s", idx, e)
        if score >= threshold and text.strip():
            box = None
            if boxes is not None and idx < len(boxes):
                box = np.asarray(boxes[idx]).tolist()
            item = (text, score, box)
            items.append(item)
            if on_line is not None:
                on_line(item, done, total)

    if items:
        items = _sort_reading_order(items)
        # 坐标映射回原图（与 build_final_output 同一套映射），保证与 sync 路径等价
        with contextlib.suppress(Exception):
            from rapidocr.utils.process_img import map_boxes_to_original

            mapped = map_boxes_to_original(
                np.array([it[2] for it in items], dtype=float),
                op_record,
                bgr.shape[0],
                bgr.shape[1],
            )
            items = [(it[0], it[1], np.asarray(mb).tolist()) for it, mb in zip(items, mapped)]
    return items, time.perf_counter() - t0
