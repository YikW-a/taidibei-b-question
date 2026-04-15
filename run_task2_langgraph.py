from pathlib import Path
import os


_BASE_DIR = Path(__file__).resolve().parent
_CACHE_DIR = _BASE_DIR / "outputs/task2_langgraph/.cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
(_CACHE_DIR / "matplotlib").mkdir(parents=True, exist_ok=True)
(_CACHE_DIR / "fontconfig").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_DIR / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_DIR))
os.environ.setdefault("FONTCONFIG_PATH", str(_CACHE_DIR / "fontconfig"))

from src.task2_langgraph.app.cli import main


if __name__ == "__main__":
    main()
