"""Task 3 LangGraph skeleton."""

from __future__ import annotations

import os
import sys


# macOS scientific stack + faiss may load duplicate OpenMP runtimes.
if sys.platform == "darwin":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
