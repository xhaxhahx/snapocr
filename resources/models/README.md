# resources/models —— 离线 OCR 模型

本目录随包分发以下 ONNX 模型（构建时由 `scripts/download_models.py` 或 rapidocr 内置模型放置）：

| 文件 | 实际模型 | 大小 |
|---|---|---|
| det.onnx | PP-OCRv6 det small | ~9.9MB |
| rec.onnx | PP-OCRv6 rec small（中/繁/英/日等多语） | ~21.2MB |
| cls.onnx | ch_ppocr_mobile_v2.0_cls（方向分类） | ~0.6MB |

来源：RapidAI/RapidOCR wheel 内置模型（Apache-2.0；模型源自 PaddleOCR，Apache-2.0）。

升级模型（如 PP-OCRv6 server 或未来 v7）：用新 onnx 覆盖本目录同名文件即可，无需改代码；
若删除本目录文件，引擎会自动回落到 rapidocr 包内置模型。
