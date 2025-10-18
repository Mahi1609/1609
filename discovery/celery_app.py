# celery_app.py
import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

#------------ Determine if running inside Docker ------------
# Detect if running inside Docker (heuristic: check for /.dockerenv file)
def is_docker_env() -> bool:
    return os.path.exists("/.dockerenv")

# Default values
default_broker = "redis://localhost:6379/0"
default_backend = "redis://localhost:6379/0"

# Use Docker-friendly URLs when inside Docker
if is_docker_env():
    default_broker = "redis://redis:6379/0"
    default_backend = "redis://redis:6379/0"

# Allow overrides via environment variables
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", default_broker)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", default_backend)
#------------------------------------------------------------




# include discovery.tasks so worker auto-loads them


#------------ celery = Celery("mvp_news", broker=REDIS_URL, backend=REDIS_URL, include=["discovery.tasks"]) -- original line------------

celery = Celery(
    "discovery",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["discovery.tasks"],
)

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
