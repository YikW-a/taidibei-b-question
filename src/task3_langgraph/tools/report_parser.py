from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from .report_metadata import normalize_report_metadata_with_rules

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover
    fitz = None


VISUAL_CAPTION_PATTERN = re.compile(
    r"^(?P<kind>图表?|表)\s*(?P<index>[0-9一二三四五六七八九十百零]+)\s*([:：.\-—]\s*)?(?P<caption>.*)$"
)
VISUAL_REF_PATTERN = re.compile(r"(图表?\s*[0-9一二三四五六七八九十百零]+|表\s*[0-9一二三四五六七八九十百零]+)")
PAGE_NOISE_PATTERNS = [
    re.compile(r"^第?\s*\d+\s*页(?:\s*/\s*共?\s*\d+\s*页)?$"),
    re.compile(r"^\d+\s*/\s*\d+$"),
    re.compile(r"^请务必阅读正文之后的重要声明部分$"),
    re.compile(r"^请务必阅读正文后的重要声明部分$"),
    re.compile(r"^敬请参阅最后一页特别声明$"),
    re.compile(r"^敬请参阅末页重要声明及评级说明$"),
    re.compile(r"^来源[:：].*$"),
    re.compile(r"^资料来源[:：].*$"),
    re.compile(r"^证券研究报告[:：]?.*$"),
    re.compile(r"^(公司点评报告|行业周报|行业深度报告|公司深度报告|首次覆盖报告|行业专题报告).*$"),
    re.compile(r"^市场有风险.*"),
    re.compile(r"^股票投资评级.*"),
    re.compile(r"^投资评级.*"),
    re.compile(r"^个股表现.*"),
    re.compile(r"^行业表现.*"),
    re.compile(r"^分析师[:：].*$"),
    re.compile(r"^SAC\s*登记编号[:：]?\s*.*$"),
    re.compile(r"^Email[:：].*$"),
    re.compile(r"^研究所[:：]?\s*.*$"),
    re.compile(r"^证券分析师[:：]?\s*.*$"),
    re.compile(r"^联系人[:：]?\s*.*$"),
]
HEADING_BLACKLIST = {"投资评级", "风险提示", "目录", "附录"}
LOW_INFORMATION_PATTERNS = [
    re.compile(r"总股本|总市值|流通市值|52 周内最高/最低价|第一大股东|资产负债率"),
    re.compile(r"分析师[:：]|SAC|Email[:：]"),
    re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)\s+.+$"),
]
DISCARD_PARAGRAPH_PATTERNS = [
    re.compile(r"评级说明和重要声明"),
    re.compile(r"信息披露声明"),
    re.compile(r"免责声明"),
    re.compile(r"投资评级[:：]?"),
    re.compile(r"证券的投资评级"),
    re.compile(r"行业的投资评级"),
    re.compile(r"法律声明"),
    re.compile(r"若本报告的接收人非本公司的客户"),
    re.compile(r"本研究报告仅供"),
    re.compile(r"本公司不会因接收人收到本报告而视其为客户"),
    re.compile(r"任何形式的分享证券投资收益或者分担证券投资损失"),
    re.compile(r"公司简介"),
    re.compile(r"经营范围包括[:：]"),
    re.compile(r"联系我们"),
    re.compile(r"邮编[:：]"),
    re.compile(r"公司网址[:：]"),
    re.compile(r"研究所地址[:：]"),
    re.compile(r"分析师声明"),
    re.compile(r"特别声明"),
]

TABLE_OF_CONTENTS_PATTERNS = [
    re.compile(r"^(目录|内容目录)\s*$"),
    re.compile(r"[.．·•]{6,}"),
]

DISCLAIMER_PAGE_PATTERNS = [
    re.compile(r"评级说明和重要声明"),
    re.compile(r"信息披露声明"),
    re.compile(r"免责声明"),
    re.compile(r"法律声明"),
    re.compile(r"特别声明"),
    re.compile(r"分析师声明"),
    re.compile(r"联系我们"),
]

