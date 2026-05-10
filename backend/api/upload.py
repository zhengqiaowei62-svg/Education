"""教材上传与解析路由。"""
import uuid
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.models.schemas import (
    UploadFileStatus, UploadResponse, Textbook,
)
from backend.core import parser
from backend.storage import state

router = APIRouter()

ALLOWED_EXTS = {"pdf", "md", "markdown", "txt", "docx"}


@router.post("/upload", response_model=UploadResponse)
async def upload_files(files: List[UploadFile] = File(...)):
    results: list[UploadFileStatus] = []
    for f in files:
        ext = (f.filename or "").rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXTS:
            results.append(UploadFileStatus(
                filename=f.filename or "",
                size=0, format=ext, status="failed",
                message=f"unsupported format: {ext}",
            ))
            continue

        data = await f.read()
        textbook_id = f"book_{uuid.uuid4().hex[:8]}"
        try:
            tb = parser.parse(data, ext, f.filename or "untitled", textbook_id)
            state.TEXTBOOKS[textbook_id] = tb
            results.append(UploadFileStatus(
                filename=f.filename or "",
                size=len(data), format=ext, status="done",
                textbook_id=textbook_id,
                message=f"{len(tb.chapters)} 章 / {tb.total_chars} 字 / {len(tb.blocks)} 区块",
            ))
        except Exception as e:
            results.append(UploadFileStatus(
                filename=f.filename or "",
                size=len(data), format=ext, status="failed",
                message=str(e)[:200],
            ))

    return UploadResponse(files=results)


@router.get("/textbooks", response_model=List[Textbook])
def list_textbooks():
    # 列表场景下不返回 chapters.content，避免响应过大
    light = []
    for tb in state.TEXTBOOKS.values():
        light.append(Textbook(
            textbook_id=tb.textbook_id,
            filename=tb.filename, title=tb.title,
            total_pages=tb.total_pages, total_chars=tb.total_chars,
            chapters=[c.model_copy(update={"content": ""}) for c in tb.chapters],
            blocks=[],
        ))
    return light


@router.get("/textbooks/{textbook_id}", response_model=Textbook)
def get_textbook(textbook_id: str):
    tb = state.TEXTBOOKS.get(textbook_id)
    if not tb:
        raise HTTPException(status_code=404, detail="textbook not found")
    return tb


@router.delete("/textbooks/{textbook_id}")
def delete_textbook(textbook_id: str):
    state.TEXTBOOKS.pop(textbook_id, None)
    state.GRAPHS.pop(textbook_id, None)
    return {"ok": True}
