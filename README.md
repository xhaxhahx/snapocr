# 截图工具 (SnapOCR)

完全离线的截图 + OCR 桌面工具。托盘常驻，点击托盘图标或按全局快捷键即可框选截屏，
框选后一键 OCR（RapidOCR / PP-OCRv6 ONNX，本地推理，不联网），并内置
画笔 / 高亮 / 文字 / 矩形 / 椭圆 / 箭头 / 马赛克 / 橡皮擦 标注、复制与保存，
预览确认窗支持缩放平移与**钉住**（置顶且跨会话保留）。

- **平台**：Windows 10/11 x64（含 LTSC 2019/2021、22H2+）；Linux 信创（UOS 20 1070+、
  银河麒麟 V10 SP1+，x86_64 / ARM64）
- **引擎**：RapidOCR 3.x + onnxruntime CPU + PP-OCRv6 small 三模型
  （det 9.9MB + cls 0.6MB + rec 21.2MB ≈ 31.7MB，随包离线）
- **形态**：绿色版 zip 解压即用 + per-user 安装版（免管理员）；Linux 提供 deb 包
- **隐私**：零网络请求，所有识别在本机完成
- **内存**：三层防线（对象生命周期 / 确定性回收 / 内存看门狗软释放与自愈重启），
  常驻 Commit 恒 ≤ 初始化基线 + 48MB（见 `docs/15-内存治理实施计划书.md`）

## 快速上手（Windows）

1. 安装版：双击 `SnapOCR-1.0.0-win64-setup.exe`（per-user，无需管理员）；
   绿色版：解压 `SnapOCR-1.0.0-win64-绿色版.zip` 到任意目录，运行 `SnapOCR.exe`。
2. 启动后出现托盘图标：**左键点击图标 = 立即框选截屏**；全局快捷键默认
   `Ctrl+Alt+A`（可在设置修改，安装页默认勾选开机自启）。
3. 拖动鼠标框选区域（放大镜 + 尺寸标签 + 窗口吸附辅助），松开后工具条出现：
   - **OCR识别**：本地识别选区文字，弹窗显示结果（复制文本 / 复制为TXT文件 /
     保存 / 格式化换行 / 重新识别）；
   - **编辑**：标注编辑器（画笔/高亮/文字/矩形/椭圆/箭头/马赛克/橡皮、撤销重做、
     色板/粗细/字号/字重/字体）；
   - **复制图片** / **复制为jpg文件** / **另存为**：剪贴板 / 文件（可命名）；
   - **回车或双击选区 = 打开预览确认窗**；选区外重新拖动 = 替换旧选区；Esc = 取消。
4. 预览确认窗：滚轮缩放、拖拽平移；标题栏**图钉** = 置顶并跨会话保留
   （截图时也保持在最前），最小化 = 结束会话但窗口保留；复制 / 另存 / 重试 / 取消。

## Linux（信创）安装

```bash
sudo apt install ./snapocr_1.0.0_<架构>.deb      # UOS/麒麟
```

- X11 会话：全局热键自动生效。
- Wayland 会话（2025 年后 UOS/deepin 新版默认）：系统限制全局热键，请在
  「托盘图标点击」或系统设置→键鼠→快捷键→自定义快捷键，命令填
  `/opt/snapocr/SnapOCR --capture`。

## 命令行参数（单实例自动转发）

```bat
SnapOCR.exe --capture      :: 呼出框选
SnapOCR.exe --settings     :: 打开设置
SnapOCR.exe --exit         :: 退出常驻实例
SnapOCR.exe --recycle      :: 自愈重启（内存整理，通常由看门狗触发）
```

## 开发与构建

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
python scripts\download_models.py        # 构建机联网拉取模型到 resources/models
dev.bat --selftest                       # 自检（OCR/遮罩/编辑器/剪贴板/UI合成）
python scripts\test_unit.py             # 单元测试（18 项）
python scripts\probes\round33_suite.py  # 回归探针套件（215+ 项）
deploy\windows\build_all.bat             # 产出绿色版 zip + 安装版 exe
```

> 安装版打包前请把 `vc_redist.x64.exe` 放到 `deploy/windows/`（与 `.iss` 同目录），
> 否则干净系统缺少 VC++ 运行库时首次 OCR 会崩溃。详见 `docs/04-构建与发布指南.md`。
> Linux 构建需在 UOS/同级 glibc 环境执行 `deploy/linux/build_deb.sh`
> （PyInstaller 不跨 glibc 交叉打包），或直接使用 `deploy/ci/github-actions.yml`。

## 代码质量

规范以 **`pyproject.toml`** 的 ruff 配置为唯一事实来源（规则集 `E F W I B C4 SIM RUF UP`，行宽 100）。
```bat
.venv\Scripts\pip install -r requirements-dev.txt   :: 开发工具（ruff）
check.bat                :: 一键门禁：格式 + 静态检查 + 编译 + 探针 + 自检
check.bat --fast         :: 同上但跳过 OCR 端到端自检
```

## 文档索引

| 文档 | 内容 |
|---|---|
| docs/01 | 技术选型与架构设计 |
| docs/03 | 使用说明（功能与交互语义） |
| docs/04 | 构建与发布指南（Windows） |
| docs/05 | 测试报告（逐轮详录，顶部有当前状态速览） |
| docs/06 | 信创构建与部署指南 |
| docs/10 | 代码审查标准与流程（宪法） |
| docs/15 | 内存治理实施计划书 |
