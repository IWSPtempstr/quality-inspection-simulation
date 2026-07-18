FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*
COPY services/scheduler-py/pyproject.toml /app/pyproject.toml
COPY services/scheduler-py/src /app/src
RUN pip install --no-cache-dir .
EXPOSE 8080
CMD ["python", "-c", "from scheduler.api.app import create_app; from scheduler.conf.settings import SchedulerSettings; import uvicorn; uvicorn.run(create_app(SchedulerSettings()), host='0.0.0.0', port=8080)"]