INLINE_NOISE_PATTERNS = [
    re.compile(r"证券研究报告[:：]?", re.IGNORECASE),
    re.compile(r"(公司点评报告|行业周报|行业深度报告|公司深度报告|首次覆盖报告|行业专题报告)"),
    re.compile(r"市场有风险，投资需谨慎"),
    re.compile(r"请务必阅读正文之后的免责条款部分"),
    re.compile(r"请务必阅读正文之后的重要声明部分"),
    re.compile(r"请务必阅读正文后的重要声明部分"),
    re.compile(r"敬请参阅最后一页免责声明"),
    re.compile(r"敬请参阅末页重要声明及评级说明"),
    re.compile(r"股票投资评级"),
    re.compile(r"投资评级[:：]?"),
    re.compile(r"个股表现"),
    re.compile(r"行业表现"),
    re.compile(r"数据来源[:：]聚源.*"),
    re.compile(r"资料来源[:：].*"),
    re.compile(r"证券分析师[:：]?\s*[^。；\n]*"),
    re.compile(r"分析师[:：]?\s*[^。；\n]*"),
    re.compile(r"联系人[:：]?\s*[^。；\n]*"),
    re.compile(r"SAC\s*登记编号[:：]?\s*[^。；\n]*"),
    re.compile(r"证书编号[:：]?\s*[^。；\n]*"),
    re.compile(r"Email[:：]?\s*[^。；\n]*"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
]

INLINE_COVER_METRIC_PATTERNS = [
    re.compile(r"第一大股东[^。；\n]*"),
    re.compile(r"总股本/流通股本[^。；\n]*"),
    re.compile(r"总市值/流通市值[^。；\n]*"),
    re.compile(r"最新收盘价（?元）?[^。；\n]*"),
    re.compile(r"一年最高最低[^。；\n]*"),
    re.compile(r"52\s*周内最高/最低价[^。；\n]*"),
    re.compile(r"资产负债率\(%\)[^。；\n]*"),
    re.compile(r"近3个月换手率\(%\)[^。；\n]*"),
]


def _normalize_file_key(name: str) -> str:
    text = str(name or "").strip()
    text = text.replace("/", "_").replace("\\", "_")
    text = re.sub(r"\s+", "", text)
    return text.lower()


def _build_pdf_lookup(directory: Path) -> dict[str, Path]:
    lookup: dict[str, Path] = {}
    if not directory.exists():
        return lookup
    for path in directory.glob("*.pdf"):
        lookup[_normalize_file_key(path.stem)] = path
    return lookup


def _resolve_pdf_path(title: str, directory: Path, lookup: dict[str, Path]) -> Path | None:
    key = _normalize_file_key(title)
    if key in lookup:
        return lookup[key]
    candidate = directory / f"{title}.pdf"
    if candidate.exists():
        return candidate
    return None


def _extract_pdf_pages(pdf_path: Path, max_pages_per_report: int) -> list[dict[str, Any]]:
    if fitz is None or not pdf_path.exists():
        return []
    pages: list[dict[str, Any]] = []
    try:
        doc = fitz.open(pdf_path)
        try:
            page_limit = len(doc) if max_pages_per_report <= 0 else min(len(doc), max_pages_per_report)
            for page_index in range(page_limit):
                page = doc.load_page(page_index)
                text = page.get_text("text")
                text = _clean_text(text)
                if text:
                    pages.append({"page": page_index + 1, "text": text})
        finally:
            doc.close()
    except Exception:
        return []
    return pages


def _clean_text(text: str) -> str:
    text = str(text or "")
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_inline_noise(text: str) -> str:
    cleaned = str(text or "")
    for pattern in INLINE_NOISE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    for pattern in INLINE_COVER_METRIC_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"(?:\s*[|｜]+\s*)+", " ", cleaned)
    cleaned = re.sub(r"(?:\s*[-—–]{2,}\s*)+", " ", cleaned)
    return _clean_text(cleaned)


