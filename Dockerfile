FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/tsconfig.app.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src
RUN npm ci && npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
# Needed so the backend can `modal deploy` to the user's account at runtime.
COPY modal_app ./modal_app
COPY content ./content
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

EXPOSE 8080
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
