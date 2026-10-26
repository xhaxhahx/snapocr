# -*- coding: utf-8 -*-
"""轻量 i18n：zh 主语言，en 兜底。"""

import os

_ZH = {
    "capture": "截屏",
    "settings": "设置",
    "about": "关于",
    "exit": "退出",
    "autostart": "开机自动启动",
    "hotkey": "截屏快捷键",
    "hotkey_conflict": "快捷键注册失败，可能已被其他程序占用，请在设置中更换。",
    "hotkey_unsupported": "不支持的按键",
    "hotkey_no_display": "无法打开 X Display",
    "hotkey_x11_fail": "无法加载 libX11",
    "unhandled_error": "程序遇到未处理的错误，详情见日志文件。",
    "hotkey_changed": "截屏快捷键已生效：{}",
    "ocr": "OCR识别",
    "copy": "复制图片",
    "save": "另存为",
    "edit": "编辑",
    "cancel": "取消",
    "done": "完成",
    "undo": "撤销",
    "redo": "重做",
    "tool_pen": "画笔",
    "tool_highlight": "涂色",
    "tool_text": "文字",
    "tool_rect": "矩形",
    "tool_ellipse": "椭圆",
    "tool_arrow": "箭头",
    "tool_mosaic": "马赛克",
    "width_thin": "细",
    "width_medium": "中",
    "width_thick": "粗",
    "width_bold": "加粗",
    "width_hint": "粗度",
    "text_size_hint": "字号",
    "font_hint": "字体",
    "text_weight_hint": "字重",
    "weight_light": "细体",
    "weight_normal": "常规",
    "weight_bold": "粗体",
    "ocr_running": "正在识别…",
    "ocr_result": "OCR 识别结果",
    "ocr_copy_text": "复制文本",
    "ocr_save_txt": "保存",
    "ocr_retry": "重新识别",
    "ocr_empty": "未识别到文字",
    "ocr_lines": "{} 行 / {} 字 / 耗时 {:.1f}s",
    "ocr_locating": "正在定位文字…",
    "wrap_join": "整段",
    "wrap_sentence": "按句换行",
    "wrap_original": "原图换行",
    "wrap_button": "格式化换行",
    "wrap_hint": "当前：{0} · 点击切换为「{1}」",
    "ocr_found": "找到 {} 处文字，正在识别…",
    "ocr_progress": "识别中 {}/{}",
    "copied": "已复制到剪贴板",
    "saved": "已保存：{}",
    "save_failed": "保存失败：{}",
    "ocr_failed": "识别失败：{}",
    "ocr_busy": "正在加载识别引擎，请稍候…",
    "select_hint": "拖动鼠标框选区域，Enter/双击确认，Esc 取消",
    "confirm_selection": "确认",
    "model_missing": "未找到 OCR 模型文件（{}），请检查 resources/models 目录。",
    "engine_error": "识别引擎加载失败：{}",
    "settings_title": "设置 - 截图工具",
    "save_dir": "默认保存目录",
    "browse": "浏览…",
    "ocr_group": "OCR 选项",
    "use_cls": "自动纠正文字方向（推荐）",
    "small_scale": "小字号放大倍数",
    "threads": "识别线程数（0=自动，≤4）",
    "ui_group": "界面",
    "language": "语言 / Language",
    "lang_default": "中文（跟随系统默认）",
    "default_filename": "截图_%s.png",
    "default_txt_filename": "OCR_文本_%s.txt",
    "default_filename_jpg": "截图_%s.jpg",
    "copy_file": "复制为jpg文件",
    "copy_file_img_tip": "把标注图复制为JPG文件到剪贴板（粘贴到资源管理器/聊天窗口即得文件）",
    "copy_as_file": "复制为文件",
    "copy_as_jpg": "复制为jpg文件",
    "copy_as_txt_file": "复制为TXT文件",
    "filename_label": "文件名",
    "copied_as_file": "已复制文件：{}",
    "copy_file_failed": "复制为文件失败：{}",
    "ok": "确定",
    "apply": "应用",
    "close": "关闭",
    "tray_tip": "截图工具 - 点击图标截屏，{} 呼出",
    "first_run_tip": "点击托盘图标或按 {} 即可框选截屏，框选后可 OCR 识别",
    "text_input_hint": "输入文字，Ctrl+Enter 或点击空白处完成",
    "pixelated_none": "马赛克底图生成失败",
    "color": "颜色",
    "current_color": "当前颜色",
    "hotkey_hint": "点击后直接按键盘录入，Esc 清空",
    "preview_title": "截图预览",
    "preview_copy": "复制图片",
    "preview_save": "另存",
    "preview_retry": "重试",
    "preview_cancel": "取消",
    "about_text": "{0} v{1}\n\n开发单位：中共枣庄市委组织部\n\n"
    "完全离线的截图 + 文字识别工具（RapidOCR · PP-OCRv6 · 本地推理）",
    "windows_hint_wayland": "Wayland 会话：请把命令 snapocr --capture 绑定为系统自定义快捷键",
    "clear": "清空",
    "tool_eraser": "橡皮擦",
    "startup_group": "启动",
    "settings_saved": "设置已保存",
    "restore_defaults": "恢复默认",
    "mosaic_block": "马赛克块大小",
    "release_after_ocr": "识别后释放模型（省内存，下次稍慢）",
    "shortcuts": "快捷键",
    "shortcuts_text": "截屏：{0}\n\n"
    "编辑器内：Ctrl+C 复制 · Ctrl+S 保存 · Ctrl+Z 撤销 · Ctrl+Y 重做\n"
    "框选：Enter / 双击 完成 · Esc 取消 · 右键 取消",
    "copy_failed": "复制失败：剪贴板被其他程序占用，请稍后重试",
    "autostart_failed": "开机自启设置失败：可能被安全软件拦截或系统策略限制。",
    "tray_unavailable": "系统托盘当前不可用（资源管理器异常时会出现）。程序以后台模式运行，"
    "快捷键仍可使用；托盘恢复后图标会自动出现。",
    "capture_admin_hint": "截到全黑图：目标窗口可能以管理员身份运行，"
    "请以管理员身份重启本程序后重试。",
    "capture_black_hint": "检测到全黑画面：独占全屏或 HDR 模式可能无法捕获，"
    "请改用窗口模式或关闭 HDR。",
    "capture_hdr_hint": "检测到已启用 HDR 的显示器：截图可能偏亮发白，如需精确色彩请临时关闭 HDR。",
    "rdp_hint": "检测到远程会话：全局热键可能被本地计算机拦截，请使用托盘点击截屏。",
    "ocr_model_loaded": "模型已加载（{:.1f}s），正在识别…",
}

