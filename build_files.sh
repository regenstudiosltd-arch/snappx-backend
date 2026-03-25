#!/bin/bash
echo "=== Running collectstatic ==="
python manage.py collectstatic --noinput --verbosity=0

echo "=== Running migrations ==="
python manage.py migrate --noinput
