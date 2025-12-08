FROM python:3.9-slim

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN groupadd -g 5678 appuser && \
    useradd -r -u 5678 -g appuser appuser

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data && \
    chown -R appuser:appuser /app

EXPOSE 8080

VOLUME /app/data

USER appuser

CMD ["python", "main.py"]
