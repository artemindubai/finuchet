# Финучёт: сборка фронта отдельной ступенью, в итоговый образ едет только dist (ARCHITECTURE §11.2).
FROM node:20-slim AS front
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements-bot.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt -r /app/backend/requirements-bot.txt
COPY backend /app/backend
COPY tools /app/tools
COPY --from=front /front/dist /app/frontend/dist
# База и бэкапы — на volume /data, иначе редеплой стирает деньги (грабля 3 журнала).
ENV DB_PATH=/data/finuchet.db \
    BACKUP_DIR=/data/backups \
    TMP_DIR=/data/tmp \
    TZ=Asia/Dubai \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
EXPOSE 8080
# Запуск ровно тот же, что локально: из корня, без --app-dir (§11.1).
CMD ["sh", "-c", "python -m uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
