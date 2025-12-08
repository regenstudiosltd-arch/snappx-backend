FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

# Run as non-root user
RUN adduser --disabled-password --gecos '' appuser
USER appuser

EXPOSE $PORT

CMD gunicorn core.wsgi:application --bind 0.0.0.0:$PORT --timeout 120 --workers 3
