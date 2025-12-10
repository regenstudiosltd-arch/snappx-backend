FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# INSTALL ESSENTIAL SYSTEM DEPENDENCIES

RUN apt-get update && apt-get install -y \
    build-essential \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static files
# RUN python manage.py collectstatic --noinput

# Run as non-root user
RUN adduser --disabled-password --gecos '' appuser
USER appuser

EXPOSE $PORT

# CMD gunicorn core.wsgi:application --bind 0.0.0.0:$PORT --timeout 120 --workers 3
CMD sh -c "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120"
