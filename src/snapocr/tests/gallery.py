# -*- coding: utf-8 -*-
"""UI 回归截图画廊（借鉴 Firefox mozscreenshots 的配置驱动截图）：
自动驱动全部界面状态 × 深/浅主题，存档到 docs/gallery/<theme>/。
用法: python src/run.py --gallery [dark|light|both]
"""

import os
import time


def _set_registry_theme(dark: bool):
    if os.name != "nt":
        return
    try:
        import winreg

        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(k, "AppsUseLightTheme", 0, winreg.REG_DWORD, 0 if dark else 1)
        k.Close()
    except Exception:
        # 测试脚本：主题切换失败不阻断截图生成
        pass


def _broadcast_theme_change():
    if os.name != "nt":
        return
    try:
        import ctypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "ImmersiveColorSet", SMTO_ABORTIFHUNG, 1000, None
        )
    except Exception:
        # 广播失败（无窗口响应）：测试脚本可忽略
        pass


def _read_registry_theme() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        k.Close()
        return int(v) == 0
    except Exception:
        return False


def _fixed_cfg(cfg):
    """画廊基线必须跨机器可复现：所有键固定取 DEFAULTS，不随本机用户配置漂移。

    背景：曾出现 `docs/gallery/result.png` 因开发机把「自动合并换行」关掉而变成两行，
    与提交的基线不一致，误判为界面回归。画廊只做静态留档，`set()` 一律丢弃，绝不写盘。
    """
    from ..config import DEFAULTS

    class _FixedCfg:
        def get(self, key, default=None):
            return DEFAULTS.get(key, cfg.get(key, default))

        def set(self, key, value):
            pass  # 只读：画廊不得修改用户配置

    return _FixedCfg()


def run_gallery(app, cfg, spec="both"):
    cfg = _fixed_cfg(cfg)
    from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt
    from PyQt5.QtGui import QPainterPath, QPixmap

    from ..paths import app_dir
    from ..ui.overlay import OverlayWindow
    from ..ui.preview_dialog import PreviewDialog
    from ..ui.result_window import ResultWindow
    from ..ui.settings_dialog import SettingsDialog
    from .selftest import _sample_image

    if spec not in ("dark", "light", "both"):
        spec = "both"
    themes = ["dark", "light"] if spec == "both" else [spec]

    orig_dark = _read_registry_theme()
    shot_root = os.path.join(app_dir(), "docs", "gallery")

    def grab(w, path):
        w.grab().save(path)

    results = []
    try:
        for name in themes:
            dark = name == "dark"
            _set_registry_theme(dark)
            _broadcast_theme_change()
            app.processEvents()

            time.sleep(0.4)
            app.processEvents()

            out = os.path.join(shot_root, name)
            os.makedirs(out, exist_ok=True)
            scr = app.primaryScreen()

            # 遮罩：编辑态（展开 + 笔画 + 马赛克）
            pm = QPixmap.fromImage(_sample_image(1280, 720))
            ov = OverlayWindow(scr, pm, cfg=cfg)
            ov.sel = QRectF(100, 80, 500, 300)
            ov._finalize()
            ov._on_edit_toggle(True)
            # 基线可复现：绕开展开动画，直接到终态（否则抓图时刻高度不定）
            ov.toolbar.set_expanded(True, animate=False)
            app.processEvents()
            c = ov.canvas
            c.set_tool("pen")
            c._current = {
                "kind": "pen",
                "pts": [QPointF(60 * c.dpr, 200 * c.dpr), QPointF(300 * c.dpr, 240 * c.dpr)],
                "color": "#ff3b30",
                "width": 4,
            }
            c.mouseReleaseEvent(QEvent(QEvent.MouseButtonRelease))
            c.set_tool("mosaic")
            mpath = QPainterPath()
            mpath.setFillRule(Qt.WindingFill)
            mpath.addRect(320 * c.dpr, 40 * c.dpr, 180 * c.dpr, 70 * c.dpr)
            c._current = {"kind": "mosaic", "path": mpath, "width": 20}
            c.mouseReleaseEvent(QEvent(QEvent.MouseButtonRelease))
            ov.show()
            app.processEvents()
            grab(ov, os.path.join(out, "overlay_editing.png"))
            ov.hide()
            ov.deleteLater()

            # 预览窗
            pv = PreviewDialog(c.render_to_image(), cfg)
            pv.show_near(scr)
            app.processEvents()
            grab(pv, os.path.join(out, "preview.png"))
            pv.close()

            # 结果窗口
            rw = ResultWindow(cfg)
            rw.set_results(
                [
                    ("快截OCR 自检测试样张", 0.98, None),
                    ("Screenshot OCR Test 1234567890", 0.97, None),
                ],
                0.42,
            )
            rw.show()
            app.processEvents()
            grab(rw, os.path.join(out, "result.png"))
            rw.close()

            # 设置窗口
            sd = SettingsDialog(cfg)
            sd.show()
            app.processEvents()
            grab(sd, os.path.join(out, "settings.png"))
            sd.close()
            results.append(name)

        # 收尾：主题恢复到运行前
        _set_registry_theme(orig_dark)
        _broadcast_theme_change()
        app.processEvents()
    finally:
        _set_registry_theme(orig_dark)
        _broadcast_theme_change()

    print("gallery done: %s -> %s" % (",".join(results), shot_root))
    return 0