def _is_noise_line(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return True
    if len(stripped) <= 2 and re.fullmatch(r"\d+", stripped):
        return True
    if re.fullmatch(r"[0-9. /%+-]+", stripped) and len(stripped) <= 32:
        return True
    for pattern in PAGE_NOISE_PATTERNS:
        if pattern.match(stripped):
            return True
    return False


def _split_dense_sentence(text: str) -> list[str]:
    stripped = _strip_inline_noise(text)
    if not stripped:
        return []
    if len(stripped) < 220:
        return [stripped]
    parts = re.split(r"(?<=[。！？；])", stripped)
    pieces = [part.strip() for part in parts if part.strip()]
    return pieces or [stripped]


def _looks_like_cover_metric_block(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return True
    hits = 0
    for pattern in LOW_INFORMATION_PATTERNS:
        if pattern.search(stripped):
            hits += 1
    digit_density = sum(ch.isdigit() for ch in stripped) / max(1, len(stripped))
    has_sentence = bool(re.search(r"[。！？；]", stripped))
    return hits >= 2 or (digit_density > 0.18 and not has_sentence)


def _is_table_of_contents_page(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    hit_count = 0
    for pattern in TABLE_OF_CONTENTS_PATTERNS:
        if pattern.search(normalized):
            hit_count += 1
    dotted_lines = len(re.findall(r"[.．]{6,}", normalized))
    return hit_count >= 2 or ("目录" in normalized and dotted_lines >= 3)


def _is_disclaimer_page(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    hits = sum(1 for pattern in DISCLAIMER_PAGE_PATTERNS if pattern.search(normalized))
    return hits >= 2


def _is_low_information_paragraph(text: str) -> bool:
    stripped = _strip_inline_noise(text)
    if not stripped:
        return True
    if len(stripped) < 18:
        return True
    for pattern in DISCARD_PARAGRAPH_PATTERNS:
        if pattern.search(stripped):
            return True
    if re.fullmatch(r"[A-Za-z0-9 ./%+\-—]+", stripped):
        return True
    if re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)\s*.*", stripped):
        return True
    if _looks_like_cover_metric_block(stripped):
        return True
    return False


def _split_into_chunks(
    text: str,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> list[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size_chars:
        return [cleaned]
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size_chars - chunk_overlap_chars)
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size_chars)
        chunks.append(cleaned[start:end].strip())
        if end >= len(cleaned):
            break
        start += step
    return [chunk for chunk in chunks if chunk]


def _heading_level(text: str) -> int | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    if VISUAL_CAPTION_PATTERN.match(stripped):
        return None
    if stripped in HEADING_BLACKLIST:
        return 1
    if len(stripped) > 40:
        return None
    if re.fullmatch(r"[0-9./ %+\-]+", stripped):
        return None
    if re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", stripped):
        return None
    if re.match(r"^第[一二三四五六七八九十百零]+[章节部分篇]", stripped):
        return 1
    if re.match(r"^[一二三四五六七八九十百零]+、", stripped):
        return 1
    if re.match(r"^[（(][一二三四五六七八九十百零]+[）)]", stripped):
        return 2
    if re.match(r"^\d+\.\d+\.\d+", stripped):
        return 3
    if re.match(r"^\d+\.\d+", stripped):
        return 2
    if re.match(r"^\d+[、.．]", stripped):
        return 1
    if len(stripped) <= 36 and "：" in stripped and not re.search(r"[。！？；]$", stripped):
        return 1
    return None


def _extract_visual_caption(text: str) -> dict[str, Any] | None:
    stripped = str(text or "").strip()
    match = VISUAL_CAPTION_PATTERN.match(stripped)
    if not match:
        return None
    kind = str(match.group("kind") or "").strip()
    index = str(match.group("index") or "").strip()
    caption = str(match.group("caption") or "").strip()
    label = f"{kind}{index}"
    return {
        "label": label,
        "kind": "figure" if "图" in kind else "table",
        "caption": caption or stripped,
    }


def _extract_visual_refs(text: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in VISUAL_REF_PATTERN.findall(str(text or "")):
        label = re.sub(r"\s+", "", str(raw))
        if not label or label in seen:
            continue
        seen.add(label)
        refs.append(
            {
                "label": label,
                "kind": "figure" if "图" in label else "table",
            }
        )
    return refs


def _looks_like_page_topic_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _heading_level(stripped) is not None:
        return True
    if len(stripped) > 48:
        return False
    if re.search(r"[。！？；]", stripped):
        return False
    if re.fullmatch(r"[0-9A-Za-z ./%+\-]+", stripped):
        return False
    return bool(re.match(r"^[一二三四五六七八九十0-9A-Za-z（）().、\-—\s]*[:：]", stripped))


def _is_continuation_fragment(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if len(stripped) > 120:
        return False
    if re.match(r"^[0-9][0-9.,%％+\-]*[。；，、]", stripped):
        return True
    if re.match(r"^[)\]】%％、，。；]", stripped):
        return True
    if re.match(r"^(同比|环比|其中|同时|此外|另外|而|并且|且)", stripped):
        return True
    return False


def _join_lines(lines: list[str]) -> str:
    text = "".join(str(line or "").strip() for line in lines if str(line or "").strip())
    return _clean_text(text)


def _paragraphize(text: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    lines = [str(line).strip() for line in str(text or "").splitlines()]
    for line in lines:
        line = _strip_inline_noise(line)
        if not line:
            if current:
                paragraph = _join_lines(current)
                if paragraph:
                    paragraphs.extend(_split_dense_sentence(paragraph))
                current = []
            continue
        if _is_noise_line(line):
            if current:
                paragraph = _join_lines(current)
                if paragraph:
                    paragraphs.extend(_split_dense_sentence(paragraph))
                current = []
            continue
        if _heading_level(line) is not None or _extract_visual_caption(line):
            if current:
                paragraph = _join_lines(current)
                if paragraph:
                    paragraphs.extend(_split_dense_sentence(paragraph))
                current = []
            paragraphs.append(line)
            continue
        current.append(line)
    if current:
        paragraph = _join_lines(current)
        if paragraph:
            paragraphs.extend(_split_dense_sentence(paragraph))
    filtered: list[str] = []
    for paragraph in paragraphs:
        stripped = paragraph.strip()
        if len(stripped) < 8:
            continue
        if _is_low_information_paragraph(stripped):
            continue
        filtered.append(stripped)
    if len(filtered) >= 2 and _is_continuation_fragment(filtered[0]):
        filtered[1] = f"{filtered[0]} {filtered[1]}".strip()
        filtered = filtered[1:]
    return filtered


def _split_paragraph_groups(
    paragraphs: list[str],
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> list[list[str]]:
    if not paragraphs:
        return []
    groups: list[list[str]] = []
    current: list[str] = []
    current_len = 0

    def _paragraph_cost(paragraph: str) -> int:
        return len(paragraph) + 2

    for paragraph in paragraphs:
        cost = _paragraph_cost(paragraph)
        if current and current_len + cost > chunk_size_chars:
            groups.append(list(current))
            overlap: list[str] = []
            overlap_len = 0
            for prev in reversed(current):
                overlap.insert(0, prev)
                overlap_len += _paragraph_cost(prev)
                if overlap_len >= chunk_overlap_chars:
                    break
            current = overlap
            current_len = sum(_paragraph_cost(item) for item in current)
        if cost > chunk_size_chars and not current:
            sub_chunks = _split_into_chunks(paragraph, chunk_size_chars, chunk_overlap_chars)
            groups.extend([[item] for item in sub_chunks])
            continue
        current.append(paragraph)
        current_len += cost
    if current:
        groups.append(list(current))
    merged: list[list[str]] = []
    for group in groups:
        group_text_len = sum(len(item) for item in group)
        if merged and group_text_len < max(120, chunk_overlap_chars):
            merged[-1].extend(group)
        else:
            merged.append(group)
    return merged


def _format_chunk_text(
    paragraphs: list[str],
    *,
    section_title: str,
    subsection_title: str,
) -> str:
    prefix: list[str] = []
    if section_title:
        prefix.append(section_title)
    if subsection_title and subsection_title != section_title:
        prefix.append(subsection_title)
    body = "\n\n".join(paragraphs).strip()
    if prefix:
        return "\n".join(prefix + ([body] if body else []))
    return body


def _metadata_fallback_text(row: dict[str, Any], source_type: str) -> str:
    metadata = normalize_report_metadata_with_rules(row, source_type)
    if source_type == "stock":
        items = [
            str(metadata.get("title", "") or ""),
            str(metadata.get("company", "") or ""),
            str(metadata.get("industry", "") or ""),
            str(metadata.get("organization", "") or ""),
            str(metadata.get("rating_current", "") or ""),
            str(metadata.get("forecast_eps_this_year", "") or ""),
            str(metadata.get("forecast_pe_this_year", "") or ""),
        ]
    else:
        items = [
            str(metadata.get("title", "") or ""),
            str(metadata.get("industry", "") or ""),
            str(metadata.get("organization", "") or ""),
            str(metadata.get("rating_current", "") or ""),
        ]
    return "；".join(item for item in items if item)


def _rows_to_chunks(
    df: pd.DataFrame,
    source_type: str,
    report_dir: Path,
    field_descriptions: dict[str, dict[str, str]] | None,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    max_pages_per_report: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    lookup = _build_pdf_lookup(report_dir)
    for row in df.to_dict(orient="records"):
        metadata = normalize_report_metadata_with_rules(row, source_type, field_descriptions=field_descriptions)
        title = str(metadata.get("title", "") or "").strip()
        pdf_path = _resolve_pdf_path(title, report_dir, lookup)
        pages = _extract_pdf_pages(pdf_path, max_pages_per_report) if pdf_path else []
        if pages:
            current_section_title = ""
            current_subsection_title = ""
            for page_payload in pages:
                page_number = int(page_payload["page"])
                page_text = str(page_payload["text"])
                if _is_table_of_contents_page(page_text) or _is_disclaimer_page(page_text):
                    current_section_title = ""
                    current_subsection_title = ""
                    continue
                paragraphs = _paragraphize(page_text)
                if paragraphs:
                    first_paragraph = paragraphs[0]
                    if _looks_like_page_topic_heading(first_paragraph):
                        current_section_title = first_paragraph
                        current_subsection_title = ""
                body_buffer: list[str] = []
                page_chunk_index = 0

                def _flush_body_buffer() -> None:
                    nonlocal page_chunk_index
                    if not body_buffer:
                        return
                    grouped = _split_paragraph_groups(body_buffer, chunk_size_chars, chunk_overlap_chars)
                    for group in grouped:
                        chunk_text = _format_chunk_text(
                            group,
                            section_title=current_section_title,
                            subsection_title=current_subsection_title,
                        )
                        if not chunk_text:
                            continue
                        page_chunk_index += 1
                        chunks.append(
                            {
                                "chunk_id": f"{source_type}::{title}::p{page_number}::body::{page_chunk_index}",
                                **metadata,
                                "path": str(pdf_path) if pdf_path else "",
                                "page": page_number,
                                "page_start": page_number,
                                "page_end": page_number,
                                "chunk_index": page_chunk_index,
                                "chunk_type": "body",
                                "section_title": current_section_title,
                                "subsection_title": current_subsection_title,
                                "text": chunk_text,
                                "figure_table_refs": _extract_visual_refs(chunk_text),
                                "content_source": "pdf_page",
                            }
                        )
                    body_buffer.clear()

                for paragraph in paragraphs:
                    heading_level = _heading_level(paragraph)
                    visual_caption = _extract_visual_caption(paragraph)
                    if heading_level is not None:
                        _flush_body_buffer()
                        if heading_level == 1:
                            current_section_title = paragraph
                            current_subsection_title = ""
                        elif heading_level >= 2:
                            current_subsection_title = paragraph
                        continue
                    if visual_caption is not None:
                        _flush_body_buffer()
                        page_chunk_index += 1
                        chunks.append(
                            {
                                "chunk_id": f"{source_type}::{title}::p{page_number}::visual::{page_chunk_index}",
                                **metadata,
                                "path": str(pdf_path) if pdf_path else "",
                                "page": page_number,
                                "page_start": page_number,
                                "page_end": page_number,
                                "chunk_index": page_chunk_index,
                                "chunk_type": "visual_caption",
                                "section_title": current_section_title,
                                "subsection_title": current_subsection_title,
                                "text": paragraph,
                                "figure_table_refs": [visual_caption],
                                "visual_caption": visual_caption,
                                "content_source": "pdf_page",
                            }
                        )
                        continue
                    body_buffer.append(paragraph)

                _flush_body_buffer()
        else:
            fallback_text = _metadata_fallback_text(row, source_type)
            if fallback_text:
                chunks.append(
                    {
                        "chunk_id": f"{source_type}::{title}::meta",
                        **metadata,
                        "path": str(pdf_path) if pdf_path else "",
                        "page": 0,
                        "page_start": 0,
                        "page_end": 0,
                        "chunk_index": 0,
                        "chunk_type": "metadata_fallback",
                        "section_title": "",
                        "subsection_title": "",
                        "text": fallback_text,
                        "figure_table_refs": _extract_visual_refs(fallback_text),
                        "content_source": "metadata_fallback",
                    }
                )
    return chunks


def build_report_chunk_manifest(
    stock_reports: pd.DataFrame,
    industry_reports: pd.DataFrame,
    stock_report_dir: Path,
    industry_report_dir: Path,
    field_descriptions: dict[str, dict[str, str]] | None = None,
    chunk_size_chars: int = 900,
    chunk_overlap_chars: int = 150,
    max_pages_per_report: int = 100,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    chunks.extend(
        _rows_to_chunks(
            stock_reports,
            "stock",
            stock_report_dir,
            field_descriptions,
            chunk_size_chars,
            chunk_overlap_chars,
            max_pages_per_report,
        )
    )
    chunks.extend(
        _rows_to_chunks(
            industry_reports,
            "industry",
            industry_report_dir,
            field_descriptions,
            chunk_size_chars,
            chunk_overlap_chars,
            max_pages_per_report,
        )
    )
    return chunks


__all__ = ["build_report_chunk_manifest"]
