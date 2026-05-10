# ---------- Backend image (FastAPI + uvicorn) ----------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 系统依赖：PyMuPDF / pillow 等需要的少量库
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 先复制 requirements 以利用层缓存
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 复制后端源码（前端打包产物在另一个镜像里走 nginx）
COPY backend ./backend
COPY .env.example ./.env.example

# 运行时持久化目录（state.py 写入）
RUN mkdir -p /app/backend/storage/data /app/backend/storage/uploads

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
