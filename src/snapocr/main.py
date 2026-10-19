# -*- coding: utf-8 -*-
"""入口：参数解析、HighDPI、单实例、日志、异常钩子。

用法:
  snapocr                常驻托盘
  snapocr --capture      呼出框选（可绑定到系统快捷键）
  snapocr --settings     打开设置
  snapocr --hidden       常驻但不弹首次提示
  snapocr --selftest     运行自检
  snapocr --bench        OCR 基准测试
"""

import contextlib
import os
import sys


def _setup_qt_plugin_path():
    """PyQt5 wheel 在含中文的安装路径下无法自动定位 Qt 插件目录，显式指定。

    兼容三种布局：venv/site-packages(PyQt5/Qt5/plugins)、
    PyInstaller onedir(PyQt5/Qt5/plugins 或 PyQt5/Qt/plugins)。
    """
    try:
        import PyQt5
    except Exception:
        return
    base = os.path.dirname(os.path.abspath(PyQt5.__file__))
    for sub in (("Qt5", "plugins"), ("Qt", "plugins")):
        p = os.path.join(base, *sub)
        if os.path.isdir(os.path.join(p, "platforms")):
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", os.path.join(p, "platforms"))
            os.environ.setdefault("QT_PLUGIN_PATH", p)
            return


_setup_qt_plugin_path()


def main():
    args = list(sys.argv[1:])

    if "--version" in args:
        from . import __version__

        print("SnapOCR", __version__)
        return 0
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    # HighDPI 必须在 QApplication 之前
    from PyQt5.QtCore import QCoreApplication, Qt
    from PyQt5.QtGui import QGuiApplication

    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # 该策略在个别 Qt 5.15 早期补丁版缺失，取不到时保持默认四舍五入
    with contextlib.suppress(Exception):
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    from PyQt5.QtWidgets import QApplication

    from . import APP_DISPLAY, APP_NAME, __version__

    app = QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY)
    app.setOrganizationName("SnapOCR")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)

    from .config import Config
    from .i18n import init_lang

    cfg = Config()
    init_lang(cfg.get("lang"))

    from .utils.logger import get_logger, install_excepthook

    install_excepthook(dialog="--selftest" not in args)
    log = get_logger()
    log.info("启动 %s v%s args=%s", APP_NAME, __version__, args)

    # 主题初始化（必须在自检之前：让 --selftest 走与正常启动完全相同的路径，
    # 避免启动期代码缺陷被自检分支"提前返回"掩盖）
    from .ui import theme

    theme.manager.start_watching()
    app.setFont(theme.app_font())
    # 应用窗口/任务栏图标：填充版相机（开始菜单与 exe 图标同源 app.ico）
    from PyQt5.QtGui import QIcon as _QIcon

    from .paths import resources_dir as _res

    _ico = os.path.join(_res(), "app.ico")
    if os.path.isfile(_ico):
        app.setWindowIcon(_QIcon(_ico))

    # 自检/基准/画廊不走单实例转发，确保总能独立执行
    if "--selftest" in args:
        from .tests.selftest import run_selftest

        return run_selftest(app, cfg)
    if "--gallery" in args:
        from .tests.gallery import run_gallery

        spec = (
            args[args.index("--gallery") + 1]
            if args.index("--gallery") + 1 < len(args)
            and args[args.index("--gallery") + 1] in ("dark", "light", "both")
            else "both"
        )
        return run_gallery(app, cfg, spec)
    if "--bench" in args:
        from .tests.bench import run_bench

        return run_bench(app, cfg)

    # 单实例：已有实例则转发命令
    from .utils.singleinstance import SingleInstance

    si = SingleInstance()

    # --once 用完即走：会话（框选/编辑/结果窗）结束后进程自动退出，不驻托盘。
    # 单文件版默认启用该模式，且双击（无参数）即直接进入截屏。
    frozen_name = os.path.basename(sys.executable).lower() if getattr(sys, "frozen", False) else ""
    is_single_exe = getattr(sys, "frozen", False) and "snapocr-single" in frozen_name
    once = "--once" in args or (is_single_exe and "--resident" not in args)
    if is_single_exe and "--capture" not in args and "--settings" not in args:
        args = [*args, "--capture"]

    state = si.try_connect(args)
    if state != SingleInstance.NO_INSTANCE:
        # FORWARDED=已确认送达；UNCERTAIN=连接建立但 ack 超时（保守视为已转发，避免双开）
        log.info("命令已转发到常驻实例(%s)，退出", state)
        return 0
    # 无实例在跑时 --exit 应当即退出，而不是把常驻实例拉起来（多出一个托盘图标）
    if "--exit" in args:
        log.info("无运行实例，--exit 直接退出")
        return 0

    si.listen()
    from .app import SnapApp

    show_tip = (not once) and "--hidden" not in args and not cfg.get("autostart_shown_tip", False)
    snap = SnapApp(show_tip=show_tip, once=once)
    if show_tip:
        cfg.set("autostart_shown_tip", True)
    # 关键：把单实例收到的命令接到应用处理（此前误接了 SnapApp 自身的同名信号，
    # 导致 --capture 等转发命令被静默丢弃）
    si.commandReceived.connect(snap._on_command)

    # 命令行直呼截屏（本实例即常驻实例）
    if "--capture" in args or "--settings" in args:
        from PyQt5.QtCore import QTimer

        QTimer.singleShot(120, snap.start_capture if "--capture" in args else snap.open_settings)

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
