FROM python:3.13-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app

FROM base AS runtime
COPY requirements.txt requirements-lock.txt ./
RUN pip install -r requirements.txt
COPY app ./app
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
COPY requirements-dev.txt pyproject.toml ./
RUN pip install -r requirements-dev.txt
COPY tests ./tests
USER app
CMD ["sh", "-c", "ruff check --no-cache . && ruff format --check --no-cache . && python -m pytest -p no:cacheprovider"]
