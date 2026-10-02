FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --upgrade pip && pip install --requirement requirements.txt

FROM base AS development

RUN pip install --requirement requirements-dev.txt
COPY --chown=app:app . .

USER app
EXPOSE 8000

CMD ["sh", "-c", "exec fastapi dev app/main.py --host 0.0.0.0 --port \"${PORT:-8000}\""]

FROM base AS production

COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app

USER app
EXPOSE 8000

CMD ["sh", "-c", "exec fastapi run app/main.py --host 0.0.0.0 --port \"${PORT:-8000}\""]
