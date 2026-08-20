# ── Stage 1: Build frontend ────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Serve frontend with nginx ─────────────────────────────────────
FROM nginx:alpine AS frontend-serve
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/frontend/dist /usr/share/nginx/html

# ── Stage 3: Backend ──────────────────────────────────────────────────────
FROM python:3.12-slim AS backend

# System deps: tesseract-ocr (pytesseract), libgl1/libglib2.0 (Pillow), libpq-dev (psycopg)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
        libpq-dev \
        gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
