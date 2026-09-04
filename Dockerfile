# Contract RAG demo. Build:  docker build -t contract-rag .
# Run:   docker run -p 8090:8090 -v contract-rag-data:/app/data --env-file .env contract-rag
#
# If the LLM/embeddings run in Ollama on the host, point the container at it:
#   LLM_BASE_URL=http://host.docker.internal:11434/v1   (Mac/Windows)
#   and add --add-host=host.docker.internal:host-gateway on Linux.
FROM python:3.12-slim

# tesseract + poppler enable OCR for scanned PDFs (optional but cheap here)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /app/data \
    && chown -R app:app /app

COPY --chown=app:app app ./app
COPY --chown=app:app static ./static

USER app

EXPOSE 8090
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
