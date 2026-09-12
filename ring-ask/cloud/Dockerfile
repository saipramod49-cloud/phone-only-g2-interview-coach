FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir gunicorn==23.0.0
COPY bridge.py cloud_app.py ring_api.py ./
COPY ring-ui ./ring-ui
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 4 --timeout 120 --keep-alive 5 --access-logfile /dev/null cloud_app:app"]
