web: gunicorn techvoto.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 120
worker: celery -A techvoto worker -l INFO --concurrency=2
