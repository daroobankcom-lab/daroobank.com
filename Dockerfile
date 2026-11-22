# Development image; not a hardened production deployment.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-build.txt ./
RUN python -m pip install --no-cache-dir --require-hashes --upgrade -r requirements-build.txt \
    && python -m pip install --no-cache-dir --require-hashes -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "python -m tools.wait_for_database && python manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8000"]
