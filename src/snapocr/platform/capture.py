# -*- coding: utf-8 -*-
"""统一抓屏接口。

- Windows(XP+) / X11：QScreen.grabWindow(0)（GDI BitBlt / XGetImage），
  返回带 devicePixelRatio 的 QPixmap。
- Wayland：grabWindow 不可用，降级到 xdg-desktop-portal Screenshot 接口（需要用户在桌面授权一次）。
- 附带若干「抓屏环境」探测：提权状态（UIPI 黑屏）、HDR 状态（发白）、远程会话（热键被拦截）、
  全黑帧判定。这些探测全部是 Windows 专用且失败即安全返回 False，非 Windows 上为空操作。
"""

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap

from ..utils.logger import get_logger

log = get_logger()

_MAX_LOGICAL_W = 2560  # 逻辑宽超过此值的屏才考虑降采样（P24）
_MIN_DPR = 1.0  # 降采样后 dpr 不得低于 1.0，保证输出不糊


def is_wayland() -> bool:
    return bool(
        os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def grab_screen_pixmap(screen) -> QPixmap:
    """抓取单块屏，返回设备像素图（devicePixelRatio 已带）。"""
    pm = screen.grabWindow(0)
    if (pm.isNull() or (pm.width() <= 1 and screen.size().width() > 2)) and is_wayland():
        pm = _grab_via_portal(screen) or pm
    if not pm.isNull():
        pm = _maybe_downsample(pm, screen)
    return pm


def _maybe_downsample(pm: QPixmap, screen) -> QPixmap:
    """超大屏（如 4K@200%）抓屏瞬时占用可达上百 MB：物理像素 1/2 降采样，
    同步把 dpr 减半以保持逻辑尺寸不变（WYSIWYG 几何完全不受影响）。
    仅当降采样后 dpr 仍 >= 1.0 时才做，避免把输出糊到「1 逻辑像素不足 1 物理像素」。"""
    try:
        if screen.geometry().width() <= _MAX_LOGICAL_W:
            return pm
        dpr = pm.devicePixelRatio() or 1.0
        new_dpr = dpr / 2.0
        if new_dpr < _MIN_DPR:
            return pm
        small = pm.scaled(
            max(1, pm.width() // 2),
            max(1, pm.height() // 2),
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
        small.setDevicePixelRatio(new_dpr)
        log.info(
            "大屏抓图降采样 %dx%d(dpr=%.2f) → %dx%d(dpr=%.2f) 以降低内存峰值",
            pm.width(),
            pm.height(),
            dpr,
            small.width(),
            small.height(),
            new_dpr,
        )
        return small
    except Exception:
        return pm


def _grab_via_portal(screen):
    """xdg-desktop-portal Screenshot：桌面弹出授权确认后返回截图文件 URI。"""
    try:
        from PyQt5.QtCore import QEventLoop, QTimer
        from PyQt5.QtDBus import QDBusConnection, QDBusInterface

        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return None
        iface = QDBusInterface(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Screenshot",
            bus,
        )
        if not iface.isValid():
            return None
        loop = QEventLoop()
        holder = {"uri": None}

        sender = str(bus.baseService())  # 形如 :1.234
        token = "snapocr_%d" % id(loop)
        handle = "/org/freedesktop/portal/desktop/request/%s/%s" % (
            sender.replace(":", "_").replace(".", "_"),
            token,
        )
        bus.connect(
            "", handle, "org.freedesktop.portal.Request", "Response", _make_response(holder, loop)
        )

        iface.call("Screenshot", "", {"handle_token": token, "interactive": True})
        QTimer.singleShot(120000, loop.quit)  # 最长等 2 分钟（等用户授权）
        loop.exec_()
        uri = holder.get("uri")
        if uri and uri.startswith("file://"):
            # portal 返回 file:// URI（含百分号编码，如 %20/中文）：必须按 URL
            # 解码成本地路径，直接切片会因路径不存在而加载失败
            from PyQt5.QtCore import QUrl

            pm = QPixmap(QUrl(uri).toLocalFile())
            if not pm.isNull():
                # portal 返回的图不带 DPR：显式补上，否则缩放屏下框选区域与实际内容错位
                pm.setDevicePixelRatio(screen.devicePixelRatio() or 1.0)
            return pm
    except Exception as e:
        log.warning("portal 抓屏失败: %s", e)
    return None


def _make_response(holder, loop):
    def _on(code, results):
        try:
            if code == 0 and "uri" in results:
                holder["uri"] = results["uri"]
        except Exception:
            # portal 回调异常（拒绝/格式变化）：视为抓屏失败走降级链
            pass
        loop.quit()

    return _on


# ---------------- 抓屏环境探测（Windows 专用，其余平台安全返回 False） ----------------


def is_elevated() -> bool:
    """当前进程是否已提权。未提权时无法读取管理员窗口的像素（UIPI），会得到全黑图。"""
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_remote_session() -> bool:
    """是否处于远程桌面（RDP）会话：本地计算机常会截走全局热键。"""
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))  # SM_REMOTESESSION
    except Exception:
        return False


def is_hdr_active() -> bool:
    """是否存在已启用 HDR（高级色彩）的显示器。查询失败一律返回 False。

    走 DisplayConfigGetDeviceInfo(GET_ADVANCED_COLOR_INFO=9)：相关结构体成员均为 4 字节，
    默认对齐与紧凑对齐一致；任何异常都不影响主流程，最坏只是不提示。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt

        class _LUID(ctypes.Structure):
            _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]

        class _PATH_SOURCE(ctypes.Structure):
            _fields_ = [
                ("adapterId", _LUID),
                ("id", wt.UINT),
                ("modeInfoIdx", wt.UINT),
                ("statusFlags", wt.UINT),
            ]

        class _RATIONAL(ctypes.Structure):
            _fields_ = [("Numerator", wt.UINT), ("Denominator", wt.UINT)]

        class _PATH_TARGET(ctypes.Structure):
            _fields_ = [
                ("adapterId", _LUID),
                ("id", wt.UINT),
                ("modeInfoIdx", wt.UINT),
                ("outputTechnology", wt.UINT),
                ("rotation", wt.UINT),
                ("scaling", wt.UINT),
                ("refreshRate", _RATIONAL),
                ("scanLineOrdering", wt.UINT),
                ("targetAvailable", wt.BOOL),
                ("statusFlags", wt.UINT),
            ]

        class _PATH_INFO(ctypes.Structure):
            _fields_ = [
                ("sourceInfo", _PATH_SOURCE),
                ("targetInfo", _PATH_TARGET),
                ("flags", wt.UINT),
            ]

        class _MODE_INFO(ctypes.Structure):
            _fields_ = [
                ("infoType", wt.UINT),
                ("id", wt.UINT),
                ("adapterId", _LUID),
                ("body", ctypes.c_byte * 48),
            ]

        class _DEVICE_INFO_HEADER(ctypes.Structure):
            _fields_ = [("type", wt.UINT), ("size", wt.UINT), ("adapterId", _LUID), ("id", wt.UINT)]

        class _ADV_COLOR_INFO(ctypes.Structure):
            _fields_ = [
                ("header", _DEVICE_INFO_HEADER),
                ("value", wt.UINT),
                ("colorEncoding", wt.UINT),
                ("bitsPerColorChannel", wt.UINT),
            ]

        user32 = ctypes.windll.user32
        n_path = wt.UINT(0)
        n_mode = wt.UINT(0)
        QDC_ONLY_ACTIVE_PATHS = 0x2
        if (
            user32.GetDisplayConfigBufferSizes(
                QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_path), ctypes.byref(n_mode)
            )
            != 0
        ):
            return False
        if n_path.value <= 0:
            return False
        paths = (_PATH_INFO * n_path.value)()
        modes = (_MODE_INFO * max(1, n_mode.value))()
        if (
            user32.QueryDisplayConfig(
                QDC_ONLY_ACTIVE_PATHS,
                ctypes.byref(n_path),
                paths,
                ctypes.byref(n_mode),
                modes,
                None,
            )
            != 0
        ):
            return False
        GET_ADVANCED_COLOR_INFO = 9
        for i in range(n_path.value):
            info = _ADV_COLOR_INFO()
            info.header.type = GET_ADVANCED_COLOR_INFO
            info.header.size = ctypes.sizeof(_ADV_COLOR_INFO)
            info.header.adapterId = paths[i].targetInfo.adapterId
            info.header.id = paths[i].targetInfo.id
            if (
                user32.DisplayConfigGetDeviceInfo(ctypes.byref(info)) == 0 and info.value & 0x2
            ):  # 位0=支持, 位1=已启用
                return True
        return False
    except Exception:
        return False


def is_black_frame(pm: QPixmap, ratio=0.985) -> bool:
    """判定整帧是否几乎全黑（UIPI 受限 / 独占全屏 / HDR 混合模式的典型表现）。

    网格采样（约 32×32 点），非黑点占比超过 (1-ratio) 即认为不是黑屏；异常返回 False。
    """
    try:
        img = pm.toImage()
        if img.isNull() or img.width() < 16 or img.height() < 16:
            return False
        if img.format() != QImage.Format_RGB888:
            img = img.convertToFormat(QImage.Format_RGB888)
        w, h = img.width(), img.height()
        ptr = img.constBits()
        try:
            raw = ptr.asarray(img.sizeInBytes())
        except AttributeError:
            raw = bytes(ptr)
        import numpy as np

        arr = np.frombuffer(raw, dtype=np.uint8, count=img.sizeInBytes())
        arr = arr.reshape(h, img.bytesPerLine())[:, : w * 3].reshape(h, w, 3)
        sy = max(1, h // 32)
        sx = max(1, w // 32)
        sample = arr[::sy, ::sx]
        return float((sample == 0).all(axis=2).mean()) >= ratio
    except Exception:
        return False
