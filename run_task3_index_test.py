from __future__ import annotations

from pathlib import Path

cache_root = Path(__file__).resolve().parent / "outputs_test/task3_langgraph/.cache"
cache_root.mkdir(parents=True, exist_ok=True)

from src_test.task3_langgraph.app.index_cli import main


if __name__ == "__main__":
    main()
