# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PyQt5.QtGui import QImage  # noqa: E402

img = QImage("docs/screenshots/_probe_border.png")
crop = img.copy(180, 70, 140, 30)
crop = crop.scaled(560, 120)
crop.save("docs/screenshots/_probe_border_zoom.png")
print("saved")
