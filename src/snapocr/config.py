# -*- coding: utf-8 -*-
"""配置：JSON 持久化 + 默认值。"""

import atexit
import json
import os
import threading

from .paths import config_file

DEFAULTS = {
    "hotkey": "",  # 初始不设呼出快捷键：用户在设置里录入并保存后才生效（2026-10-29 需求）
    "autostart": False,
    "save_dir": "",  # 空=系统图片目录
    "lang": "",  # 空=跟随系统
    "ocr_use_cls": True,  # 方向分类（纠正旋转文字）
    "ocr_small_scale": 1.0,  # 小字放大倍数 1.0/1.5/2.0
    "ocr_threads": 0,  # 0=自动（自动=按 min(4, CPU 核) 跑，避免线程超订阅，U9 口径）
    "ocr_max_dim": 4000,  # 送推理前最长边钳制，防超大图内存峰值
    "ocr_release_after": False,  # 识别后释放模型（低配机省内存）
    "pen_color": "#ff3b30",
    "mosaic_block": 10,  # 马赛克块大小(设备像素)；设置入口在截图工具条（马赛克激活时）
    "mem_mode": "threshold",  # 内存自动整理：threshold=按内存阈值 / time=按时间间隔 / off=关闭
    "mem_threshold_mb": 30,  # 阈值模式触发线：高于初始化基线多少 MB（用户可调）
    "mem_interval_min": 60,  # 时间模式整理间隔（分钟）
    "autostart_shown_tip": False,  # 首次运行提示已展示（须进 DEFAULTS 才会被 load() 回读）
    "result_win_w": 480,  # 结果窗上次尺寸（U8，关闭时回写）
    "result_win_h": 400,
}

_SAVE_DEBOUNCE_S = 0.3  # 连续 set() 的写盘合并窗口（色谱拖动以鼠标事件频率触发 set）


class Config:
    def __init__(self):
        self._lock = threading.Lock()
        self._d = dict(DEFAULTS)
        self._save_timer = None
        self.load()
        atexit.register(self._flush_now)

    def load(self):
        try:
            with open(config_file(), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in DEFAULTS:
                    # 值类型与默认值不一致（手改脏配置）按损坏处理回落默认：
                    # save_dir=123 会让保存路径拼接抛 TypeError，ocr_threads="abc"
                    # 会让推理参数转换抛 ValueError（§33.1 A2）
                    if k in data and type(data[k]) is type(DEFAULTS[k]):
                        self._d[k] = data[k]
        except Exception:
            # 配置损坏/不可读：回落默认值，不阻断启动
            pass
        # 旧默认热键迁移（F4 → 无：新语义下默认不启用快捷键，用户未自定义过的旧装机回落为空）
        if self._d.get("hotkey") == "F4":
            self._d["hotkey"] = ""

    def save(self):
        """立即同步落盘（reset/退出等需要马上生效的路径用）。"""
        self._cancel_timer()
        self._write_file()

    def get(self, key, default=None):
        return self._d.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        with self._lock:
            # 持锁写入：防与 _write_file 的 json.dump 并发时字典变大小（§33.2 C1）
            self._d[key] = value
        self._schedule_save()

    def reset(self):
        """恢复全部默认值并落盘（设置页「恢复默认」用）。"""
        self._d = dict(DEFAULTS)
        self.save()

    # ---- 写盘去抖（§33.2 C1）----

    def _schedule_save(self):
        """0.3s 内的连续 set() 合并为一次写盘。

        色谱拖动/连点曾以鼠标事件频率全量写 JSON+os.replace（实测 1.3ms/次，
        60Hz 拖动约 76ms/s 纯磁盘开销，另有文件创建/替换 churn）。代价：进程在
        窗口期内被硬杀会丢最后一次 UI 偏好写入——atexit 兜底 + 正常退出均会 flush。
        """
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            t = threading.Timer(_SAVE_DEBOUNCE_S, self._flush)
            t.daemon = True
            self._save_timer = t
        t.start()

    def _flush(self):
        with self._lock:
            self._save_timer = None
        self._write_file()

    def _flush_now(self):
        """atexit/立即落盘：取消在途定时器后同步写一次。"""
        self._cancel_timer()
        self._write_file()

    def _cancel_timer(self):
        with self._lock:
            t, self._save_timer = self._save_timer, None
        if t is not None:
            t.cancel()

    def _write_file(self):
        with self._lock:
            try:
                tmp = config_file() + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._d, f, ensure_ascii=False, indent=2)
                os.replace(tmp, config_file())
            except Exception:
                # 写入失败（只读目录/磁盘满）：静默降级为不持久化
                pass
