FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN sed -i 's/\r$//' scripts/start.sh && chmod +x scripts/start.sh

ENV PYTHONPATH=/app
ENV PORT=8002
EXPOSE 8002

CMD ["sh", "scripts/start.sh"]

