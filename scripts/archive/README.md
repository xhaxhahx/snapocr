# 历史一次性调试脚本（归档）

以下脚本为开发期针对具体缺陷/交互做的一次性验证探针，已完成使命：
- `_dbg_state.py` / `_dbg_t12f.py`：调试 T1.1b / T1.2 / T1.2f 的状态与残留窗口
- `_probe_tl.py`：定位遮罩左上角灰色块控件
- `_probe_v3.py` / `_probe_v5.py` / `_probe_zoom.py`：新交互（光标/窗口识别/色板/字体/放大镜）探针

保留原因：仅作历史留档。**不参与 ruff 门禁**（见 pyproject.toml 的 extend-exclude），
现行自动化验证请使用 `scripts/test_plan_probe.py` 与 `scripts/test_fix_probe.py`。
如需彻底清理，可直接删除本目录。
