FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DB_FILE=/data/bot_data.db
RUN mkdir -p /data
VOLUME /data
CMD ["python", "your_bot_script.py"]
