FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*
COPY services/ai-py/pyproject.toml /app/pyproject.toml
COPY services/ai-py/src /app/src
COPY services/ai-py/prompts /app/prompts
RUN pip install --no-cache-dir .
EXPOSE 8080
CMD ["uvicorn", "ai_service.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
