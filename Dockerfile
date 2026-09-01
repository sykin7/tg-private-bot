FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY new.py ./bot.py
COPY ai_classifier.py ./ai_classifier.py
COPY rule_sync.py ./rule_sync.py
COPY env_utils.py ./env_utils.py

RUN mkdir -p /app/data

CMD ["python", "bot.py"]
