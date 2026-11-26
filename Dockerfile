FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/ backend/
COPY tests/ tests/
USER 65534:65534
CMD ["python", "-m", "unittest", "discover", "-v"]
