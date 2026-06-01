from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "rag_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks.ingestion_task"],
)

celery_app.conf.update(
    # 序列化
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 重试策略
    task_acks_late=True,                    # 任务执行完成后才 ACK，防止丢失
    task_reject_on_worker_lost=True,        # Worker 崩溃时重新入队
    worker_prefetch_multiplier=1,           # 每次只预取一个任务，避免长任务饿死其他任务
    # 结果保留
    result_expires=86400,                   # 结果保留 24 小时
    # 队列路由
    task_routes={
        "app.workers.tasks.ingestion_task.process_document": {"queue": "ingestion"},
        "app.workers.tasks.cleanup_task.*": {"queue": "default"},
    },
    # Dead Letter Queue：超过重试上限的任务投递到 DLQ
    task_queues={},  # 由 kombu 定义，此处占位
    # Worker 并发数
    worker_concurrency=settings.celery_worker_concurrency,
    # 任务超时
    task_soft_time_limit=600,   # 10 分钟软超时（发送 SIGTERM）
    task_time_limit=660,        # 11 分钟硬超时（发送 SIGKILL）
)
