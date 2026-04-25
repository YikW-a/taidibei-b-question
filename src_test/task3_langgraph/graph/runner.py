from __future__ import annotations

from dataclasses import dataclass

from src.task3_langgraph.graph.runner import Task3LangGraphPrototype as BaseTask3LangGraphPrototype

from ..nodes import Task3NodeContext
from .builder import build_task3_graph


@dataclass
class Task3LangGraphPrototype(BaseTask3LangGraphPrototype):
    def __post_init__(self) -> None:
        self.context = Task3NodeContext(self.config)
        self.app = build_task3_graph(self.config)
