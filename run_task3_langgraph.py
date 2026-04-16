from pathlib import Path
import os


_BASE_DIR = Path(__file__).resolve().parent
_CACHE_DIR = _BASE_DIR / "outputs/task3_langgraph/.cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
(_CACHE_DIR / "matplotlib").mkdir(parents=True, exist_ok=True)
(_CACHE_DIR / "fontconfig").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_DIR / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_DIR))
os.environ.setdefault("FONTCONFIG_PATH", str(_CACHE_DIR / "fontconfig"))
# Work around macOS OpenMP runtime duplication between scientific deps and faiss.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from src.task3_langgraph.app.cli import main


if __name__ == "__main__":
    main()
