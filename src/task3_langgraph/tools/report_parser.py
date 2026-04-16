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
            for page_index in range(min(len(doc), max_pages_per_report)):
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


def _join_lines(lines: list[str]) -> str:
    text = "".join(str(line or "").strip() for line in lines if str(line or "").strip())
    return _clean_text(text)


def _paragraphize(text: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    lines = [str(line).strip() for line in str(text or "").splitlines()]
    for line in lines:
        if not line:
            if current:
                paragraph = _join_lines(current)
                if paragraph:
                    paragraphs.append(paragraph)
                current = []
            continue
        if _heading_level(line) is not None or _extract_visual_caption(line):
            if current:
                paragraph = _join_lines(current)
                if paragraph:
                    paragraphs.append(paragraph)
                current = []
            paragraphs.append(line)
            continue
        current.append(line)
    if current:
        paragraph = _join_lines(current)
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


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
    return groups


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
                paragraphs = _paragraphize(page_text)
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
    max_pages_per_report: int = 20,
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
