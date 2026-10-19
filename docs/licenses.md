# 许可与第三方组件

本工程源码：MIT License。

| 组件 | 许可 | 用途 |
|---|---|---|
| PyQt5 5.15 | GPL v3（Riverbank） | GUI 框架（随包分发二进制，遵循 GPL v3 开源义务） |
| rapidocr 3.x | Apache-2.0（RapidAI） | OCR 推理管线封装 |
| onnxruntime | MIT（Microsoft） | ONNX CPU 推理运行时 |
| opencv-python-headless | Apache-2.0 | 图像处理（rapidocr 依赖） |
| PP-OCRv5 mobile det/cls/rec 模型 | Apache-2.0（PaddleOCR/Baidu） | 模型权重 |
| Inno Setup 6 | Inno Setup License（免费商用） | 仅构建期使用，不随包分发 |

> 商用闭源注意：PyQt5 为 GPL v3。若日后需要闭源商用，将依赖切换为
> PySide6（LGPL v3）即可，代码层仅 import 处需小改（本项目所有 Qt 导入集中在
> `snapocr` 包内，无散落调用）。
