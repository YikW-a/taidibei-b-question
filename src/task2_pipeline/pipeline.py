from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from .charting import chart_type_to_label
from .config import Task2Config
from .engine import QueryEngine
from .llm_client import OpenAICompatibleClient
from .llm_engine import LLMQueryEngine
from .models import QuestionResult
from .parser import IntentParser, load_questions


class Task2Pipeline:
    CHART_REQUEST_TOKENS = (
        "图",
        "绘制",
        "趋势图",
        "折线图",
        "柱状图",
        "条形图",
        "水平柱状图",
        "饼图",
        "散点图",
        "直方图",
        "箱线图",
        "雷达图",
    )

    def __init__(self, config: Task2Config) -> None:
        self.config = config
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.config.result_dir.mkdir(parents=True, exist_ok=True)
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)

        company_reference = pd.read_excel(self.config.company_info_path, sheet_name=0)
        self.intent_parser = IntentParser(company_reference)
        self.query_engine = QueryEngine(self.config.database_url, company_reference, self.config.result_dir)
        self.llm_query_engine = None
        if self.config.llm_mode == "llm":
            if not (self.config.llm_base_url and self.config.llm_api_key and self.config.llm_model):
                raise ValueError("LLM mode requires llm_base_url, llm_api_key, and llm_model.")
            llm_client = OpenAICompatibleClient(
                base_url=self.config.llm_base_url,
                api_key=self.config.llm_api_key,
                model=self.config.llm_model,
            )
            self.llm_query_engine = LLMQueryEngine(
                source_database_url=self.config.database_url,
                cache_db_path=self.config.query_cache_db,
                llm_client=llm_client,
                result_dir=self.config.result_dir,
                artifacts_dir=self.config.artifacts_dir,
            )

    def run(self) -> pd.DataFrame:
        questions = load_questions(self.config.question_file)
        if self.config.question_ids:
            requested_ids = {item.strip() for item in self.config.question_ids if item.strip()}
            questions = [question for question in questions if question.question_id in requested_ids]
            print(f"question-id mode enabled: selected {len(questions)} questions -> {', '.join(sorted(requested_ids))}")
        elif self.config.sample_limit is not None and self.config.sample_limit > 0 and self.config.sample_limit < len(questions):
            question_df = pd.DataFrame(
                {
                    "idx": list(range(len(questions))),
                    "question_id": [question.question_id for question in questions],
                }
            )
            sampled_indices = (
                question_df.sample(n=self.config.sample_limit, random_state=self.config.sample_seed)["idx"].sort_values().tolist()
            )
            questions = [questions[index] for index in sampled_indices]
            print(f"sample mode enabled: randomly selected {len(questions)} questions with seed={self.config.sample_seed}")
        rows: list[QuestionResult] = []
        ok_count = 0
        todo_count = 0
        error_count = 0
        total = len(questions)
        for index, question in enumerate(questions, start=1):
            print(f"[{index}/{total}] start {question.question_id} | mode={self.config.llm_mode} | {question.raw_question}")
            intent = self.intent_parser.parse(question)
            drawable_turn_indexes = self._find_drawable_turn_indexes(question)
            main_image_index = len(drawable_turn_indexes) if drawable_turn_indexes else 1
            main_chart_question_text = question.sub_questions[max(drawable_turn_indexes)] if drawable_turn_indexes else question.raw_question
            try:
                sql, answer, preview, chart_path, graph_format, attempts, extra_note, intent_type, status = self._run_question(
                    question,
                    intent,
                    image_index=main_image_index,
                    chart_question_text=main_chart_question_text,
                )
            except Exception as exc:
                if self.config.llm_mode == "llm":
                    try:
                        sql, answer, preview, chart_path = self.query_engine.answer(
                            question,
                            intent,
                            image_index=main_image_index,
                            chart_question_text=main_chart_question_text,
                        )
                        graph_format = self._infer_template_graph_format(main_chart_question_text, intent.chart_type, chart_path)
                        intent_type = f"llm_fallback_{intent.intent_type}"
                        status = "ok" if answer and answer != "当前版本已完成任务二骨架，但该问题尚未配置专用模板，建议后续补充规则。" else "todo"
                        attempts = 0
                        extra_note = f"llm_failed_then_template_fallback: {exc}"
                    except Exception as fallback_exc:
                        sql = ""
                        answer = f"处理失败：{exc}"
                        preview = ""
                        chart_path = ""
                        graph_format = "无"
                        intent_type = "llm_nl2sql"
                        status = "error"
                        attempts = 0
                        extra_note = f"{exc}；fallback_failed: {fallback_exc}"
                else:
                    sql = ""
                    answer = f"处理失败：{exc}"
                    preview = ""
                    chart_path = ""
                    graph_format = "无"
                    intent_type = intent.intent_type
                    status = "error"
                    attempts = 0
                    extra_note = str(exc)
            chart_paths = self._build_turn_chart_paths(question, drawable_turn_indexes, chart_path, main_image_index)
            graph_format = self._combine_graph_formats(question, drawable_turn_indexes, chart_paths, graph_format)
            answer_json = self._build_answer_json(question, answer, chart_paths, drawable_turn_indexes)
            rows.append(
                QuestionResult(
                    question_id=question.question_id,
                    question_type=question.question_type,
                    original_question_json=question.original_question_json,
                    raw_question=question.raw_question,
                    intent_type=intent_type,
                    parsed_companies="；".join(intent.companies),
                    parsed_periods="；".join(intent.periods),
                    parsed_metrics="；".join(intent.metrics),
                    generated_query=sql,
                    answer_text=answer,
                    answer_json=answer_json,
                    result_preview=preview,
                    chart_path="；".join(chart_paths),
                    graph_format=graph_format,
                    status=status,
                    query_attempts=attempts,
                    note="；".join([item for item in ["；".join(intent.notes), extra_note] if item]),
                )
            )
            if status == "ok":
                ok_count += 1
            elif status == "todo":
                todo_count += 1
            else:
                error_count += 1
            print(
                f"[{index}/{total}] done  {question.question_id} | status={status} | "
                f"attempts={attempts} | ok={ok_count} todo={todo_count} error={error_count}"
            )

        df = pd.DataFrame([row.__dict__ for row in rows])
        submission_df = self._build_submission_df(df)
        submission_df.to_excel(self.config.result_xlsx, index=False)
        df.to_csv(self.config.artifacts_dir / "task2_results.csv", index=False, encoding="utf-8-sig")

        summary = {
            "question_count": len(df),
            "question_ids": list(self.config.question_ids),
            "sample_limit": self.config.sample_limit,
            "sample_seed": self.config.sample_seed if self.config.sample_limit else None,
            "ok_count": int((df["status"] == "ok").sum()),
            "todo_count": int((df["status"] == "todo").sum()),
            "error_count": int((df["status"] == "error").sum()),
            "intent_counts": df["intent_type"].value_counts().to_dict(),
        }
        with (self.config.artifacts_dir / "task2_summary.json").open("w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        return df

    def _run_question(
        self,
        question,
        intent,
        image_index: int,
        chart_question_text: str | None = None,
    ) -> tuple[str, str, str, str, str, int, str, str, str]:
        if self.config.llm_mode == "llm":
            sql, answer, preview, chart_path, graph_format, attempts, extra_note = self.llm_query_engine.answer(
                question,
                intent,
                image_index=image_index,
                chart_question_text=chart_question_text,
            )
            intent_type = "llm_nl2sql"
            status = "ok"
        else:
            sql, answer, preview, chart_path = self.query_engine.answer(
                question,
                intent,
                image_index=image_index,
                chart_question_text=chart_question_text,
            )
            intent_type = intent.intent_type
            status = "ok" if answer and answer != "当前版本已完成任务二骨架，但该问题尚未配置专用模板，建议后续补充规则。" else "todo"
            graph_format = self._infer_template_graph_format(question.raw_question, intent.chart_type, chart_path)
            attempts = 1
            extra_note = ""
        return sql, answer, preview, chart_path, graph_format, attempts, extra_note, intent_type, status

    def _build_answer_json(self, question, answer_text: str, chart_paths: list[str], drawable_turn_indexes: list[int]) -> str:
        turns = []
        cumulative_turns: list[str] = []
        chart_turn_index_set = set(drawable_turn_indexes)
        for index, sub_question in enumerate(question.sub_questions):
            cumulative_turns.append(sub_question)
            cumulative_text = " | ".join(cumulative_turns)
            cumulative_intent = self.intent_parser.parse_text(cumulative_text)
            is_chart_turn = index in chart_turn_index_set
            if index == len(question.sub_questions) - 1:
                content = answer_text
                images = self._image_list_for_turn(index, drawable_turn_indexes, chart_paths, fallback_to_last=not drawable_turn_indexes or is_chart_turn)
            else:
                content = self._build_intermediate_reply(question, cumulative_turns, cumulative_text, cumulative_intent)
                images = self._image_list_for_turn(index, drawable_turn_indexes, chart_paths, fallback_to_last=False) if is_chart_turn else []
            turns.append(
                {
                    "Q": sub_question,
                    "A": {
                        "content": content,
                        "image": images,
                    },
                }
            )
        return json.dumps(turns, ensure_ascii=False)

    def _build_turn_chart_paths(
        self,
        question,
        drawable_turn_indexes: list[int],
        main_chart_path: str,
        main_image_index: int,
    ) -> list[str]:
        if not drawable_turn_indexes:
            return [main_chart_path] if main_chart_path else []
        ordered_turns = list(drawable_turn_indexes)
        chart_paths: list[str] = []
        cumulative_turns: list[str] = []
        for index, sub_question in enumerate(question.sub_questions):
            cumulative_turns.append(sub_question)
            if index not in ordered_turns:
                continue
            image_index = ordered_turns.index(index) + 1
            if image_index == main_image_index and main_chart_path:
                chart_paths.append(main_chart_path)
                continue
            staged_chart_path = self._build_staged_chart(question, cumulative_turns, image_index, sub_question)
            if staged_chart_path:
                chart_paths.append(staged_chart_path)
        return chart_paths

    def _build_staged_chart(self, question, cumulative_turns: list[str], image_index: int, chart_question_text: str) -> str:
        cumulative_text = " | ".join(cumulative_turns)
        cumulative_intent = self.intent_parser.parse_text(cumulative_text)
        staged_question = replace(
            question,
            original_question_json=json.dumps([{"Q": item} for item in cumulative_turns], ensure_ascii=False),
            raw_question=cumulative_text,
            sub_questions=list(cumulative_turns),
        )
        try:
            if self.config.llm_mode == "llm":
                _, _, _, chart_path, _, _, _, _, status = self._run_question(
                    staged_question,
                    cumulative_intent,
                    image_index=image_index,
                    chart_question_text=chart_question_text,
                )
                return chart_path if status == "ok" else ""
            _, _, _, chart_path = self.query_engine.answer(
                staged_question,
                cumulative_intent,
                image_index=image_index,
                chart_question_text=chart_question_text,
            )
            return chart_path
        except Exception:
            return ""

    def _image_list_for_turn(
        self,
        turn_index: int,
        drawable_turn_indexes: list[int],
        chart_paths: list[str],
        fallback_to_last: bool,
    ) -> list[str]:
        if not chart_paths:
            return []
        if drawable_turn_indexes:
            ordered_turns = list(drawable_turn_indexes)
            if turn_index in ordered_turns:
                image_position = ordered_turns.index(turn_index)
                if image_position < len(chart_paths):
                    return [self._to_relative_image_path(chart_paths[image_position])]
            return []
        if fallback_to_last:
            return [self._to_relative_image_path(chart_paths[-1])]
        return []

    def _find_chart_turn_indexes(self, sub_questions: list[str]) -> set[int]:
        return {
            index
            for index, sub_question in enumerate(sub_questions)
            if self._turn_requests_chart(sub_question)
        }

    def _find_drawable_turn_indexes(self, question) -> list[int]:
        drawable: list[int] = []
        cumulative_turns: list[str] = []
        for index, sub_question in enumerate(question.sub_questions):
            cumulative_turns.append(sub_question)
            cumulative_text = " | ".join(cumulative_turns)
            cumulative_intent = self.intent_parser.parse_text(cumulative_text)
            if self._turn_requests_chart(sub_question) or cumulative_intent.intent_type == "trend_or_chart":
                drawable.append(index)
        return drawable

    def _combine_graph_formats(
        self,
        question,
        drawable_turn_indexes: list[int],
        chart_paths: list[str],
        fallback_graph_format: str,
    ) -> str:
        if not chart_paths or not drawable_turn_indexes:
            return fallback_graph_format
        labels: list[str] = []
        cumulative_turns: list[str] = []
        path_count = min(len(drawable_turn_indexes), len(chart_paths))
        drawable_turn_indexes = drawable_turn_indexes[:path_count]
        for index, sub_question in enumerate(question.sub_questions):
            cumulative_turns.append(sub_question)
            if index not in drawable_turn_indexes:
                continue
            cumulative_text = " | ".join(cumulative_turns)
            cumulative_intent = self.intent_parser.parse_text(cumulative_text)
            label = self._infer_template_graph_format(sub_question, cumulative_intent.chart_type, chart_paths[drawable_turn_indexes.index(index)])
            if label and label != "无" and label not in labels:
                labels.append(label)
        return "；".join(labels) if labels else fallback_graph_format

    def _turn_requests_chart(self, question_text: str) -> bool:
        return any(token in question_text for token in self.CHART_REQUEST_TOKENS)

    def _to_relative_image_path(self, chart_path: str) -> str:
        if not chart_path:
            return ""
        path = Path(chart_path)
        return f"./result/{path.name}"

    def _build_submission_df(self, df: pd.DataFrame) -> pd.DataFrame:
        submission = pd.DataFrame(
            {
                "编号": df["question_id"],
                "问题": df["original_question_json"],
                "SQL 查询语句": df["generated_query"],
                "图形格式": df["graph_format"].fillna("无").replace("", "无"),
                "回答": df["answer_json"],
            }
        )
        return submission

    def _build_intermediate_reply(self, question, cumulative_turns: list[str], cumulative_text: str, cumulative_intent) -> str:
        missing_slots = self._missing_slots(cumulative_text, cumulative_intent)
        if missing_slots:
            return self._build_clarification_reply(cumulative_text, cumulative_intent, missing_slots)
        staged_answer = self._try_stage_answer(question, cumulative_turns, cumulative_intent)
        if staged_answer:
            return staged_answer
        return "已收到本轮补充信息，请继续说明你希望查询的条件。"

    def _try_stage_answer(self, question, cumulative_turns: list[str], cumulative_intent) -> str:
        staged_question = replace(
            question,
            original_question_json=json.dumps([{"Q": item} for item in cumulative_turns], ensure_ascii=False),
            raw_question=" | ".join(cumulative_turns),
            sub_questions=list(cumulative_turns),
        )
        try:
            sql, answer, preview, chart_path = self.query_engine.answer(staged_question, cumulative_intent)
        except Exception:
            return ""
        if not answer:
            return ""
        if answer in {
            "未找到匹配记录。",
            "未能识别趋势分析所需指标。",
            "未能识别排序所需指标。",
            "未能识别对比所需指标。",
            "未识别到可统计的指标。",
            "当前版本已完成任务二骨架，但该问题尚未配置专用模板，建议后续补充规则。",
        }:
            return ""
        return answer

    def _infer_template_graph_format(self, question_text: str, preferred_chart_type: str | None, chart_path: str) -> str:
        if not chart_path:
            return "无"
        if any(token in question_text for token in ["双条形图", "双柱状图"]):
            return "双条形图"
        if preferred_chart_type:
            return chart_type_to_label(preferred_chart_type)
        if any(token in question_text for token in ["趋势", "变化", "走势"]):
            return "折线图"
        if any(token in question_text for token in ["水平柱状图"]):
            return "水平柱状图"
        if any(token in question_text for token in ["柱状图", "条形图", "排名", "前十", "前五", "前三", "排序"]):
            return "柱状图"
        if "饼图" in question_text:
            return "饼图"
        if "散点图" in question_text or "相关性" in question_text:
            return "散点图"
        if "直方图" in question_text or "分布" in question_text:
            return "直方图"
        if "箱线图" in question_text:
            return "箱线图"
        if "雷达图" in question_text:
            return "雷达图"
        return "折线图"

    def _build_clarification_reply(self, cumulative_text: str, intent, missing_slots: list[str]) -> str:
        if missing_slots == ["period"]:
            metric_text = intent.metrics[0] if intent.metrics else "指标"
            return f"请问你查询哪一个报告期的{metric_text}？"
        if missing_slots == ["company"]:
            return "请问你要查询哪一家公司，或者提供股票代码？"
        if missing_slots == ["metric"]:
            company_text = intent.companies[0] if intent.companies else "该公司"
            return f"请问你想查询{company_text}的哪一个财务指标？"
        prompt_map = {
            "company": "公司名称或股票代码",
            "period": "报告期",
            "metric": "查询指标",
        }
        prompt_text = "、".join(prompt_map[item] for item in missing_slots)
        return f"为了继续查询，请补充：{prompt_text}。"

    def _missing_slots(self, text: str, intent) -> list[str]:
        missing: list[str] = []
        if not self._is_broad_scope_query(text) and not (intent.companies or intent.stock_codes):
            missing.append("company")
        if not intent.metrics and not self._is_metric_agnostic_query(text):
            missing.append("metric")
        if not intent.periods and not self._is_period_optional_query(text):
            missing.append("period")
        return missing

    def _is_broad_scope_query(self, text: str) -> bool:
        broad_markers = [
            "66家",
            "所有上市公司",
            "中药公司",
            "中药上市公司",
            "行业均值",
            "行业平均",
            "哪些公司",
            "哪些企业",
            "有多少家",
            "多少家",
            "这些公司",
            "其中",
            "全行业",
        ]
        return any(marker in text for marker in broad_markers)

    def _is_metric_agnostic_query(self, text: str) -> bool:
        metric_optional_markers = ["情况如何", "怎么样", "分析一下", "分析行业", "业绩比较好"]
        return any(marker in text for marker in metric_optional_markers)

    def _is_period_optional_query(self, text: str) -> bool:
        period_optional_markers = ["近几年", "近年来", "趋势", "变化", "2022-", "2023-", "2024-", "2025-"]
        return any(marker in text for marker in period_optional_markers)
