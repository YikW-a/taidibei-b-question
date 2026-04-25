from __future__ import annotations

from dataclasses import dataclass

from src.task2_langgraph.graph.runner import Task2LangGraphPrototype as BaseTask2LangGraphPrototype

from ..nodes import Task2NodeContext
from .builder import build_task2_graph


@dataclass
class Task2LangGraphPrototype(BaseTask2LangGraphPrototype):
    def __post_init__(self) -> None:
        self.context = Task2NodeContext(self.config)
        self.app = build_task2_graph(self.config)
