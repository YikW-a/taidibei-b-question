from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent
_CACHE_DIR = _BASE_DIR / "outputs/testsets/.cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
(_CACHE_DIR / "matplotlib").mkdir(parents=True, exist_ok=True)
(_CACHE_DIR / "fontconfig").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_DIR / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_DIR))
os.environ.setdefault("FONTCONFIG_PATH", str(_CACHE_DIR / "fontconfig"))
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from src.task2_langgraph.app.common import resolve_config as resolve_task2_config
from src.task2_langgraph.graph.runner import Task2LangGraphPrototype
from src.task3_langgraph.app.common import resolve_config as resolve_task3_config
from src.task3_langgraph.graph.runner import Task3LangGraphPrototype


def _ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} 不存在：{path}")


def run_task2(
    *,
    base_dir: Path,
    question_file: Path,
    output_dir: Path,
    llm_config: Path | None,
) -> dict[str, object]:
    config = resolve_task2_config(
        base_dir=base_dir,
        llm_config=llm_config,
        question_file=question_file,
        output_dir=output_dir,
    )
    runner = Task2LangGraphPrototype(config)
    states = runner.run_many(runner.select_question_ids(), show_progress=True)
    return runner.export_batch_results(states)


def run_task3(
    *,
    base_dir: Path,
    question_file: Path,
    output_dir: Path,
    knowledge_base_dir: Path,
    llm_config: Path | None,
) -> dict[str, object]:
    config = resolve_task3_config(
        base_dir=base_dir,
        llm_config=llm_config,
        question_file=question_file,
        output_dir=output_dir,
        knowledge_base_dir=knowledge_base_dir,
        build_index_on_start=False,
    )
    runner = Task3LangGraphPrototype(config)
    states = runner.run_many(runner.select_question_ids(), show_progress=True)
    return runner.export_batch_results(states)


def main() -> None:
    parser = argparse.ArgumentParser(description="统一运行任务二和任务三测试题集")
    parser.add_argument("--base-dir", type=Path, default=Path.cwd(), help="项目根目录")
    parser.add_argument(
        "--task2-question-file",
        type=Path,
        default=None,
        help="任务二测试题集路径，默认 正式数据/测试集/任务二问题汇总.xlsx",
    )
    parser.add_argument(
        "--task3-question-file",
        type=Path,
        default=None,
        help="任务三测试题集路径，默认 正式数据/测试集/任务三问题汇总.xlsx",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="统一输出根目录，默认 outputs/testsets",
    )
    parser.add_argument(
        "--task3-knowledge-base-dir",
        type=Path,
        default=None,
        help="任务三知识库目录，默认 outputs/task3_langgraph",
    )
    parser.add_argument("--task2-llm-config", type=Path, default=None, help="任务二 LLM 配置文件")
    parser.add_argument("--task3-llm-config", type=Path, default=None, help="任务三 LLM 配置文件")
    parser.add_argument("--skip-task2", action="store_true", help="跳过任务二测试")
    parser.add_argument("--skip-task3", action="store_true", help="跳过任务三测试")
    args = parser.parse_args()

    base_dir = args.base_dir
    testset_dir = base_dir / "正式数据/测试集"
    output_root = args.output_root or (base_dir / "outputs/testsets")
    task2_question_file = args.task2_question_file or (testset_dir / "任务二问题汇总.xlsx")
    task3_question_file = args.task3_question_file or (testset_dir / "任务三问题汇总.xlsx")
    task2_output_dir = output_root / "task2_langgraph"
    task3_output_dir = output_root / "task3_langgraph"
    task3_knowledge_base_dir = args.task3_knowledge_base_dir or (base_dir / "outputs/task3_langgraph")

    summaries: dict[str, object] = {}

    if not args.skip_task2:
        _ensure_exists(task2_question_file, "任务二测试题集")
        print(f"[testsets] 任务二题库：{task2_question_file}", flush=True)
        print(f"[testsets] 任务二输出：{task2_output_dir}", flush=True)
        summaries["task2"] = run_task2(
            base_dir=base_dir,
            question_file=task2_question_file,
            output_dir=task2_output_dir,
            llm_config=args.task2_llm_config,
        )

    if not args.skip_task3:
        _ensure_exists(task3_question_file, "任务三测试题集")
        _ensure_exists(task3_knowledge_base_dir / "artifacts/vector_store/index.faiss", "任务三知识库 index.faiss")
        print(f"[testsets] 任务三题库：{task3_question_file}", flush=True)
        print(f"[testsets] 任务三输出：{task3_output_dir}", flush=True)
        print(f"[testsets] 任务三知识库：{task3_knowledge_base_dir}", flush=True)
        summaries["task3"] = run_task3(
            base_dir=base_dir,
            question_file=task3_question_file,
            output_dir=task3_output_dir,
            knowledge_base_dir=task3_knowledge_base_dir,
            llm_config=args.task3_llm_config,
        )

    print("\nTestset summaries:")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
