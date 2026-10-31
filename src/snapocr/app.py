# -*- coding: utf-8 -*-
"""应用装配：托盘、热键、截屏控制器、OCR 调度、设置窗口。"""

import contextlib
import gc
import os
import subprocess
import sys

from PyQt5.QtCore import QEvent, QObject, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QGuiApplication, QIcon, QPixmapCache
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

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
from .ui.preview_dialog import PreviewDialog
from .ui.result_window import ResultWindow
from .ui.settings_dialog import SettingsDialog
from .utils.logger import get_logger
from .utils.memory_watchdog import MemoryWatchdog

log = get_logger()

# 平台热键
if os.name == "nt":
    from .platform.hotkey_win import HotkeyManager
else:
    from .platform.hotkey_linux import HotkeyManager


class ToastLabel(QLabel):
    """屏幕中下方的轻提示（应用内，不产生系统通知，不改变任务栏图标）。"""

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
        self._queue = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

    def pop(self, text, screen=None, msec=1600):
        self._queue.append((text, screen, msec))
        if not self.isVisible() and not self._timer.isActive():
            self._show_next()

    def _show_next(self):
        if not self._queue:
            self.hide()
            return
        text, screen, msec = self._queue.pop(0)
        self.setText(text)
        self.adjustSize()
        scr = screen or QApplication.primaryScreen()
        g = scr.availableGeometry()
        self.move(g.left() + (g.width() - self.width()) // 2, g.bottom() - self.height() - 60)
        self.show()
        self.raise_()
        self._timer.start(msec)

    def _advance(self):
        self._show_next()


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
        self._stale_ocr = False  # 选区已移动：在途识别结果作废（U3）
        self._hiding = []
        self._previews = []  # 存活的预览窗强引用（见 _close_overlays）

    # ---------- 截屏 ----------
    def start_capture(self):
        log.info("start_capture enter overlays=%s", len(self.overlays))
        if self.overlays:
            return  # 已在进行
        # 隐藏自家窗口，避免被截进去
        for w in QApplication.topLevelWidgets():
            if not w.isVisible() or w is self.app.toast:
                continue
            # 钉住的预览窗不隐藏：钉住只表示"不随截图任务关闭"，用户希望它一直
            # 留在屏上（2026-10-28 用户澄清），再次截图时也不该消失。
            if isinstance(w, PreviewDialog) and getattr(w, "pinned", False):
                continue
            w.hide()
            # 用户在会话期间关闭的对话框（如设置窗 Esc/reject）不得在会话结束时
            # 被 _restore_windows 复活：hide 时清标记、closed 后打标记（只对
            # QDialog 有可靠的 closed 语义；其余窗口极少在会话期间被关）。
            if isinstance(w, QDialog):
                w._snap_user_closed = False
                if not getattr(w, "_snap_close_hooked", False):
                    # self._settings 等对话框跨会话存活，只挂一次
                    w._snap_close_hooked = True
                    w.finished.connect(lambda _r, _w=w: setattr(_w, "_snap_user_closed", True))
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
            ov.previewClosed.connect(self._maybe_quit_once)
            ov.raisePinnedRequested.connect(self._raise_pinned_previews)
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
        # 先清掉本类持有的**已关闭**预览窗强引用（上一轮钉住、此后被 × 的窗），
        # 让 sip 正常回收；存活判定放回收之后做补挂，避免把本轮要保留的误清。
        self._previews = [w for w in self._previews if w.isVisible()]
        for ov in self.overlays:
            pv = getattr(ov, "_preview", None)
            # 钉住的预览窗必须由本类**强引用**：PreviewDialog 无父级，PyQt 里归
            # Python 所有——遮罩包装（唯一持引者 ov._preview）随 overlays 清空被
            # 回收时，sip 会静默销毁 C++ 预览窗：无 closeEvent/hideEvent、无
            # deleteLater 可查，表现为"钉住后点复制，预览窗凭空消失"
            # （2026-10-29 插桩实证，复现 3/3）。
            if (
                pv is not None
                and isinstance(pv, PreviewDialog)
                and pv.isVisible()
                and pv not in self._previews
            ):
                self._previews.append(pv)
            # 用 close() 而不是 hide()：遮罩的 closeEvent 负责断开与钉住预览窗的
            # 信号连接、并告知"会话已结束"（禁用重试）。hide() 不触发 closeEvent，
            # 会导致钉住窗后续点击回调到已销毁的遮罩（2026-10-28 客户机崩溃）。
            ov.close()
            ov.release_buffers()  # 立即释放抓屏缓冲（4K 双屏可达数百 MB）
            # destroy() 归还原生 Win32 窗口的 backing store：全屏 1920×1080 遮罩
            # 每次 show/close 泄漏 ~8MB（Commit 内存实测 20 轮 +56MB），仅
            # deleteLater 无法归还（2026-10-28 内存生命周期专项实测 F0/F2）。
            ov.destroy()
            ov.deleteLater()
        self.overlays = []
        self._restore_windows()
        # 会话末顺手软释放（docs/15 L1-b）：OCR/抓屏路径的临时对象多为跨代引用，
        # 不主动 collect 会滞留数轮；QPixmapCache 可能缓存标注/托盘位图。
        gc.collect()
        QPixmapCache.clear()

    def _restore_windows(self):
        for w in self._hiding:
            if w is self.result or getattr(w, "_snap_user_closed", False):
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

    def _preview_closed(self):
        """PreviewDialog.closeEvent 宿主钩子（挂在 QApplication 实例，见 SnapApp）。"""
        # 已关闭的预览窗立即摘出强引用表：其合成 QImage 可达全屏大小（~8MB），
        # 留到下一轮会话结束才清会造成可观的滞留（docs/15 L1-c）。
        self._previews = [w for w in self._previews if w.isVisible()]
        self._maybe_quit_once()

    def _raise_pinned_previews(self):
        """遮罩激活到顶时重提钉住的预览窗，保证其始终前置于遮罩（用户 10-29 需求）。

        仅 raise_（层级内抬升），零分配、零新引用；非钉住预览窗不提——它们
        属于当前会话的确认流，被遮罩盖住是预期行为。
        """
        for w in QApplication.topLevelWidgets():
            if isinstance(w, PreviewDialog) and getattr(w, "pinned", False) and w.isVisible():
                w.raise_()

    def busy(self) -> bool:
        """内存看门狗的"忙碌"判定：任一为真则本轮跳过，绝不清理/重启。

        覆盖：截屏会话（遮罩/结果窗/预览窗/设置窗任一可见）+ OCR 线程在跑。
        """
        if self.overlays or self._hiding:
            return True
        if self.worker is not None and self.worker.isRunning():
            return True
        if self.result is not None and self.result.isVisible():
            return True
        if getattr(self, "_settings", None) is not None and self._settings.isVisible():
            return True
        return any(
            isinstance(w, PreviewDialog) and w.isVisible() for w in QApplication.topLevelWidgets()
        )

    def _soft_release(self):
        """看门狗 L1 软释放：空闲时回收可回收缓存（docs/15 §3）。

        释放引擎是其中最重的一步——空闲态用户无感（下次识别自动重载 ~1.2s）；
        会话中绝不调用（见 busy()）。
        """
        self._previews = [w for w in self._previews if w.isVisible()]
        gc.collect()
        QPixmapCache.clear()
        if ocr_engine.engine_loaded():
            ocr_engine.release_engine()  # 内部自带 gc.collect()

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
            # 钉住的预览窗：截图会话已结束，但用户明确要求窗口保留 → 进程必须留着。
            # 它关闭时 PreviewDialog.closeEvent 发出 closed 信号，宿主在
            # _result_closed/取消链路之外还需再触发一次本判定——目前由
            # once 模式的退出前判定（quit 前）兜底覆盖。
            if any(
                isinstance(w, PreviewDialog) and w.isVisible() and getattr(w, "pinned", False)
                for w in QApplication.topLevelWidgets()
            ):
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
            if not self._stale_ocr:
                self.app.toast.pop(tr("ocr_running"), screen)
                return
            # 选区已移动：旧任务结果作废——切断其 UI 信号后放行新任务（U3），
            # 旧线程自行跑完自然回收（finished→deleteLater 保留），结果不再挡道
            self._detach_worker(self.worker)
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

    def _detach_worker(self, w):
        """丢弃在途识别任务：断开其全部 UI 信号（finished→deleteLater 保留，线程自然收尾）。"""
        with contextlib.suppress(TypeError, RuntimeError):
            w.ok.disconnect(self._ocr_ok)
            w.fail.disconnect(self._ocr_fail)
            w.loaded.disconnect(self._ocr_loaded)
            w.found.disconnect(self._ocr_found)
            w.partial.disconnect(self._ocr_partial)

    def _ocr_ok(self, results, elapsed):
        if self.result:
            self.result.set_results(results, elapsed)
        self.worker = None
        self._stale_ocr = False
        self.ocrBusy.emit(False)
        self._maybe_release_engine()

    def _ocr_fail(self, msg):
        if self.result:
            self.result.set_error(msg)
        self.worker = None
        self._stale_ocr = False
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
        self._stale_ocr = True  # 在途识别针对的是旧取景，结果作废（U3）
        if self.result is not None:
            self.result.close()  # 触发 _result_closed → ocrPanel(False)

    def _result_closed(self):
        self.result = None
        # 结果窗已关，「重新识别」不可达：释放上次识别的输入图（4K 约 24-32MB）（§33.1 A7）
        self._last_input = None
        self.ocrPanel.emit(False)
        self._maybe_quit_once()


class SnapApp(QObject):
    commandReceived = pyqtSignal(list)

    def __init__(self, show_tip=True, once=False):
        super().__init__()
        self.once = bool(once)  # 用完即走模式（--once / 单文件版默认）
        self.cfg = Config()
        # 自启以系统实际状态为准（注册表/桌面项）：安装器按安装页选择改写注册表后，
        # 设置页与之同步（旧装机残留曾致"安装未勾选但设置显示已开启"）
        from .platform.autostart import sync_autostart_cfg

        sync_autostart_cfg(self.cfg)
        self.toast = ToastLabel()
        self.controller = CaptureController(self)
        # PreviewDialog.closeEvent 的宿主钩子挂在 plain QApplication 实例上：
        # 钉住窗寿命长于遮罩，遮罩销毁时其 closeEvent 已断开 closed→previewClosed，
        # 用户此后关闭钉住窗只能经由本钩子触发 once 模式退出重判
        # （此前钩子从未实现——once 模式"关掉钉住窗后进程不退出"，2026-10-29 补齐）。
        QApplication.instance().on_preview_closed = self.controller._preview_closed

        # 内存看门狗（docs/15）：once 模式进程短命，无意义；托盘常驻才需要。
        if not self.once:
            self._watchdog = MemoryWatchdog(
                self,
                cfg_get=self.cfg.get,
                is_busy=self.controller.busy,
                soft_release=self.controller._soft_release,
                do_recycle=self._recycle_self,
            )
            self._watchdog.start()

        # 托盘（线稿相机按物理像素渲染，随主题反色，贴近系统托盘图标风格）
        self.tray = QSystemTrayIcon(self._tray_icon())
        self.tray.setToolTip(self._tray_tip())
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
            QTimer.singleShot(900, lambda: self.toast.pop(tr("rdp_hint"), msec=5000))

        # 屏幕热插拔/休眠唤醒/分辨率热变更：有活动遮罩会话时重建，
        # 避免界面停在旧拓扑或旧几何上（§33.1 A8：同屏改分辨率不触发增删信号）。
        # 重建走"500ms 静默期"：连续变化只在几何稳定后重抓一次——在变化中途重抓会
        # 拿到显示管线过渡期的半成品帧（上缘残条+其余纯黑）。RDP 会话对几何变化
        # 直接忽略（见 _on_screens_changed，2026-10-26 RDP 实测反馈）
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(500)
        self._rebuild_timer.timeout.connect(self._rebuild_overlays)
        try:
            qapp = QGuiApplication.instance()
            qapp.screenAdded.connect(self._on_screen_added)
            qapp.screenRemoved.connect(self._on_screens_changed)
            for _scr in qapp.screens():
                _scr.geometryChanged.connect(self._on_screens_changed)
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
        # 提示走应用内 Toast：系统托盘通知会让 Deepin 任务栏出现黄色“!”通知图标
        self.hotkey.error.connect(lambda m: self.toast.pop(m, msec=5000))
        if self.once:
            log.info("once 模式：跳过全局热键注册")
        else:
            self._apply_hotkey()

        # 单实例命令
        self.commandReceived.connect(self._on_command)

        if show_tip:
            QTimer.singleShot(
                800,
                lambda: self.toast.pop(
                    tr("first_run_tip", self.cfg.get("hotkey"))
                    if self.cfg.get("hotkey")
                    else tr("first_run_tip_nokey"),
                    msec=4000,
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
        """屏幕拓扑/几何变化：有活动遮罩时等 500ms 静默期再重建一次（定时器自重置防风暴）。

        RDP 例外（2026-10-26 实测反馈）：RDP 客户端会随全屏遮罩的出现动态协商
        分辨率，geometryChanged 频发；此时重建后的重抓落在显示管线过渡期，得到
        "上缘残条+其余纯黑"的半成品帧，整个遮罩表现为黑屏。RDP 会话忽略几何
        变化（维持既有抓屏即可），只对屏幕增删（真拓扑变化）重建。
        """
        if not self.controller.overlays:
            return
        if is_remote_session():
            return
        self._rebuild_timer.start()

    def _on_screen_added(self, scr):
        """新屏接入：补挂它的 geometryChanged（分辨率/缩放热变更），再走既有静默期重建。"""
        with contextlib.suppress(Exception):
            scr.geometryChanged.connect(self._on_screens_changed)
        self._on_screens_changed()

    def _rebuild_overlays(self):
        """几何已稳定：关掉旧遮罩并重新取景（150ms 让位窗口收尾）。"""
        if not self.controller.overlays:
            return
        log.info("屏幕拓扑/几何变化已稳定：重建截屏遮罩")
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
        if self.controller.overlays:
            # 截屏会话进行中经 IPC/快捷方式打开：置顶遮罩会盖住普通窗口，
            # 设置窗须临时置顶才可见可交互（U10）；会话结束后照常平铺
            s.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        s.settingsApplied.connect(self._settings_applied)
        self._settings = s
        s.show()

    def _tray_tip(self):
        """托盘 tooltip：有热键与无热键两种文案（空热键不出现空洞占位）。"""
        hk = self.cfg.get("hotkey")
        return tr("tray_tip", hk) if hk else tr("tray_tip_nokey")

    def _settings_applied(self, hotkey_changed):
        self._apply_hotkey()
        self.tray.setToolTip(self._tray_tip())
        if hotkey_changed:
            hk = self.cfg.get("hotkey")
            # 新热键与"清除热键"分别提示（空热键不出现空洞占位）
            self.toast.pop(
                tr("hotkey_changed", hk) if hk else tr("hotkey_cleared"),
                msec=3000,
            )
        else:
            self.toast.pop(tr("settings_saved"), msec=2500)
        if getattr(self, "_settings", None):
            self._settings.deleteLater()
            self._settings = None

    def _apply_hotkey(self):
        seq = self.cfg.get("hotkey") or ""
        ok = self.hotkey.register(seq)
        if not ok and seq:
            # 空热键 = 主动不启用（register 内部直接跳过），不算失败
            log.info("热键注册失败: %s", seq)
        if not ok and os.name != "nt" and is_wayland():
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
        elif "--recycle" in a:  # 自愈通道：手动/看门狗触发的内存整理重启
            self._recycle_self()

    # ---------- 自愈重启（docs/15 L2）----------
    def _recycle_self(self):
        """派生新进程接管后本进程退出：内存回到初始化基线的最终兜底。

        安全性：剪贴板由 quit() 的 OleFlushClipboard 交接给系统；调用方（看门狗/
        --recycle 命令）保证此时无会话、无可见窗口。新进程以 --recycle 等待本进程
        管道消失后再 listen，避免抢名。
        """
        try:
            if getattr(sys, "frozen", False):
                argv = [sys.executable, "--hidden", "--resident", "--recycle"]
            else:
                # 源码运行：python src/run.py --hidden --resident --recycle
                script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "run.py"))
                argv = [sys.executable, script, "--hidden", "--resident", "--recycle"]
            flags = 0
            if os.name == "nt":
                DETACHED_PROCESS = 0x00000008
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(
                argv,
                creationflags=flags,
                close_fds=True,
                cwd=os.path.dirname(os.path.abspath(argv[1] if len(argv) > 2 else argv[0])),
            )
            log.info("自愈重启：新进程已派生 %r", argv)
        except Exception:
            log.exception("自愈重启派生失败——放弃本次回收，看门狗下轮再试")
            return
        self.quit()

    def quit(self):
        with contextlib.suppress(Exception):
            self.hotkey.unregister()
            self.tray.hide()
        # 识别中点退出：先优雅等待工作线程收尾，再退出（避免强杀丢结果/线程警告）
        with contextlib.suppress(Exception):
            self.controller._shutdown_ocr()
        QApplication.quit()
