# -*- coding: utf-8 -*-
"""程序化图标：QPainter 绘制，避免携带二进制图标资源。"""

import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

# 缓存
_cache = {}

# 应用图标等比放大系数：原图案画在 56×56 画框（内缩 4px），满铺到 64×64 画布需 64/56。
# 采用"整体仿射缩放"而非逐个改坐标，保证刀身/手柄/蓝点的结构关系与原版逐像素一致。
_APP_ICON_ZOOM = 64.0 / 56.0  # 8/7


def _painter(pm_size=64):
    pm = QPixmap(pm_size, pm_size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    return pm, p


def _pen(color, w, cap=Qt.RoundCap, join=Qt.RoundJoin):
    pen = QPen(QColor(color), w, Qt.SolidLine, cap, join)
    return pen


def _icon_from_pm(pm):
    return QIcon(pm)


def icon(name: str, color="#ffffff", size=64) -> QIcon:
    key = "%s|%s|%s" % (name, color, size)
    if key in _cache:
        return _cache[key]
    ic = _icon_from_pm(_draw(name, color, size))
    _cache[key] = ic
    return ic


def dual_icon(name: str, off_color, on_color, size=64) -> QIcon:
    """可勾选按钮双色图标：普通态 off_color，选中态 on_color。"""
    key = "dual|%s|%s|%s|%s" % (name, off_color, on_color, size)
    if key in _cache:
        return _cache[key]
    ic = QIcon()
    ic.addPixmap(_draw(name, off_color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(_draw(name, on_color, size), QIcon.Normal, QIcon.On)
    _cache[key] = ic
    return ic


def pixmap(name: str, color="#ffffff", size=64) -> QPixmap:
    return _draw(name, color, size)


def _draw(name, color, size):
    pm, p = _painter(size)
    c = QColor(color)
    s = size / 64.0
    lw = max(3.2, 5 * s)
    p.setPen(_pen(c, lw))
    p.setBrush(Qt.NoBrush)

    if name == "capture":  # 相机
        p.drawRoundedRect(QRectF(8 * s, 18 * s, 48 * s, 32 * s), 6 * s, 6 * s)
        p.drawRect(QRectF(24 * s, 12 * s, 16 * s, 8 * s))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(24 * s, 26 * s, 16 * s, 16 * s))
    elif name == "ocr":  # 方框 + 文
        p.setPen(_pen(c, lw, Qt.RoundCap, Qt.RoundJoin))
        p.drawRoundedRect(QRectF(8 * s, 12 * s, 48 * s, 40 * s), 6 * s, 6 * s)
        f = QFont("Microsoft YaHei" if _zh_font() else "Sans")
        f.setPixelSize(int(24 * s))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(8 * s, 12 * s, 48 * s, 40 * s), Qt.AlignCenter, "文")
    elif name == "copy":
        p.drawRoundedRect(QRectF(10 * s, 10 * s, 28 * s, 34 * s), 4 * s, 4 * s)
        p.drawRect(QRectF(24 * s, 22 * s, 28 * s, 34 * s))
    elif name == "save":
        p.drawRoundedRect(QRectF(10 * s, 10 * s, 44 * s, 44 * s), 4 * s, 4 * s)
        p.drawRect(QRectF(20 * s, 10 * s, 22 * s, 16 * s))
        p.drawRect(QRectF(18 * s, 34 * s, 28 * s, 20 * s))
    elif name == "pen":  # 斜置铅笔
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        path = QPainterPath()
        path.moveTo(46 * s, 8 * s)
        path.lineTo(56 * s, 18 * s)
        path.lineTo(22 * s, 52 * s)
        path.lineTo(10 * s, 54 * s)
        path.lineTo(12 * s, 42 * s)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "select":  # 经典指针（白底深描边，贴近系统/火狐光标样式）
        path = QPainterPath()
        path.moveTo(20 * s, 10 * s)
        path.lineTo(20 * s, 52 * s)
        path.lineTo(30 * s, 42 * s)
        path.lineTo(37 * s, 56 * s)
        path.lineTo(44 * s, 52 * s)
        path.lineTo(37 * s, 39 * s)
        path.lineTo(50 * s, 38 * s)
        path.closeSubpath()
        p.setPen(QPen(QColor("#26262b"), 2 * s, Qt.SolidLine, Qt.SquareCap, Qt.RoundJoin))
        p.setBrush(QColor("#ffffff"))
        p.drawPath(path)
    elif name == "highlight":  # 荧光笔：斜杆 + 粗划线
        p.setPen(_pen(c, lw))
        p.drawLine(QPointF(40 * s, 12 * s), QPointF(52 * s, 24 * s))
        p.setPen(_pen(c, 12 * s, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(20 * s, 38 * s), QPointF(44 * s, 20 * s))
        p.setPen(_pen(QColor(0, 0, 0, 0), 1))
        p.setBrush(QColor(color))
        p.drawPolygon(
            QPolygonF([QPointF(14 * s, 52 * s), QPointF(26 * s, 52 * s), QPointF(18 * s, 42 * s)])
        )
    elif name == "text":
        f = QFont("Arial")
        f.setPixelSize(int(44 * s))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "T")
    elif name == "rect":
        p.drawRoundedRect(QRectF(10 * s, 16 * s, 44 * s, 32 * s), 3 * s, 3 * s)
    elif name == "ellipse":
        p.drawEllipse(QRectF(10 * s, 16 * s, 44 * s, 32 * s))
    elif name == "arrow":
        p.setPen(_pen(c, 8 * s, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(14 * s, 50 * s), QPointF(48 * s, 16 * s))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawPolygon(
            QPolygonF([QPointF(54 * s, 10 * s), QPointF(50 * s, 30 * s), QPointF(34 * s, 14 * s)])
        )
    elif name == "mosaic":
        p.setPen(Qt.NoPen)
        for i in range(4):
            for j in range(4):
                alpha = 255 if (i + j) % 2 == 0 else 120
                cc = QColor(c)
                cc.setAlpha(alpha)
                p.setBrush(cc)
                p.drawRect(QRectF(10 * s + i * 11.5 * s, 10 * s + j * 11.5 * s, 10.5 * s, 10.5 * s))
    elif name == "undo":
        p.setPen(_pen(c, lw))
        p.drawArc(QRectF(14 * s, 16 * s, 40 * s, 40 * s), 30 * 16, 180 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawPolygon(
            QPolygonF([QPointF(8 * s, 30 * s), QPointF(28 * s, 22 * s), QPointF(24 * s, 42 * s)])
        )
    elif name == "redo":
        p.setPen(_pen(c, lw))
        p.drawArc(QRectF(10 * s, 16 * s, 40 * s, 40 * s), -30 * 16, -180 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawPolygon(
            QPolygonF([QPointF(56 * s, 30 * s), QPointF(36 * s, 22 * s), QPointF(40 * s, 42 * s)])
        )
    elif name == "clear":  # 清空：垃圾桶
        p.setPen(_pen(c, lw, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(16 * s, 22 * s), QPointF(48 * s, 22 * s))
        p.drawLine(QPointF(26 * s, 15 * s), QPointF(38 * s, 15 * s))
        p.drawRoundedRect(QRectF(20 * s, 22 * s, 24 * s, 30 * s), 3 * s, 3 * s)
        p.drawLine(QPointF(28 * s, 30 * s), QPointF(28 * s, 44 * s))
        p.drawLine(QPointF(36 * s, 30 * s), QPointF(36 * s, 44 * s))
    elif name == "eraser":  # 橡皮擦：斜置块 + 分隔线
        p.setPen(_pen(c, lw, Qt.RoundCap, Qt.RoundJoin))
        path = QPainterPath()
        path.moveTo(18 * s, 44 * s)
        path.lineTo(42 * s, 20 * s)
        path.lineTo(52 * s, 30 * s)
        path.lineTo(28 * s, 54 * s)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(32 * s, 30 * s), QPointF(42 * s, 40 * s))
    elif name == "cancel":
        p.setPen(_pen(c, lw))
        p.drawLine(QPointF(16 * s, 16 * s), QPointF(48 * s, 48 * s))
        p.drawLine(QPointF(48 * s, 16 * s), QPointF(16 * s, 48 * s))
    elif name == "done":
        p.setPen(_pen(c, lw))
        p.drawPolyline(
            QPolygonF([QPointF(12 * s, 34 * s), QPointF(27 * s, 48 * s), QPointF(52 * s, 18 * s)])
        )
    elif name == "settings":  # 齿轮：外圈+齿
        p.setPen(_pen(c, lw))
        p.drawEllipse(QRectF(18 * s, 18 * s, 28 * s, 28 * s))
        p.setPen(_pen(c, 6 * s, Qt.FlatCap))

        for i in range(8):
            a = i * math.pi / 4
            x1 = 32 * s + math.cos(a) * 22 * s
            y1 = 32 * s + math.sin(a) * 22 * s
            x2 = 32 * s + math.cos(a) * 28 * s
            y2 = 32 * s + math.sin(a) * 28 * s
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    elif name == "app":  # 应用图标：深底 + 蓝色虚线取景框 + 白色剪刀（截屏语义）
        sw = max(1.3, 4 * s)  # 描边宽按尺寸缩放，小尺寸设下限防糊
        # 深色圆角底原先画在 (4,4)-(60,60) 的 56×56 画框内、内缩 4px，与相邻应用
        # 并排时小一圈。现要求底色满铺画布（四角透明、与系统图标栅格对齐）。
        # 做法是**整体等比放大**：把旧画框关于画布中心 (32,32) 放大 8/7（56→64）。
        # 用一次仿射变换完成，下方图案绘制代码与原始版本逐行一致 —— 刀身与手柄的
        # 连接、蓝点与刀身交叉点的相对位置等结构关系完全保持，不会被手工改坐标破坏。
        p.save()
        p.translate(32 * s, 32 * s)
        p.scale(_APP_ICON_ZOOM, _APP_ICON_ZOOM)
        p.translate(-32 * s, -32 * s)
        # 深色圆角底（旧画框 (4,4,56,56)，经上方变换后恰好铺满 0..64）
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1F2937"))
        p.drawRoundedRect(QRectF(4 * s, 4 * s, 56 * s, 56 * s), 16 * s, 16 * s)
        # 虚线取景框（Qt 的 dashPattern 以线宽为单位：8/6 px ÷ 线宽 4）
        # 小尺寸下虚线会退化成噪点，改用实线，整体轮廓不变
        dash = QPen(QColor("#0078D4"), sw, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin)
        if size >= 32:
            dash.setDashPattern([2.0, 1.5])
        p.setPen(dash)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(14 * s, 16 * s, 36 * s, 30 * s), 6 * s, 6 * s)
        # 剪刀：两个手柄环 + 交叉刀身
        p.setPen(QPen(QColor("#FFFFFF"), sw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawEllipse(QPointF(24 * s, 44 * s), 5 * s, 5 * s)
        p.drawEllipse(QPointF(38 * s, 44 * s), 5 * s, 5 * s)
        p.drawLine(QPointF(26 * s, 40 * s), QPointF(40 * s, 20 * s))
        p.drawLine(QPointF(36 * s, 40 * s), QPointF(22 * s, 20 * s))
        # 轴心蓝点
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0078D4"))
        p.drawEllipse(QPointF(31 * s, 30 * s), 2.5 * s, 2.5 * s)
        p.restore()
    elif name == "pin":  # 图钉（正视、竖直朝下）：梯形钉身 + 底横线 + 中央竖针
        # 形状参照用户提供的标准图钉样图（2026-10-28）：上宽下窄的梯形轮廓，
        # 底边一条横线，中针从横线中点垂下
        pen_w = 3.0 * s
        p.setPen(QPen(QColor(color), pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        # 梯形钉身：上边 (22,14)-(42,14)，下边 (28,34)-(36,34)（上宽下窄）
        p.drawPolyline(
            QPolygonF(
                [
                    QPointF(22 * s, 14 * s),
                    QPointF(42 * s, 14 * s),
                    QPointF(36 * s, 34 * s),
                    QPointF(28 * s, 34 * s),
                    QPointF(22 * s, 14 * s),
                ]
            )
        )
        # 底部横线（比梯形下底更宽）
        p.drawLine(QPointF(22 * s, 34 * s), QPointF(42 * s, 34 * s))
        # 中央竖针
        p.drawLine(QPointF(32 * s, 34 * s), QPointF(32 * s, 50 * s))
    elif name == "minimize":  # 最小化：单条下横线（与系统标题栏按钮一致）
        p.setPen(QPen(QColor(color), 3.0 * s, Qt.SolidLine, Qt.FlatCap))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(20 * s, 36 * s), QPointF(44 * s, 36 * s))
    elif name == "maximize":  # 最大化：单方框（与系统标题栏按钮同款细线）
        p.setPen(QPen(QColor(color), 2.2 * s, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(22 * s, 22 * s, 20 * s, 20 * s))
    elif name == "restore":  # 还原：两个重叠方框（最大化态的按钮图标）
        p.setPen(QPen(QColor(color), 2.2 * s, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(21 * s, 26 * s, 16 * s, 16 * s))  # 后方框
        p.drawRect(QRectF(26 * s, 21 * s, 16 * s, 16 * s))  # 前方框
    elif name == "close_line":  # 关闭：×（细线，与标题栏按钮一致；区别于 cancel 的粗叉）
        p.setPen(QPen(QColor(color), 3.0 * s, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(21 * s, 21 * s), QPointF(43 * s, 43 * s))
        p.drawLine(QPointF(43 * s, 21 * s), QPointF(21 * s, 43 * s))
    else:  # 兜底圆点
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(16 * s, 16 * s, 32 * s, 32 * s))
    p.end()
    return pm


def _zh_font() -> bool:
    from PyQt5.QtGui import QFontDatabase

    fams = QFontDatabase().families() if hasattr(QFontDatabase, "families") else []
    if not fams:
        return False
    for f in ("Microsoft YaHei", "微软雅黑", "SimHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei"):
        if f in fams:
            return True
    return False
