from __future__ import annotations

from pathlib import Path


class PromptManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def load(self, name: str) -> str:
        path = self.base_dir / f"{name}.txt"
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8").strip()


__all__ = ["PromptManager"]