_EN = {
    "capture": "Capture",
    "settings": "Settings",
    "about": "About",
    "exit": "Exit",
    "autostart": "Start with system",
    "hotkey": "Capture hotkey",
    "hotkey_conflict": "Hotkey registration failed (may be in use). Choose another in Settings.",
    "hotkey_unsupported": "Unsupported key",
    "hotkey_no_display": "Cannot open X Display",
    "hotkey_x11_fail": "Cannot load libX11",
    "unhandled_error": "An unexpected error occurred. See log file for details.",
    "hotkey_changed": "Hotkey active: {}",
    "ocr": "OCR",
    "copy": "Copy image",
    "save": "Save as",
    "edit": "Edit",
    "cancel": "Cancel",
    "done": "Done",
    "undo": "Undo",
    "redo": "Redo",
    "tool_pen": "Pen",
    "tool_highlight": "Highlighter",
    "tool_text": "Text",
    "tool_rect": "Rectangle",
    "tool_ellipse": "Ellipse",
    "tool_arrow": "Arrow",
    "tool_mosaic": "Mosaic",
    "width_thin": "Thin",
    "width_medium": "Medium",
    "width_thick": "Thick",
    "width_bold": "Bold",
    "width_hint": "Stroke width",
    "text_size_hint": "Font size",
    "font_hint": "Font",
    "text_weight_hint": "Font weight",
    "weight_light": "Light",
    "weight_normal": "Regular",
    "weight_bold": "Bold",
    "ocr_running": "Recognizing…",
    "ocr_result": "OCR Result",
    "ocr_copy_text": "Copy text",
    "ocr_save_txt": "Save",
    "ocr_retry": "Re-run",
    "ocr_empty": "No text recognized",
    "ocr_lines": "{} lines / {} chars / {:.1f}s",
    "ocr_locating": "Locating text…",
    "wrap_join": "One block",
    "wrap_sentence": "By sentence",
    "wrap_original": "As in image",
    "wrap_button": "Reformat",
    "wrap_hint": "Current: {0} · click to switch to {1}",
    "ocr_found": "Found {} text blocks, recognizing…",
    "ocr_progress": "Recognizing {}/{}",
    "copied": "Copied to clipboard",
    "saved": "Saved: {}",
    "save_failed": "Save failed: {}",
    "ocr_failed": "OCR failed: {}",
    "ocr_busy": "Loading OCR engine, please wait…",
    "select_hint": "Drag to select. Enter/double-click to confirm, Esc to cancel",
    "confirm_selection": "OK",
    "model_missing": "OCR model not found ({}). Check resources/models.",
    "engine_error": "Engine load failed: {}",
    "settings_title": "Settings - Screenshot Tool",
    "save_dir": "Default save folder",
    "browse": "Browse…",
    "ocr_group": "OCR options",
    "use_cls": "Auto text direction (recommended)",
    "small_scale": "Small-text upscale",
    "threads": "Inference threads (0=auto, ≤4)",
    "ui_group": "Interface",
    "language": "Language / 语言",
    "lang_default": "Follow system",
    "default_filename": "screenshot_%s.png",
    "default_txt_filename": "ocr_text_%s.txt",
    "default_filename_jpg": "screenshot_%s.jpg",
    "copy_file": "Copy as JPG file",
    "copy_file_img_tip": "Copy the annotated image as a JPG file to the clipboard",
    "copy_as_file": "Copy as file",
    "copy_as_jpg": "Copy as JPG file",
    "copy_as_txt_file": "Copy as TXT file",
    "filename_label": "File name",
    "copied_as_file": "File copied: {}",
    "copy_file_failed": "Copy as file failed: {}",
    "ok": "OK",
    "apply": "Apply",
    "close": "Close",
    "tray_tip": "Screenshot Tool - click to capture, {} for hotkey",
    "first_run_tip": "Click tray icon or press {} to capture, then OCR",
    "text_input_hint": "Type text; Ctrl+Enter or click empty area to finish",
    "pixelated_none": "Failed to build mosaic base",
    "color": "Color",
    "current_color": "Current color",
    "hotkey_hint": "Press keys to record; Esc clears",
    "preview_title": "Preview",
    "preview_copy": "Copy image",
    "preview_save": "Save",
    "preview_retry": "Retry",
    "preview_cancel": "Cancel",
    "about_text": "{0} v{1}\n\nDeveloped by 中共枣庄市委组织部 "
    "(CPZZ Zaozhuang Organization Dept.)\n\n"
    "Fully offline screenshot + OCR (RapidOCR · PP-OCRv6 · on-device)",
    "windows_hint_wayland": "Wayland: bind 'snapocr --capture' as a system custom shortcut",
    "clear": "Clear",
    "tool_eraser": "Eraser",
    "startup_group": "Startup",
    "settings_saved": "Settings saved",
    "restore_defaults": "Restore defaults",
    "mosaic_block": "Mosaic block size",
    "release_after_ocr": "Release model after OCR (saves RAM, slower next run)",
    "shortcuts": "Shortcuts",
    "shortcuts_text": "Capture: {0}\n\n"
    "Editor: Ctrl+C copy · Ctrl+S save · Ctrl+Z undo · Ctrl+Y redo\n"
    "Select: Enter / double-click done · Esc cancel · right-click cancel",
    "copy_failed": "Copy failed: clipboard is locked by another app, please retry",
    "autostart_failed": "Failed to set autostart: blocked by security software or system policy.",
    "tray_unavailable": "System tray is unavailable (happens when Explorer restarts). "
    "The app keeps running in background and the hotkey still works; "
    "the icon reappears once the tray recovers.",
    "capture_admin_hint": "Captured an all-black image: the target window may be running as "
    "administrator. Restart this app as administrator and retry.",
    "capture_black_hint": "All-black frame detected: exclusive fullscreen or HDR mode may not be "
    "capturable. Switch to windowed mode or turn off HDR.",
    "capture_hdr_hint": "HDR display detected: screenshots may look washed out / over-bright. "
    "Turn off HDR temporarily for accurate colors.",
    "rdp_hint": "Remote session detected: the global hotkey may be captured by the local machine. "
    "Use the tray icon to capture instead.",
    "ocr_model_loaded": "Model loaded ({:.1f}s), recognizing…",
}

