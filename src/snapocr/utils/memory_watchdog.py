# -*- coding: utf-8 -*-
"""内存看门狗：三层防线的 L2 兜底，行为由设置页「内存管理」组驱动（docs/15）。

模式（cfg: mem_mode）：
- threshold（默认）：空闲时 Commit > 基线 + mem_threshold_mb → 软释放；
  仍超限且连续 2 次 → 自愈重启（回到初始化基线的最终兜底）
- time：空闲时距上次整理 ≥ mem_interval_min 分钟 → 软释放 + 自愈重启（彻底回基线）
- off：不整理

busy 时整个周期跳过——绝不打断正在进行的截屏/识别/任何可见窗口。
"""

import gc
import os
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from .logger import get_logger

log = get_logger()

CHECK_INTERVAL_S = 30  # 采样周期（用户阈值可低至 10MB，30s 保证响应）
CONFIRM_TIMES = 2  # 阈值模式：连续超限次数（防抖）
MIN_RECYCLE_INTERVAL_S = 300  # 两次自愈重启最小间隔（防风暴，用户模式下的底线）
BASELINE_SAMPLES_S = (10, 25, 45)  # 基线多点采样（取最低；10s 时初始化已完成）


def _commit_mb_win() -> float:
    """Windows：Commit（PagefileUsage，含私有提交页，比 WS 稳定）。"""
    import ctypes

    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [
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
    """采样 → 软释放 → 自愈重启 的状态机（模式/阈值/间隔由设置页配置）。"""

    softReleased = pyqtSignal(float)  # 软释放后的 Commit（MB）
    recycled = pyqtSignal()  # 即将自愈重启（宿主应立即派生新进程并退出）

    def __init__(self, parent, cfg_get, is_busy, soft_release, do_recycle):
        super().__init__(parent)
        self._cfg_get = cfg_get  # (key, default) -> 值：每次检查实时读设置
        self._is_busy = is_busy  # () -> bool：会话/识别/任何可见窗口进行中
        self._soft_release = soft_release  # () -> None
        self._do_recycle = do_recycle  # () -> None
        self._baseline = None  # 历史最低 Commit（防阈值漂移）
        self._over_count = 0  # 阈值模式：连续超限计数
        self._last_recycle = 0.0  # monotonic；start() 时锚定为启动时刻
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_S * 1000)
        self._timer.timeout.connect(self._check)

    def start(self):
        if os.environ.get("SNAPOCR_NO_WATCHDOG"):  # 测试逃生口
            return
        self._last_recycle = time.monotonic()  # 时间模式：从启动起算间隔
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
            log.warning(
                "内存读数骤降 %.1f→%.1fMB，视为退出伪影忽略", self._baseline, cur
            )
            return
        self._baseline = min(self._baseline, cur) if self._baseline else cur
        log.info("内存看门狗基线: %.1fMB", self._baseline)

    def _check(self):
        if self._is_busy():
            return  # 会话/识别/可见窗口进行中：绝不打扰
        mode = self._cfg_get("mem_mode", "threshold")
        if mode == "off":
            return
        cur = commit_mb()
        if cur <= 0:
            return
        if self._baseline is not None and cur < self._baseline * 0.5:
            # 骤降（腰斩级）= 读取伪影（如宿主进程异常回收）：忽略本轮并保持基线，
            # 活进程内不会出现合法的腰斩级回落，基线绝不被伪影拉低
            log.warning("内存读数骤降 %.1f→%.1fMB，忽略本轮", self._baseline, cur)
            return
        self._accept(cur)  # 基线取历史最低（带骤降守卫）
        if self._baseline is None:
            return

        if mode == "time":
            interval_s = max(5, int(self._cfg_get("mem_interval_min", 60))) * 60
            if time.monotonic() - self._last_recycle >= interval_s:
                log.info("内存整理（按时间，间隔 %d 分钟）", interval_s // 60)
                self._do_reclaim()
            return

        # ---- threshold 模式（默认）----
        limit = self._baseline + max(10, int(self._cfg_get("mem_threshold_mb", 30)))
        if cur > limit:
            log.info("内存超阈值: %.1fMB (基线 %.1f + %d)", cur, self._baseline,
                     max(10, int(self._cfg_get("mem_threshold_mb", 30))))
            self._soft_release()
            cur = commit_mb()
            self.softReleased.emit(cur)
        if cur > limit:
            self._over_count += 1
        else:
            self._over_count = 0
        if self._over_count >= CONFIRM_TIMES:
            since = time.monotonic() - self._last_recycle
            if since >= MIN_RECYCLE_INTERVAL_S:
                log.warning("内存 %.1fMB 连续 %d 次超阈值 → 自愈重启", cur, self._over_count)
                self._last_recycle = time.monotonic()
                self._over_count = 0
                self.recycled.emit()
                self._do_recycle()

    def _do_reclaim(self):
        """时间模式的整理动作：软释放 + 自愈重启（彻底回到初始化基线）。"""
        self._last_recycle = time.monotonic()
        self._soft_release()
        self.recycled.emit()
        self._do_recycle()
