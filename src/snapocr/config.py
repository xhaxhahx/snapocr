# -*- coding: utf-8 -*-
"""配置：JSON 持久化 + 默认值。"""

import json
import os
import threading

from .paths import config_file

DEFAULTS = {
    "hotkey": "Ctrl+Alt+A",
    "autostart": False,
    "save_dir": "",  # 空=系统图片目录
    "lang": "",  # 空=跟随系统
    "ocr_use_cls": True,  # 方向分类（纠正旋转文字）
    "ocr_small_scale": 1.0,  # 小字放大倍数 1.0/1.5/2.0
    "ocr_threads": 0,  # 0=按CPU核数
    "ocr_max_dim": 4000,  # 送推理前最长边钳制，防超大图内存峰值
    "ocr_release_after": False,  # 识别后释放模型（低配机省内存）
    "pen_color": "#ff3b30",
    "mosaic_block": 10,  # 马赛克块大小(设备像素)
}


class Config:
    def __init__(self):
        self._lock = threading.Lock()
        self._d = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(config_file(), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in DEFAULTS:
                    if k in data:
                        self._d[k] = data[k]
        except Exception:
            # 配置损坏/不可读：回落默认值，不阻断启动
            pass
        # 旧默认热键迁移（F4 → Ctrl+Alt+A，仅当用户未自定义过）
        if self._d.get("hotkey") == "F4":
            self._d["hotkey"] = "Ctrl+Alt+A"

    def save(self):
        with self._lock:
            try:
                tmp = config_file() + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._d, f, ensure_ascii=False, indent=2)
                os.replace(tmp, config_file())
            except Exception:
                # 写入失败（只读目录/磁盘满）：静默降级为不持久化
                pass

    def get(self, key, default=None):
        return self._d.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        self._d[key] = value
        self.save()

    def reset(self):
        """恢复全部默认值并落盘（设置页「恢复默认」用）。"""
        self._d = dict(DEFAULTS)
        self.save()
