FROM python:3.12-slim

WORKDIR /app
COPY server.py .
COPY static/ static/

RUN pip install --no-cache-dir fastapi uvicorn

EXPOSE 8795

ENV TACK_HOST=0.0.0.0
ENV TACK_PORT=8795
ENV TACK_DB=/data/board.db

VOLUME /data

CMD ["python", "server.py"]
