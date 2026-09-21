FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bridge.py cloud_app.py ring_api.py ring_agent.py ring_live.py asgi_app.py ./
COPY ring-ui ./ring-ui
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "exec uvicorn asgi_app:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers"]
