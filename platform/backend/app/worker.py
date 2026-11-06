from celery import Celery

from .config import get_settings

settings = get_settings()
celery_app = Celery("knowledge-hub", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=60 * 30,
    task_soft_time_limit=60 * 25,
)
celery_app.autodiscover_tasks(["app"])

