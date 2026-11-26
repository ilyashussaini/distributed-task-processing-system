FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY task_system ./task_system
COPY migrations ./migrations
COPY alembic.ini .
RUN chmod -R a+rX task_system migrations alembic.ini

USER 10001:10001
CMD ["uvicorn", "task_system.api:app", "--host", "0.0.0.0", "--port", "8000"]
