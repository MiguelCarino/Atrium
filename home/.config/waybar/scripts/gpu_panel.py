#!/usr/bin/env python3
"""GPU sensors panel -- what the GPU pill opens. All the code is in
sensors_panel.py; this file exists so panel.py can tell the two panels apart
by script name.

    gpu_panel.py [x,y]   desktop position of the click that opened it
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sensors_panel  # noqa: E402

if __name__ == "__main__":
    sensors_panel.main("gpu")
