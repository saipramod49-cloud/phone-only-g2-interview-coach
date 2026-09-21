"""ASGI entrypoint: GPT-Live WebSocket plus the existing WSGI Ring Ask API."""
from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware

import cloud_app
from ring_live import router_for

app = FastAPI()
app.include_router(router_for(cloud_app.credentials, cloud_app.ring_model))
app.mount("/", WSGIMiddleware(cloud_app.app))
