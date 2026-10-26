# 截图工具 (SnapOCR)

完全离线的截图 + OCR 桌面工具。托盘常驻，点击托盘图标或按全局快捷键即可框选截屏，
框选后一键 OCR（RapidOCR / PP-OCRv6 ONNX，本地推理，不联网），并内置
画笔 / 涂色 / 文字 / 矩形 / 椭圆 / 箭头 / 马赛克 / 橡皮擦 标注、复制与保存。

- **平台**：Windows 10/11 x64（含 LTSC 2019/2021、22H2+）；Linux 信创（UOS 20 1070+、银河麒麟 V10 SP1+，x86_64 / ARM64）
- **引擎**：RapidOCR 3.x + onnxruntime CPU + PP-OCRv6 small 三模型（det 9.9MB + cls 0.6MB + rec 21.2MB ≈ 31.7MB，随包离线）
- **形态**：绿色版 zip 解压即用 + per-user 安装版（免管理员）；Linux 提供 deb 包
- **隐私**：零网络请求，所有识别在本机完成

## 快速上手（Windows）

1. 安装版：双击 `SnapOCR-1.0.0-win64-setup.exe`（per-user 安装，无需管理员）。
   绿色版：解压 `SnapOCR-1.0.0-win64-绿色版.zip` 到任意目录，运行 `SnapOCR.exe`。
2. 启动后出现托盘图标：**左键点击图标 = 立即框选截屏**；全局快捷键默认 `F4`（可在设置修改）。
3. 拖动鼠标框选区域（放大镜/尺寸提示辅助），松开后工具条出现：
   - **OCR识别**：本地识别选区文字，弹窗显示结果（可编辑/复制/另存 TXT）；
   - **编辑**：进入标注编辑器（画笔/涂色/文字/矩形/椭圆/箭头/马赛克、撤销重做）；
   - **复制** / **保存**：复制到剪贴板 / 存为 PNG/JPG；
   - Enter 或双击选区 = 进入编辑器；Esc = 取消。
4. 编辑器内：`Ctrl+C` 复制、`Ctrl+S` 保存、`Ctrl+Z/Ctrl+Y` 撤销重做、
   「完成」= 复制并关闭；「OCR识别」对**所见即所得的画面**（含标注）识别——
   马赛克盖住的内容不会被读出。

## Linux（信创）安装

```bash
sudo apt install ./snapocr_1.0.0_<架构>.deb      # UOS/麒麟
```

- X11 会话：全局热键自动生效。
- Wayland 会话（2025 年后 UOS/deepin 新版默认）：系统限制全局热键，请用
  「托盘图标点击」或在 系统设置→键鼠→快捷键 中添加自定义快捷键，命令填
  `/opt/snapocr/SnapOCR --capture`。

## 开发与构建

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
python scripts\download_models.py        # 构建机联网拉取模型到 resources/models
dev.bat --selftest                       # 自检（OCR/遮罩/编辑器/剪贴板/UI截图）
python scripts\test_plan_probe.py        # 回归守住项探针（21 项）
python scripts\test_fix_probe.py         # 问题总表修复项验证探针（199 项）
deploy\windows\build_all.bat             # 产出绿色版 zip + 安装版 exe
```

> 安装版打包前请把 `vc_redist.x64.exe` 放到 `deploy/windows/`（与 `.iss` 同目录），
> 否则干净系统缺少 VC++ 运行库时首次 OCR 会崩溃。详见 `docs/04-构建与发布指南.md`。

Linux 构建需在 UOS/同级 glibc 环境执行 `deploy/linux/build_deb.sh`（PyInstaller 不跨 glibc 交叉打包），
或直接使用 `deploy/ci/github-actions.yml`。

## 代码质量

规范以 **`pyproject.toml`** 的 ruff 配置为唯一事实来源（规则集 `E F W I B C4 SIM RUF UP`，行宽 100）。

```bat
.venv\Scripts\pip install -r requirements-dev.txt   :: 开发工具（ruff）
check.bat                :: 一键门禁：格式 + 静态检查 + 编译 + 探针 + 自检
check.bat --fast         :: 同上但跳过 OCR 端到端自检
```

- 提交前必须 `check.bat` 全绿；**任何一项失败即阻断**，禁止用 `--skip-ruff` 或注释测试绕过。
- 需要放宽规则时走项目内部的豁免流程（全局豁免登记在 `pyproject.toml`；单点 `# noqa: 规则码` 必须带原因）。
- 提交者与合并者不得为同一人。

## 目录结构

```
src/snapocr/          源码（ui/ ocr/ platform/ utils/ tests/）
resources/models/     离线 ONNX 模型（det/cls/rec）
deploy/               PyInstaller spec、Inno Setup、Linux deb 脚本、CI
docs/                 使用说明 / 构建与发布 / 信创部署 / 测试计划（界面截图在 docs/gallery/）
scripts/              门禁与模型下载等构建辅助（archive/ 为历史调试脚本归档）
```

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/03-使用说明.md`](docs/03-使用说明.md) | 完整功能与操作说明（含界面截图） |
| [`docs/04-构建与发布指南.md`](docs/04-构建与发布指南.md) | Windows 双包 / 安装版 / 常见构建问题 |
| [`docs/06-信创构建与部署指南.md`](docs/06-信创构建与部署指南.md) | UOS / 麒麟 deb 打包与 Wayland 适配 |
| [`docs/07-测试计划与加固方案.md`](docs/07-测试计划与加固方案.md) | 测试用例、探针资产、退出标准 |
| [`docs/licenses.md`](docs/licenses.md) | 第三方组件许可清单 |

## 许可

本工程代码 MIT；第三方：PyQt5 (GPL v3)、RapidOCR (Apache-2.0)、
onnxruntime (MIT)、PaddleOCR 模型 (Apache-2.0)，详见 `docs/licenses.md`。
