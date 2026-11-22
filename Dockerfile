# Development image; not a hardened production deployment.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade 'pip==26.3' 'setuptools==84.2.1' \
    && python -m pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "python -m tools.wait_for_database && python manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8000"]