_LANGS = {"zh": _ZH, "en": _EN}
_current = "zh"


def _system_lang() -> str:
    """系统语言（语言码，如 "zh_CN" / "en_US"）；取不到返回空串。

    不用 `locale.getdefaultlocale()`——Python 3.11 起弃用、3.15 移除（官方
    deprecations 清单 gh-90817）。也不用 `locale.getlocale(LC_CTYPE)`：进程未
    setlocale 时它恒为 "C"，会把英文系统误判成中文（而 setlocale 有全局副作用）。
    这里复刻 getdefaultlocale 的实际判定顺序，且不产生任何全局状态：
    1) POSIX 环境变量（LC_ALL > LC_CTYPE > LANG），与 getdefaultlocale 一致；
    2) 无环境变量（典型 Windows）时用 QLocale.system()（Qt 官方，走系统 API）。
    """
    for env in ("LC_ALL", "LC_CTYPE", "LANG"):
        val = os.environ.get(env)
        if val:
            return val
    try:
        from PyQt5.QtCore import QLocale

        return QLocale.system().name() or ""
    except Exception:
        return ""


def init_lang(cfg_lang: str):
    global _current
    if cfg_lang in ("zh", "en"):
        _current = cfg_lang
    else:
        loc = _system_lang()
        _current = "en" if loc.lower().startswith("en") else "zh"
    _apply_qt_translations()


