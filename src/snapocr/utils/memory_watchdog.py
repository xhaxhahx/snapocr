# -*- coding: utf-8 -*-
"""内存看门狗：三层防线的 L2 兜底。

场景：永不关机、本应用永不关闭、每天重度使用的固定性能机器。要求常驻内存
（Commit）不超过「启动基线 + 48MB」，超限时先软释放，仍超限则**自愈重启**
（派生新进程接管后旧进程退出，全程 ≤3s，**全程静默、不弹任何通知**）。

状态机见 docs/15-内存治理实施计划书.md §3。busy 时本轮直接跳过——绝不打断
正在进行的截屏/识别/任何可见窗口。
"""

import os
import time
from typing import ClassVar

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from .logger import get_logger

log = get_logger()

# ---- 参数（docs/15 §3 参数表）----
CHECK_INTERVAL_S = 60
SOFT_THRESHOLD_MB = 24  # 基线 + 24MB → 软释放
HARD_THRESHOLD_MB = 48  # 基线 + 48MB → 自愈重启（硬上限）
CONFIRM_TIMES = 2  # 连续超硬阈值次数（防抖）
MIN_RECYCLE_INTERVAL_S = 3600  # 两次自愈重启最小间隔（防风暴）
BASELINE_DELAY_S = 45  # 基线最晚采样点（见下）
# 基线多点采样：基线必须落在**任何用户操作之前**，否则首轮 OCR 的 arena 增长会
# 把基线抬高、看门狗永不触发（实测教训）。10s/25s/45s 三点取最低——10s 时初始化
# 已完成（引擎懒加载），用户几乎不可能在 10s 内完成一次带 OCR 的会话。
BASELINE_SAMPLES_S = (10, 25, 45)


def _commit_mb_win() -> float:
    """Windows：Commit（PagedMemorySize64，含私有提交页，比 WS 稳定）。"""
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_: ClassVar = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.windll.kernel32
    # 64 位下必须显式声明句柄类型：GetCurrentProcess 返回伪句柄 (HANDLE)-1，
    # 不设 restype 会被截断成 32 位 → K32GetProcessMemoryInfo 拿到非法句柄返回 0
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.K32GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PMC),
        ctypes.c_uint32,
    ]
    k32.K32GetProcessMemoryInfo.restype = ctypes.c_int
    handle = k32.GetCurrentProcess()
    if not k32.K32GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
        return -1.0
    return pmc.PagefileUsage / (1024.0 * 1024.0)


def _commit_mb_linux() -> float:
    """Linux：statm 常驻页 + VmSwap（信创 UOS/麒麟）。"""
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        with open("/proc/self/statm", encoding="ascii") as f:
            rss = int(f.read().split()[1]) * page / (1024.0 * 1024.0)
        swap = 0.0
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmSwap:"):
                    swap = int(line.split()[1]) / 1024.0
                    break
        return rss + swap
    except Exception:
        return -1.0


def commit_mb() -> float:
    """当前进程 Commit（MB）。读不到返回 -1（看门狗本轮放弃）。"""
    return _commit_mb_win() if os.name == "nt" else _commit_mb_linux()


class MemoryWatchdog(QObject):
    """采样 → 软释放 → 自愈重启 的状态机。busy 时整个周期跳过。"""

    softReleased = pyqtSignal(float)  # 软释放后的 Commit（MB）
    recycled = pyqtSignal()  # 即将自愈重启（宿主应立即派生新进程并退出）

    def __init__(self, parent, is_busy, soft_release, do_recycle):
        super().__init__(parent)
        self._is_busy = is_busy  # () -> bool：会话/识别/任何可见窗口进行中
        self._soft_release = soft_release  # () -> None
        self._do_recycle = do_recycle  # () -> None
        self._baseline = None  # 历史最低 Commit（防阈值漂移）
        self._over_hard = 0  # 连续超硬阈值计数
        self._last_recycle = 0.0  # monotonic
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_S * 1000)
        self._timer.timeout.connect(self._check)

    def start(self):
        if os.environ.get("SNAPOCR_NO_WATCHDOG"):  # 测试逃生口
            return
        # 多点采基线（取最低），随后进入周期采样
        for s in BASELINE_SAMPLES_S:
            QTimer.singleShot(s * 1000, self._sample_baseline)
        self._timer.start()

    # ---- 状态机 ----
    def _sample_baseline(self):
        if self._is_busy():
            return  # 忙碌时的采样不可信（会话/识别中间态），放弃本次
        cur = commit_mb()
        if cur > 0:
            self._accept(cur)

    def _accept(self, cur):
        """基线 min-tracking，带骤降守卫：读数较基线腰斩 = 进程退出伪影
        （旧实例关闭途中定时器最后一跳，Commit 已被系统回收），不得采信。"""
        if self._baseline is not None and cur < self._baseline * 0.5:
            log.warning("内存读数骤降 %.1f→%.1fMB，视为退出伪影忽略", self._baseline, cur)
            return
        self._baseline = min(self._baseline, cur) if self._baseline else cur
        log.info("内存看门狗基线: %.1fMB", self._baseline)

    def _check(self):
        if self._is_busy():
            return  # 会话/识别/可见窗口进行中：绝不打扰
        cur = commit_mb()
        if cur <= 0:
            return
        if self._baseline is not None and cur < self._baseline * 0.5:
            # 骤降：退出伪影（见 _accept），同时把基线复位到当前真实值
            log.warning("检查发现基线失真，重置为 %.1fMB", cur)
            self._baseline = cur
            return
        self._accept(cur)  # 基线取历史最低（带骤降守卫）
        if self._baseline is None:
            return
        over_soft = cur - self._baseline > SOFT_THRESHOLD_MB
        over_hard = cur - self._baseline > HARD_THRESHOLD_MB
        if over_soft:
            log.info("内存超软阈值: %.1fMB (基线 %.1f)", cur, self._baseline)
            self._soft_release()
            cur = commit_mb()
            self.softReleased.emit(cur)
            # 软释放后重新判定硬阈值
            over_soft = cur - self._baseline > SOFT_THRESHOLD_MB
            over_hard = cur - self._baseline > HARD_THRESHOLD_MB
        if over_hard:
            self._over_hard += 1
        else:
            self._over_hard = 0
        if over_hard and self._over_hard >= CONFIRM_TIMES:
            since = time.monotonic() - self._last_recycle
            if since >= MIN_RECYCLE_INTERVAL_S:
                log.warning("内存 %.1fMB 连续 %d 次超硬阈值 → 自愈重启", cur, self._over_hard)
                self._last_recycle = time.monotonic()
                self._over_hard = 0
                self.recycled.emit()
                self._do_recycle()
