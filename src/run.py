# -*- coding: utf-8 -*-
"""开发/打包通用启动器：python src/run.py [--capture|--selftest|--bench ...]"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from snapocr.main import main

if __name__ == "__main__":
    sys.exit(main())
