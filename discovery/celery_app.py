# celery_app.py
import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# include discovery.tasks so worker auto-loads them
celery = Celery("mvp_news", broker=REDIS_URL, backend=REDIS_URL, include=["discovery.tasks"])

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    beat_schedule={
        # Schedule the single-run discovery cycle (every 5 minutes)
        "run-discovery-every-5min": {
            "task": "discovery.tasks.run_discovery_cycle",
            "schedule": 500.0,
        },
    },
)
