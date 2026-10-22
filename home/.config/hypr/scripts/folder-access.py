#!/usr/bin/env python3
"""folder-access.py: the command line of folder_access.py (its docstring
explains): which folders the AI features may read."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import folder_access  # noqa: E402

if __name__ == "__main__":
    sys.exit(folder_access.main(sys.argv[1:]))
