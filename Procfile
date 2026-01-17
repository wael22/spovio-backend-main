web: (python init_db.py || true) && gunicorn --bind 0.0.0.0:$PORT --workers 4 --timeout 120 --access-logfile - --error-logfile - main:app
