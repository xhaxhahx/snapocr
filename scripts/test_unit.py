# -*- coding: utf-8 -*-
"""单元测试（零依赖 runner，可被 pytest 直接收集）。

与 `scripts/test_*.py` 的探针不同：探针做**集成验证**（起窗口、逐像素比对、
子进程），这里只测**纯逻辑**，目标是快（<3s）且失败时能直接定位到函数。

覆盖：i18n 键对齐与回落、换行三态、配置合并与脏类型、路径兜底、
放大镜矩形翻转（几何）。不覆盖 OCR 与绘制——那些由探针与 selftest 负责。

运行：`.venv\\Scripts\\python scripts\\test_unit.py`（gate.py 已接入）
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print("  [PASS] %s" % name)
    else:
        FAILED.append((name, detail))
        print("  [FAIL] %s %s" % (name, detail))


# ---------------- i18n ----------------


def test_i18n_zh_default():
    from snapocr import i18n

    i18n.init_lang("zh")
    check("i18n 中文默认", i18n.tr("capture") == "截屏", i18n.tr("capture"))


def test_i18n_en():
    from snapocr import i18n

    i18n.init_lang("en")
    check("i18n 英文切换", i18n.tr("capture") == "Capture", i18n.tr("capture"))
    i18n.init_lang("zh")


def test_i18n_unknown_key_falls_back_to_key():
    from snapocr import i18n

    i18n.init_lang("zh")
    check("i18n 未知键回落键名", i18n.tr("__no_such_key__") == "__no_such_key__")


def test_i18n_placeholder():
    from snapocr import i18n

    i18n.init_lang("zh")
    out = i18n.tr("saved", "a.png")
    check("i18n 占位符替换", "a.png" in out, out)


def test_i18n_key_parity():
    """中英键集合必须一致——漏翻会退化成英文键名，且只有切语言才暴露。"""
    from snapocr import i18n

    zh = set(i18n._ZH)
    en = set(i18n._EN)
    only_zh = sorted(zh - en)
    only_en = sorted(en - zh)
    check(
        "i18n 中英键集合一致",
        not only_zh and not only_en,
        "仅中文=%s 仅英文=%s" % (only_zh, only_en),
    )


# ---------------- 换行三态 ----------------


def test_wrap_original_keeps_indent_and_blank():
    from snapocr.ui.result_window import WRAP_ORIGINAL, apply_wrap

    lines = ["def f():", "    return 1", "", "x = 2"]
    out = apply_wrap(lines, WRAP_ORIGINAL)  # 返回 list[str]，逐行原样
    check("换行-原图：保留缩进", "    return 1" in out, repr(out))
    check("换行-原图：保留空行", "" in out, repr(out))
    check("换行-原图：行数不变", len(out) == len(lines), repr(out))


def test_wrap_join_merges():
    from snapocr.ui.result_window import WRAP_JOIN, apply_wrap

    out = apply_wrap(["第一行", "第二行"], WRAP_JOIN)
    check(
        "换行-合并：合为一条",
        len(out) == 1 and "第一行" in out[0] and "第二行" in out[0],
        repr(out),
    )


def test_wrap_sentence_splits():
    from snapocr.ui.result_window import WRAP_SENTENCE, apply_wrap

    out = apply_wrap(["这是第一句。这是第二句。", "第三句"], WRAP_SENTENCE)
    check("换行-整句：按句切分", len(out) >= 2, repr(out))


# ---------------- 配置 ----------------


def _isolated_config():
    """把配置重定向到 .tmp，避免污染真实用户配置（探针纪律同款）。"""
    import snapocr.config as cfgmod

    os.makedirs(os.path.join(ROOT, ".tmp"), exist_ok=True)
    tmp = os.path.join(ROOT, ".tmp", "unit_config.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    cfgmod.config_file = lambda: tmp
    return cfgmod, tmp


def test_config_defaults_present():
    cfgmod, _ = _isolated_config()
    c = cfgmod.Config()
    missing = [k for k in cfgmod.DEFAULTS if c.get(k) is None and cfgmod.DEFAULTS[k] is not None]
    check("配置默认值齐全", not missing, "缺失=%s" % missing)


def test_config_dirty_type_fallback():
    """配置文件里的脏类型（如 hotkey 写成数字）必须回落默认值，不能带到运行期。"""
    cfgmod, tmp = _isolated_config()
    import json

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"hotkey": 12345, "mosaic_block": "big", "pen_color": "#00ff00"}, f)
    c = cfgmod.Config()
    check("配置脏类型回落", isinstance(c.get("hotkey"), str), c.get("hotkey"))
    check("配置脏类型回落（数值）", isinstance(c.get("mosaic_block"), int), c.get("mosaic_block"))
    check("配置合法键保留", c.get("pen_color") == "#00ff00", c.get("pen_color"))


def test_config_unknown_key_ignored():
    cfgmod, tmp = _isolated_config()
    import json

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"__unknown__": 1}, f)
    c = cfgmod.Config()
    check("配置未知键不写入", c.get("__unknown__") is None)


# ---------------- 路径 ----------------


def test_pictures_dir_nonempty():
    from snapocr.paths import pictures_dir

    d = pictures_dir()
    check("图片目录非空", bool(d) and isinstance(d, str), d)


# ---------------- UI 纯逻辑（需 QApplication） ----------------

_APP = None


def _qapp():
    global _APP
    if _APP is None:
        from PyQt5.QtCore import QCoreApplication, Qt
        from PyQt5.QtWidgets import QApplication

        from snapocr.main import _setup_qt_plugin_path

        _setup_qt_plugin_path()
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        _APP = QApplication.instance() or QApplication([])
    return _APP


def test_standard_colors_valid():
    from PyQt5.QtGui import QColor

    from snapocr.ui.editor import STANDARD_COLORS

    bad = [c for c in STANDARD_COLORS if not QColor(c).isValid()]
    check("标准色全部合法", not bad, bad)


def test_magnifier_rect_inside():
    _qapp()
    from PyQt5.QtCore import QPointF

    from snapocr.ui.overlay import OverlayWindow

    ov = OverlayWindow.__new__(OverlayWindow)
    ov.setFixedSize = lambda *a: None
    ov.width = lambda: 800
    ov.height = lambda: 600
    r = OverlayWindow._magnifier_rect(ov, QPointF(300, 300))
    check("放大镜-内部不翻转", r.x() > 300 and r.y() > 300, r)


def test_magnifier_rect_flip_right():
    _qapp()
    from PyQt5.QtCore import QPointF

    from snapocr.ui.overlay import OverlayWindow

    ov = OverlayWindow.__new__(OverlayWindow)
    ov.width = lambda: 800
    ov.height = lambda: 600
    r = OverlayWindow._magnifier_rect(ov, QPointF(795, 300))
    check("放大镜-贴右翻转", r.right() <= 800, r)


def test_magnifier_rect_flip_bottom():
    _qapp()
    from PyQt5.QtCore import QPointF

    from snapocr.ui.overlay import OverlayWindow

    ov = OverlayWindow.__new__(OverlayWindow)
    ov.width = lambda: 800
    ov.height = lambda: 600
    r = OverlayWindow._magnifier_rect(ov, QPointF(300, 595))
    check("放大镜-贴下翻转", r.bottom() <= 600, r)


def test_color_picker_reexport_identity():
    """拆分后 ui.editor 的重导出必须与 ui.color_picker 是**同一对象**。

    探针与旧调用方仍从 `ui.editor` 导入 COLORS / STANDARD_COLORS /
    ColorPickerPopup；若两处各自复制一份，调色板会出现"改了不生效"的幽灵 bug。
    """
    from snapocr.ui import color_picker, editor

    check(
        "拆分重导出：STANDARD_COLORS 同一对象",
        editor.STANDARD_COLORS is color_picker.STANDARD_COLORS,
    )
    check("拆分重导出：COLORS 同一对象", editor.COLORS is color_picker.COLORS)
    check(
        "拆分重导出：ColorPickerPopup 同一类",
        editor.ColorPickerPopup is color_picker.ColorPickerPopup,
    )


def test_sel_dirty_covers_both_rects():
    """局部重绘区域必须同时覆盖旧、新选区，且上方留出尺寸标签余量。"""
    _qapp()
    from PyQt5.QtCore import QRect, QRectF

    from snapocr.ui.overlay import OverlayWindow

    ov = OverlayWindow.__new__(OverlayWindow)
    ov.width = lambda: 1000
    ov.height = lambda: 800
    ov.rect = lambda: QRect(0, 0, 1000, 800)
    caught = []
    ov.update = lambda r: caught.append(r)
    old = QRectF(100, 100, 200, 150)
    new = QRectF(400, 300, 200, 150)
    OverlayWindow._update_sel_dirty(ov, old, new)
    r = caught[0] if caught else QRectF()
    check("局部重绘覆盖旧选区", r.contains(old.toAlignedRect()), r)
    check("局部重绘覆盖新选区", r.contains(new.toAlignedRect()), r)
    check("局部重绘上方留标签余量", r.top() <= old.top() - 30, r)


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    print("== 单元测试（%d 项）==" % len(tests))
    for name, fn in tests:
        try:
            fn()
        except Exception as e:  # 单测自身异常也算失败，但要能看出是哪条
            FAILED.append((name, repr(e)))
            print("  [ERROR] %s: %r" % (name, e))
    print("== 单元测试结果: %d 项, 失败 %d ==" % (len(tests), len(FAILED)))
    if FAILED:
        for n, d in FAILED:
            print("  失败项: %s  %s" % (n, d))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