_qt_translator = None


def _apply_qt_translations():
    """按当前语言装载 Qt 原生控件翻译（QInputDialog 按钮、编辑控件右键菜单等）。

    qtbase_zh_CN.qm 取自 Qt 官方翻译（PySide6 wheel 同源，147KB，离线随 resources
    分发）；英文是源语言无需装载。文件缺失/无 QApplication 时失败安全跳过。
    打包瘦身的 translations 剔除口径不受影响：那剔的是 Qt 插件目录死重量，这里是
    单个应用资源（resources/qt-i18n，2026-10-26 增）。"""
    global _qt_translator
    try:
        from PyQt5.QtCore import QTranslator
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        if _qt_translator is not None:
            app.removeTranslator(_qt_translator)
            _qt_translator = None
        if _current != "zh":
            return
        qm = os.path.join(_resources_dir(), "qt-i18n", "qtbase_zh_CN.qm")
        t = QTranslator()
        if os.path.isfile(qm) and t.load(qm):
            _qt_translator = t
            app.installTranslator(t)
    except Exception:
        # 翻译装载失败只影响原生控件文案，不阻断启动
        pass


def _resources_dir():
    from .paths import resources_dir

    return resources_dir()


def tr(key: str, *args) -> str:
    table = _LANGS.get(_current, _ZH)
    s = table.get(key) or _ZH.get(key) or key
    if args:
        try:
            return s.format(*args)
        except Exception:
            return s
    return s
