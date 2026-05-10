"""多格式教材解析。

- PDF: PyMuPDF 逐页 + 章节正则
- MD/TXT: 文本 + 章节正则
- DOCX: python-docx
"""
from __future__ import annotations
import re
import io
from typing import List

from backend.models.schemas import Textbook, Chapter, SourceBlock

CHAPTER_RE = re.compile(
    r"^\s*(?:第\s*[一二三四五六七八九十百零0-9]+\s*[章节]|"
    r"Chapter\s+\d+|"
    r"#{1,3}\s+第?[\d一二三四五六七八九十]+[章节]?)\s*.*$",
    re.M | re.I,
)


def parse(data: bytes, ext: str, filename: str, textbook_id: str) -> Textbook:
    ext = (ext or "").lower()
    try:
        if ext == "pdf":
            return parse_pdf(data, filename, textbook_id)
        if ext in {"md", "markdown"}:
            return _from_text(data.decode("utf-8", errors="ignore"), filename, textbook_id)
        if ext == "txt":
            return _from_text(_smart_decode(data), filename, textbook_id)
        if ext == "docx":
            return parse_docx(data, filename, textbook_id)
    except Exception as e:
        print(f"[parser] {filename} parse error: {e}")
    return Textbook(textbook_id=textbook_id, filename=filename,
                    title=filename.rsplit(".", 1)[0])


def _smart_decode(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "gb18030", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def parse_pdf(data: bytes, filename: str, textbook_id: str) -> Textbook:
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    pages: List[tuple[int, str]] = []
    blocks: list[SourceBlock] = []
    for i, page in enumerate(doc, start=1):
        text_blocks: list[str] = []
        page_dict = page.get_text("dict") or {}
        for block_index, block in enumerate(page_dict.get("blocks", []) or []):
            bbox = [round(float(v), 2) for v in block.get("bbox", [])[:4]]
            block_type = int(block.get("type", 0))
            block_id = f"{textbook_id}_p{i:04d}_b{block_index:03d}"
            if block_type == 0:
                text = _text_from_pdf_block(block)
                if not text.strip():
                    continue
                text_blocks.append(text)
                blocks.append(SourceBlock(
                    block_id=block_id,
                    kind="text",
                    page=i,
                    bbox=bbox,
                    text=text,
                ))
            elif block_type == 1:
                blocks.append(SourceBlock(
                    block_id=block_id,
                    kind="image",
                    page=i,
                    bbox=bbox,
                    text=f"PDF 第 {i} 页图像/图表区域",
                    image_ext=block.get("ext"),
                ))
        text = "\n".join(text_blocks) if text_blocks else (page.get_text("text") or "")
        lines = [ln for ln in text.split("\n") if len(ln.strip()) > 1]
        pages.append((i, "\n".join(lines)))
    full_text = "\n".join(t for _, t in pages)
    chapters = _split_chapters_with_pages(pages)
    _attach_blocks_to_chapters(blocks, chapters)
    return Textbook(
        textbook_id=textbook_id, filename=filename,
        title=filename.rsplit(".", 1)[0],
        total_pages=len(pages),
        total_chars=len(full_text),
        chapters=chapters,
        blocks=blocks,
    )


def _text_from_pdf_block(block: dict) -> str:
    lines: list[str] = []
    for line in block.get("lines", []) or []:
        spans = line.get("spans", []) or []
        line_text = "".join(str(span.get("text", "")) for span in spans).strip()
        if line_text:
            lines.append(line_text)
    return "\n".join(lines)


def _attach_blocks_to_chapters(blocks: list[SourceBlock], chapters: list[Chapter]) -> None:
    if not chapters:
        return
    for block in blocks:
        chapter = next(
            (ch for ch in chapters if ch.page_start <= block.page <= ch.page_end),
            chapters[0],
        )
        block.chapter_id = chapter.chapter_id
        block.chapter = chapter.title
        chapter.block_ids.append(block.block_id)


def _split_chapters_with_pages(pages: List[tuple[int, str]]) -> List[Chapter]:
    char_pages: list[int] = []
    parts: list[str] = []
    for pno, text in pages:
        parts.append(text + "\n")
        char_pages.extend([pno] * (len(text) + 1))
    full = "".join(parts)

    matches = list(CHAPTER_RE.finditer(full))
    chapters: list[Chapter] = []
    if not matches:
        chapters.append(Chapter(
            chapter_id="ch_01", title="全文",
            page_start=pages[0][0] if pages else 1,
            page_end=pages[-1][0] if pages else 1,
            content=full[:300000],
            char_count=len(full),
        ))
        return chapters

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        body = full[start:end]
        ps = char_pages[start] if start < len(char_pages) else 1
        pe = char_pages[end - 1] if end - 1 < len(char_pages) else ps
        chapters.append(Chapter(
            chapter_id=f"ch_{i+1:02d}",
            title=m.group().strip()[:80],
            page_start=ps, page_end=pe,
            content=body, char_count=len(body),
        ))
    return chapters


def parse_docx(data: bytes, filename: str, textbook_id: str) -> Textbook:
    from docx import Document
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return _from_text(text, filename, textbook_id)


def _from_text(text: str, filename: str, textbook_id: str) -> Textbook:
    matches = list(CHAPTER_RE.finditer(text))
    chapters: list[Chapter] = []
    if not matches:
        chapters.append(Chapter(
            chapter_id="ch_01", title="全文",
            page_start=1, page_end=1,
            content=text, char_count=len(text),
        ))
    else:
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end]
            chapters.append(Chapter(
                chapter_id=f"ch_{i+1:02d}",
                title=m.group().strip()[:80],
                page_start=1, page_end=1,
                content=body, char_count=len(body),
            ))
    blocks = [
        SourceBlock(
            block_id=f"{textbook_id}_{ch.chapter_id}_b000",
            kind="text",
            page=ch.page_start or 1,
            bbox=[],
            text=ch.content,
            chapter_id=ch.chapter_id,
            chapter=ch.title,
        )
        for ch in chapters
    ]
    for ch, block in zip(chapters, blocks):
        ch.block_ids = [block.block_id]
    return Textbook(
        textbook_id=textbook_id, filename=filename,
        title=filename.rsplit(".", 1)[0],
        total_pages=1, total_chars=len(text),
        chapters=chapters,
        blocks=blocks,
    )
