# -*- coding: utf-8 -*-
"""应用装配：托盘、热键、截屏控制器、OCR 调度、设置窗口。"""

import contextlib
import os

from PyQt5.QtCore import QEvent, QObject, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QGuiApplication, QIcon
from PyQt5.QtWidgets import QApplication, QLabel, QMenu, QMessageBox, QSystemTrayIcon

from . import APP_DISPLAY
from .config import Config
from .i18n import tr
from .ocr import engine as ocr_engine
from .ocr.worker import OcrWorker
from .platform.capture import (
    grab_screen_pixmap,
    is_black_frame,
    is_elevated,
    is_hdr_active,
    is_remote_session,
    is_wayland,
)
from .ui import icons, theme
from .ui.result_window import ResultWindow
from .ui.settings_dialog import SettingsDialog
from .utils.logger import get_logger

log = get_logger()

# 平台热键
if os.name == "nt":
    from .platform.hotkey_win import HotkeyManager
else:
    from .platform.hotkey_linux import HotkeyManager


class ToastLabel(QLabel):
    """屏幕中下方的轻提示。"""

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.X11BypassWindowManagerHint,
        )
        self.setStyleSheet(
            "background: rgba(24,26,30,225); color: #fff; border-radius: 8px;"
            "padding: 9px 18px; font-size: 13px;"
        )
        self.setScaledContents(False)

    def pop(self, text, screen=None, msec=1600):
        self.setText(text)
        self.adjustSize()
        scr = screen or QApplication.primaryScreen()
        g = scr.availableGeometry()
        self.move(g.left() + (g.width() - self.width()) // 2, g.bottom() - self.height() - 60)
        self.show()
        self.raise_()
        QTimer.singleShot(msec, self.hide)


class CaptureController(QObject):
    """一次截屏会话：多屏遮罩 → 选区 → 编辑/OCR。"""

    ocrBusy = pyqtSignal(bool)  # OCR 推理进行中
    ocrPanel = pyqtSignal(bool)  # 识别结果面板开/合（遮罩按钮同步激活态）

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.overlays = []
        self.result = None
        self.worker = None
        self._hiding = []

    # ---------- 截屏 ----------
    def start_capture(self):

        log.info("start_capture enter overlays=%s", len(self.overlays))
        if self.overlays:
            return  # 已在进行
        # 隐藏自家窗口，避免被截进去
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and w is not self.app.toast:
                w.hide()
                self._hiding.append(w)
        QApplication.processEvents()
        overlays = []
        first_pm = None
        for scr in QGuiApplication.screens():
            pm = grab_screen_pixmap(scr)
            log.info("grab screen=%s size=%s null=%s", scr.name(), pm.size(), pm.isNull())
            if pm.isNull():
                log.warning("屏幕抓取失败: %s", scr.name())
                continue
            if first_pm is None:
                first_pm = pm
            from .ui.overlay import OverlayWindow

            ov = OverlayWindow(scr, pm, cfg=self.app.cfg, ocr_busy_signal=self.ocrPanel)
            ov.ocrRequested.connect(self.toggle_ocr)
            ov.selectionMoved.connect(self._on_selection_moved)
            ov.finished.connect(self._on_finished)
            ov.cancelled.connect(self._on_finished)
            overlays.append(ov)
        if not overlays:
            self._restore_windows()
            msg = "屏幕抓取失败。"
            if os.name == "nt" and not is_elevated():
                msg += "\n" + tr("capture_admin_hint")
            QMessageBox.warning(None, APP_DISPLAY, msg)
            return
        self.overlays = overlays
        for ov in overlays:
            ov.start()
        hint = self._capture_hint(first_pm)
        if hint:
            QTimer.singleShot(280, lambda: self._show_capture_hint(overlays, hint))
        log.info("start_capture started %d overlays", len(overlays))

    def _capture_hint(self, pm):
        """抓屏环境提示：全黑帧（UIPI 未提权 / 独占全屏 / HDR）或 HDR 过曝。"""
        try:
            if pm is not None and is_black_frame(pm):
                if os.name == "nt" and not is_elevated():
                    return tr("capture_admin_hint")
                return tr("capture_black_hint")
            if is_hdr_active() and not getattr(self.app, "_hdr_warned", False):
                self.app._hdr_warned = True
                return tr("capture_hdr_hint")
        except Exception:
            # 探测失败只是不提示（黑屏/HDR 判定是尽力而为），不影响抓屏主流程
            pass
        return None

    @staticmethod
    def _show_capture_hint(overlays, hint):
        """把提示贴在主屏遮罩的 toast 上（遮罩覆盖全屏，独立 toast 会被它压住）。"""
        if not overlays:
            return
        primary = QGuiApplication.primaryScreen()
        target = next((o for o in overlays if o.screen is primary), overlays[0])
        with contextlib.suppress(Exception):
            target._toast(hint)

    def _close_overlays(self):
        for ov in self.overlays:
            ov.hide()
            ov.release_buffers()  # 立即释放抓屏缓冲（4K 双屏可达数百 MB）
            ov.deleteLater()
        self.overlays = []
        self._restore_windows()

    def _restore_windows(self):
        for w in self._hiding:
            if w is self.result:
                continue
            # 会话期间被用户关掉的窗口，其 C++ 对象可能已销毁：PyQt 对已删除对象
            # 调 show() 会抛 RuntimeError（概率低但路径真实），守卫后跳过即可。
            with contextlib.suppress(RuntimeError):
                w.show()
        self._hiding = []

    def _on_finished(self):
        """截屏会话结束（取消 / 完成 / 复制 / 保存）。会话结束即收掉结果窗。"""
        if self.result is not None:
            self.result.close()  # 会话结束不留孤儿结果窗
        self._close_overlays()
        self._maybe_quit_once()

    # ---------- 用完即走（--once / 单文件版默认） ----------
    def _maybe_quit_once(self):
        """once 模式下，当没有任何截屏相关窗口时自动退出。"""
        if not getattr(self.app, "once", False):
            return

        def check():
            if self.overlays:
                return
            if self.result is not None and self.result.isVisible():
                return
            self._flush_clipboard()
            # X11 剪贴板是"所有权"模型：源进程退出即失效，太快退出会粘出空内容
            # （deepin-screenshot 同款补丁即加退出延迟）；顺带让"已复制/已保存"toast 能被看清
            QTimer.singleShot(600, self.app.quit)

        QTimer.singleShot(250, check)

    @staticmethod
    def _flush_clipboard():
        """退出前把剪贴板数据真正交接到系统剪贴板（Windows 触发 OleFlushClipboard，X11 同步）。"""
        try:
            cb = QGuiApplication.clipboard()
            QApplication.sendEvent(cb, QEvent(QEvent.Clipboard))
        except Exception:
            # 剪贴板交接是尽力而为：失败不影响退出
            pass

    def _shutdown_ocr(self):
        """退出前优雅等待 OCR 线程结束，避免 QThread: Destroyed while running 与结果丢失。"""
        w = self.worker
        if w is not None and w.isRunning():
            w.wait(2000)

    # ---------- OCR ----------
    _last_input = None

    def toggle_ocr(self, img, anchor_rect=None, screen=None):
        """点「OCR识别」= 打开或关闭识别窗口（简单切换）。"""
        screen = screen or QApplication.primaryScreen()
        if self.result is not None and self.result.isVisible():
            self.result.hide()
            self.ocrPanel.emit(False)
            return
        self.run_ocr(img, anchor_rect, screen)

    def run_ocr(self, img, anchor_rect=None, screen=None):
        screen = screen or QApplication.primaryScreen()
        self._last_input = img
        if self.worker is not None:
            # ok/fail 派发完才置 None，比 isRunning() 语义更准（避免刚出结果时状态闪旧值）
            self.app.toast.pop(tr("ocr_running"), screen)
            return
        created = False
        if self.result is None:
            created = True
            self.result = ResultWindow(cfg=self.app.cfg)
            self.result.rerunRequested.connect(self._rerun)
            self.result.closed.connect(self._result_closed)
        elif not self.result.isVisible():
            self.result.show()
        self.result.begin_stream()
        if created:
            # 仅首次定位；点「重新识别」时窗口原地不动，只刷新文字
            self.result.show_near(anchor_rect or QRectF(0, 0, 0, 0), screen)
        # 置顶到遮罩之上，保证可见
        self.result.raise_()
        self.result.activateWindow()
        self.ocrPanel.emit(True)
        self.worker = OcrWorker(self.app.cfg, img, self)
        self.worker.ok.connect(self._ocr_ok)
        self.worker.fail.connect(self._ocr_fail)
        self.worker.loaded.connect(self._ocr_loaded)
        # 流式反馈：det 完成 → 告知框数；每识别一条 → 追加一行
        self.worker.found.connect(self._ocr_found)
        self.worker.partial.connect(self._ocr_partial)
        # 关键：线程对象随 finished 回收，否则每次 OCR 泄漏 1 个 QThread + 1 张截图
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()
        self.ocrBusy.emit(True)

    def _ocr_loaded(self, secs):
        """引擎首次加载完成：把「正在加载模型」更新为「模型已加载（Ns），正在识别」。"""
        if self.result is not None:
            self.result.set_busy(secs)

    def _ocr_found(self, total):
        """det 完成：告知找到的文本框数量。这是整条流水线中最早可用的真实进度信号。"""
        if self.result is not None:
            self.result.stream_found(total)

    def _ocr_partial(self, text, done, total):
        """逐框识别进度：追加一行并更新「识别中 n/N」。"""
        if self.result is not None:
            self.result.stream_line(text, done, total)

    def _ocr_ok(self, results, elapsed):
        if self.result:
            self.result.set_results(results, elapsed)
        self.worker = None
        self.ocrBusy.emit(False)
        self._maybe_release_engine()

    def _ocr_fail(self, msg):
        if self.result:
            self.result.set_error(msg)
        self.worker = None
        self.ocrBusy.emit(False)
        self._maybe_release_engine()

    def _maybe_release_engine(self):
        """低配机可选：识别后释放模型常驻内存（下次识别重新加载，稍慢）。"""
        try:
            if self.app.cfg.get("ocr_release_after", False):
                ocr_engine.release_engine()
        except Exception:
            # 释放失败（线程仍占用等）不阻断退出流程
            pass

    def _rerun(self):
        """结果窗「重新识别」：原地重跑最近一次输入。"""
        if self._last_input is not None:
            screen = QApplication.primaryScreen()
            self.run_ocr(self._last_input, None, screen)

    def _on_selection_moved(self):
        """移动选区 = 重新取景，结果窗直接关闭（按钮状态同步）。"""
        if self.result is not None:
            self.result.close()  # 触发 _result_closed → ocrPanel(False)

    def _result_closed(self):
        self.result = None
        self.ocrPanel.emit(False)
        self._maybe_quit_once()


class SnapApp(QObject):
    commandReceived = pyqtSignal(list)

    def __init__(self, show_tip=True, once=False):
        super().__init__()
        self.once = bool(once)  # 用完即走模式（--once / 单文件版默认）
        self.cfg = Config()
        self.toast = ToastLabel()
        self.controller = CaptureController(self)

        # 托盘（线稿相机按物理像素渲染，随主题反色，贴近系统托盘图标风格）
        self.tray = QSystemTrayIcon(self._tray_icon())
        self.tray.setToolTip(tr("tray_tip", self.cfg.get("hotkey")))
        menu = QMenu()
        act_capture = menu.addAction(tr("capture"))
        act_capture.triggered.connect(self.start_capture)
        menu.addSeparator()
        act_settings = menu.addAction(tr("settings"))
        act_settings.triggered.connect(self.open_settings)
        menu.addSeparator()
        act_about = menu.addAction(tr("about"))
        act_about.triggered.connect(self.show_about)
        menu.addSeparator()
        act_exit = menu.addAction(tr("exit"))
        act_exit.triggered.connect(self.quit)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray)
        self.tray.show()

        # 托盘不可用（资源管理器异常、部分 Linux 桌面）：说明"后台运行 + 热键可用"，恢复后自动重现
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("系统托盘不可用，进入后台模式")
            QMessageBox.warning(None, APP_DISPLAY, tr("tray_unavailable"))
        if hasattr(self.tray, "availabilityChanged"):
            self.tray.availabilityChanged.connect(self._on_tray_availability)

        # 远程桌面：全局热键常被本地计算机截走，提示改用托盘点击
        if is_remote_session():
            QTimer.singleShot(
                900,
                lambda: self.tray.showMessage(
                    APP_DISPLAY, tr("rdp_hint"), QSystemTrayIcon.Information, 5000
                ),
            )

        # 屏幕热插拔/休眠唤醒：有活动遮罩会话时重建，避免界面停在旧拓扑上
        self._screen_rebuild = False
        try:
            QGuiApplication.instance().screenAdded.connect(self._on_screens_changed)
            QGuiApplication.instance().screenRemoved.connect(self._on_screens_changed)
        except Exception:
            # 旧 Qt / 无屏幕后端时可能无此信号：跳过即可
            pass

        # 主题：托盘菜单跟随系统深浅色/强调色，实时切换
        from .ui.theme import manager as _theme_mgr

        self._act_capture = act_capture
        self._act_settings = act_settings
        self.retheme(_theme_mgr.theme)
        _theme_mgr.changed.connect(self.retheme)

        # 热键（once 模式生命周期极短，不注册全局热键以免与常驻软件冲突）
        self.hotkey = HotkeyManager(self)
        self.hotkey.activated.connect(self.start_capture)
        self.hotkey.error.connect(
            lambda m: self.tray.showMessage(APP_DISPLAY, m, QSystemTrayIcon.Warning, 3000)
        )
        if self.once:
            log.info("once 模式：跳过全局热键注册")
        else:
            self._apply_hotkey()

        # 单实例命令
        self.commandReceived.connect(self._on_command)

        if show_tip:
            QTimer.singleShot(
                800,
                lambda: self.tray.showMessage(
                    APP_DISPLAY,
                    tr("first_run_tip", self.cfg.get("hotkey")),
                    QSystemTrayIcon.Information,
                    4000,
                ),
            )

    # ---------- 行为 ----------
    def _tray_icon(self):
        """托盘图标：与应用图标同一枚（深底 + 蓝色虚线取景框 + 剪刀），
        按任务栏实际物理像素渲染，保证 1080p/2K 缩放下都不糊。"""
        from PyQt5.QtWidgets import QApplication, QStyle

        scr = QGuiApplication.primaryScreen()
        dpr = (scr.devicePixelRatio() or 1.0) if scr else 1.0
        base = QApplication.style().pixelMetric(QStyle.PM_SmallIconSize)
        size = max(16, int(base * dpr))
        return QIcon(icons.pixmap("app", size=size))

    def retheme(self, t):
        # 托盘菜单不放图标（用户要求：纯文字，风格干净）
        self.menu.setStyleSheet(theme.qss_menu(t))
        # 托盘图标与应用图标同一枚，自带深底故不再随主题反色
        self.tray.setIcon(self._tray_icon())

    def show_about(self):
        from . import __version__

        QMessageBox.about(None, tr("about"), tr("about_text", APP_DISPLAY, __version__))

    def _on_tray_availability(self, available):
        """托盘恢复（如资源管理器重启）后重新显示图标。"""
        if available:
            try:
                self.tray.show()
                self.tray.setIcon(self._tray_icon())
            except Exception:
                # 托盘对象可能已销毁（资源管理器重启期间）：忽略
                pass

    def _on_screens_changed(self, *_):
        """屏幕拓扑变化：仅在有活动遮罩会话时重建（带防抖，避免信号风暴）。"""
        if not self.controller.overlays or self._screen_rebuild:
            return
        self._screen_rebuild = True
        log.info("屏幕数量变化：重建截屏遮罩")
        QTimer.singleShot(250, self._rebuild_overlays)

    def _rebuild_overlays(self):
        self._screen_rebuild = False
        self.controller._close_overlays()
        QTimer.singleShot(150, self.start_capture)

    def _on_tray(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.start_capture()

    def start_capture(self):
        self.controller.start_capture()

    def open_settings(self):
        if getattr(self, "_settings", None) is not None:
            self._settings.show()
            self._settings.raise_()
            return
        s = SettingsDialog(self.cfg)
        s.settingsApplied.connect(self._settings_applied)
        self._settings = s
        s.show()

    def _settings_applied(self, hotkey_changed):
        self._apply_hotkey()
        self.tray.setToolTip(tr("tray_tip", self.cfg.get("hotkey")))
        if hotkey_changed:
            self.tray.showMessage(
                APP_DISPLAY,
                tr("hotkey_changed", self.cfg.get("hotkey")),
                QSystemTrayIcon.Information,
                2500,
            )
        else:
            self.tray.showMessage(
                APP_DISPLAY, tr("settings_saved"), QSystemTrayIcon.Information, 2500
            )
        if getattr(self, "_settings", None):
            self._settings.deleteLater()
            self._settings = None

    def _apply_hotkey(self):
        ok = self.hotkey.register(self.cfg.get("hotkey"))
        if not ok:
            log.info("热键注册失败: %s", self.cfg.get("hotkey"))
        if os.name != "nt" and not ok and is_wayland():
            log.info(tr("windows_hint_wayland"))

    def _on_command(self, args):

        log.info("ipc command: %s", args)
        a = args or []
        if not a or "--capture" in a:  # 空命令（如直接双击 exe）也按截屏处理
            self.start_capture()
        elif "--settings" in a:
            self.open_settings()
        elif "--exit" in a:
            self.quit()

    def quit(self):
        with contextlib.suppress(Exception):
            self.hotkey.unregister()
            self.tray.hide()
        # 识别中点退出：先优雅等待工作线程收尾，再退出（避免强杀丢结果/线程警告）
        with contextlib.suppress(Exception):
            self.controller._shutdown_ocr()
        QApplication.quit()
