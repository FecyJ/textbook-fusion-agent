from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import fitz
from docx import Document

from .schemas import Chapter, Textbook


CHAPTER_PATTERNS = [
    re.compile(r"^\s*第[一二三四五六七八九十百零〇\d]+[章节篇]\s*[\w\u4e00-\u9fff、：:\- ]{0,40}$"),
    re.compile(r"^\s*Chapter\s+\d+[\w\s:：\-]{0,60}$", re.IGNORECASE),
]


def parse_textbook(textbook: Textbook) -> Textbook:
    path = Path(textbook.upload_path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        chapters, total_pages = parse_pdf(path)
    elif suffix in {".md", ".markdown"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        chapters, total_pages = parse_plain_text(text, title=path.stem, heading_regex=r"^\s{0,3}#{1,3}\s+(.+)$")
    elif suffix == ".txt":
        text = path.read_text(encoding="utf-8", errors="ignore")
        chapters, total_pages = parse_plain_text(text, title=path.stem)
    elif suffix == ".docx":
        doc = Document(str(path))
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())
        chapters, total_pages = parse_plain_text(text, title=path.stem)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    textbook.status = "completed"
    textbook.total_pages = total_pages
    textbook.chapters = chapters
    textbook.total_chars = sum(chapter.char_count for chapter in chapters)
    textbook.title = infer_title(textbook.filename)
    textbook.error = None
    return textbook


def parse_pdf(path: Path) -> tuple[list[Chapter], int]:
    pages: list[tuple[int, str]] = []
    with fitz.open(path) as document:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text")
            pages.append((index, clean_page_text(text)))
        total_pages = document.page_count
    return build_chapters_from_pages(pages, title=path.stem), total_pages


def parse_plain_text(text: str, title: str, heading_regex: str | None = None) -> tuple[list[Chapter], int]:
    lines = [line.rstrip() for line in text.splitlines()]
    heading_pattern = re.compile(heading_regex) if heading_regex else None
    chapters: list[Chapter] = []
    current_title = title
    buffer: list[str] = []
    chapter_index = 1

    def flush() -> None:
        nonlocal chapter_index, buffer, current_title
        content = "\n".join(buffer).strip()
        if not content:
            return
        chapters.append(
            Chapter(
                chapter_id=f"ch_{chapter_index:03d}",
                title=current_title,
                page_start=1,
                page_end=1,
                content=content,
                char_count=len(content),
            )
        )
        chapter_index += 1
        buffer = []

    for line in lines:
        heading = False
        if heading_pattern:
            match = heading_pattern.match(line)
            if match:
                heading = True
                new_title = match.group(1).strip()
        else:
            heading = is_chapter_heading(line)
            new_title = line.strip()
        if heading:
            flush()
            current_title = new_title
        else:
            buffer.append(line)
    flush()

    if not chapters:
        content = text.strip()
        chapters = [
            Chapter(
                chapter_id="ch_001",
                title=title,
                page_start=1,
                page_end=1,
                content=content,
                char_count=len(content),
            )
        ]
    return chapters, 1


def build_chapters_from_pages(pages: list[tuple[int, str]], title: str) -> list[Chapter]:
    chapters: list[dict[str, object]] = []
    current = {"title": title, "page_start": pages[0][0] if pages else 1, "texts": []}

    for page_number, text in pages:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        heading = next((line for line in lines[:12] if is_chapter_heading(line)), None)
        if heading and current["texts"]:
            chapters.append({**current, "page_end": max(page_number - 1, int(current["page_start"]))})
            current = {"title": normalize_heading(heading), "page_start": page_number, "texts": []}
        current["texts"].append(text)

    if current["texts"]:
        chapters.append({**current, "page_end": pages[-1][0] if pages else 1})

    if len(chapters) <= 1 and pages:
        chapters = split_pages_evenly(pages, title)

    result: list[Chapter] = []
    for index, chapter in enumerate(chapters, start=1):
        content = "\n".join(chapter["texts"]).strip()
        if not content:
            continue
        result.append(
            Chapter(
                chapter_id=f"ch_{index:03d}",
                title=str(chapter["title"]),
                page_start=int(chapter["page_start"]),
                page_end=int(chapter["page_end"]),
                content=content,
                char_count=len(content),
            )
        )
    return result


def split_pages_evenly(pages: list[tuple[int, str]], title: str, pages_per_chunk: int = 20) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    for offset in range(0, len(pages), pages_per_chunk):
        batch = pages[offset : offset + pages_per_chunk]
        chunks.append(
            {
                "title": f"{title} 第{len(chunks) + 1}部分",
                "page_start": batch[0][0],
                "page_end": batch[-1][0],
                "texts": [text for _, text in batch],
            }
        )
    return chunks


def clean_page_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    filtered = []
    for line in lines:
        if not line:
            continue
        line = normalize_pdf_line(line)
        if re.fullmatch(r"第?\s*\d+\s*页\s*/?\s*共?\s*\d*\s*页?", line):
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if is_running_header_or_footer(line):
            continue
        filtered.append(line)
    return normalize_text_flow("\n".join(filtered))


def normalize_pdf_line(line: str) -> str:
    line = line.replace("\u2002", " ").replace("\u2003", " ").replace("\u200a", " ")
    line = re.sub(r"\s+", " ", line).strip()
    line = re.sub(r"([A-Za-z])-\s+([A-Za-z])", r"\1\2", line)
    line = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", line)
    return line


def normalize_text_flow(text: str) -> str:
    text = re.sub(r"(?<=[\u4e00-\u9fff])\n(?=[\u4e00-\u9fff，。；：、（）])", "", text)
    text = re.sub(r"(?<=[（(])\s+", "", text)
    text = re.sub(r"\s+(?=[）)])", "", text)
    return text.strip()


def is_running_header_or_footer(line: str) -> bool:
    if re.fullmatch(r"第[一二三四五六七八九十\d]+章[·\s\u4e00-\u9fff]{0,20}", line) and len(line) <= 18:
        return False
    if re.fullmatch(r"[IVXLC]+", line):
        return True
    if re.fullmatch(r"\d+\s*[|｜]\s*[\u4e00-\u9fffA-Za-z ]{1,20}", line):
        return True
    return False


def is_chapter_heading(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) > 60:
        return False
    return any(pattern.match(stripped) for pattern in CHAPTER_PATTERNS)


def normalize_heading(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" ：:")


def infer_title(filename: str) -> str:
    return Path(filename).stem


def new_textbook(filename: str, file_format: str, size_bytes: int, upload_path: str) -> Textbook:
    return Textbook(
        textbook_id=f"book_{uuid4().hex[:10]}",
        filename=filename,
        title=infer_title(filename),
        file_format=file_format,
        size_bytes=size_bytes,
        upload_path=upload_path,
        status="pending",
    )
