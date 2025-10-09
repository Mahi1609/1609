# discovery/tasks.py
import logging
import os
import socket
from datetime import datetime
from typing import Any, Dict, Optional

from discovery.celery_app import celery

logger = logging.getLogger("discovery.tasks")
logger.setLevel(logging.INFO)

# --- Imports ---
try:
    from discovery.extractor import fetch_and_process
except Exception:
    fetch_and_process = None
    logger.exception("Could not import discovery.extractor.fetch_and_process")

try:
    from discovery.list_extractor import process_list_page as process_list_page_fn
except Exception:
    process_list_page_fn = None
    logger.exception("Could not import discovery.list_extractor.process_list_page")

try:
    from discovery.scheduler import run_discovery_cycle as run_discovery_cycle_fn
except Exception:
    run_discovery_cycle_fn = None
    logger.exception("Could not import discovery.scheduler.run_discovery_cycle")

# URL filter
try:
    from discovery.url_filters import allowed_article_url
except Exception:
    allowed_article_url = None
    logger.warning("url_filters.allowed_article_url not available")

# Use your UPsert layer instead of inserting directly
try:
    from discovery.store import save_article_to_sql
except Exception:
    save_article_to_sql = None
    logger.exception("Could not import discovery.store.save_article_to_sql")

# For /debug_info
try:
    from discovery.db import get_session, init_db, get_engine
    from discovery.models import Article
    from sqlmodel import select
except Exception:
    get_session = init_db = get_engine = None
    Article = None
    select = None

try:
    import redis
except Exception:
    redis = None


def _safe_get_db_info() -> Dict[str, Optional[Any]]:
    info = {"db_url": None, "article_count": None}
    try:
        if get_engine:
            info["db_url"] = str(get_engine().url)
    except Exception:
        info["db_url"] = None
    try:
        if init_db:
            init_db()
    except Exception:
        logger.exception("init_db() failed")
    try:
        if get_session and Article is not None and select is not None:
            sess_ctx = get_session()
            if hasattr(sess_ctx, "__enter__"):
                with sess_ctx as sess:
                    # portable count
                    rows = sess.exec(select(Article)).all()
                    info["article_count"] = len(rows)
            else:
                sess = sess_ctx
                try:
                    rows = sess.exec(select(Article)).all()
                    info["article_count"] = len(rows)
                finally:
                    if hasattr(sess, "close"):
                        sess.close()
        else:
            info["article_count"] = "n/a"
    except Exception:
        logger.exception("error while gathering DB info")
        info["article_count"] = "error"
    return info


@celery.task(name="discovery.tasks.fetch_and_process_url")
def fetch_and_process_url(item_or_url: Any) -> Dict[str, Any]:
    """
    Celery task: fetch URL → extract → save via upsert.
    Applies url_filters and skips obvious list/index pages.
    """
    logger.info("[task] fetch_and_process_url %s", repr(item_or_url))

    # Normalize
    try:
        if isinstance(item_or_url, str):
            item = {"url": item_or_url}
        elif isinstance(item_or_url, dict):
            item = item_or_url
        elif hasattr(item_or_url, "url"):
            item = {"url": getattr(item_or_url, "url")}
        else:
            item = {"url": str(item_or_url)}
    except Exception:
        logger.exception("normalize failure")
        return {"status": "error", "error": "normalize_failure", "input": repr(item_or_url)}

    url = item.get("url")
    if not url:
        return {"status": "error", "error": "missing_url", "input": item_or_url}

    # 1) Filter out junk early
    if allowed_article_url and not allowed_article_url(url):
        logger.info("URL filtered out by url_filters: %s", url)
        return {"status": "skipped", "reason": "url_filtered", "url": url}

    if fetch_and_process is None:
        msg = "extractor.fetch_and_process not available"
        logger.error(msg)
        return {"status": "error", "error": msg, "url": url}

    # 2) Extract
    try:
        result = fetch_and_process(item)
        result.setdefault("url", url)
        result.setdefault("fetched_at", datetime.utcnow().isoformat())
    except Exception as e:
        logger.exception("Error in fetch_and_process for %s", url)
        return {"status": "error", "error": str(e), "url": url}

    # If extractor marks this as index-like/list page -> skip DB write
    if result.get("index_like") is True:
        logger.info("index-like page detected; skipping save: %s", url)
        result["_saved_id"] = None
        result["status"] = result.get("status") or "skipped"
        result["reason"] = "index_like_page"
        return result

    # 3) UPSERT via store.save_article_to_sql
    if save_article_to_sql is None:
        logger.error("save_article_to_sql not available; not saving")
        result["_saved_id"] = None
        return result

    # Map into (item, extracted) expected by store.py
    store_item = {
        "url": url,
        "title": result.get("title"),
        "published_at": result.get("published_at"),
        "source": item.get("source"),
        "discovered_at": datetime.utcnow(),
        "canonical_url": result.get("canonical_url") or url,
    }
    store_extracted = {
        "text": result.get("text"),
        "cleaned_text": result.get("cleaned_text"),
        "short_summary": result.get("short_summary"),
        "top_image_url": result.get("top_image_url") or result.get("top_image"),
        "content_hash": result.get("content_hash"),
        "authors": result.get("authors"),
    }

    try:
        save_out = save_article_to_sql(store_item, store_extracted)
    except Exception as e:
        logger.exception("save_article_to_sql crashed for %s", url)
        save_out = {"status": "error", "msg": str(e), "id": None}

    result["_saved_id"] = save_out.get("id")
    result["_save_status"] = save_out.get("status")
    result["_save_msg"] = save_out.get("msg")
    return result


@celery.task(name="discovery.tasks.process_list_page")
def process_list_page(url: str) -> Dict[str, Any]:
    if process_list_page_fn is None:
        return {"status": "error", "error": "list_extractor not available", "url": url}
    try:
        out = process_list_page_fn(url)
        return {"status": "ok", "result": out, "url": url}
    except Exception:
        logger.exception("Error in process_list_page for %s", url)
        return {"status": "error", "error": "exception during processing", "url": url}


@celery.task(name="discovery.tasks.run_discovery_cycle")
def run_discovery_cycle() -> Dict[str, Any]:
    if run_discovery_cycle_fn is None:
        return {"status": "error", "error": "scheduler not available"}
    try:
        summary = run_discovery_cycle_fn()
        summary.setdefault("ran_at", datetime.utcnow().isoformat())
        return {"status": "ok", **summary}
    except Exception:
        logger.exception("run_discovery_cycle failed")
        return {"status": "error", "error": "exception during discovery"}


@celery.task(name="discovery.tasks.debug_info")
def debug_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        info["hostname"] = socket.gethostname()
        info["pid"] = os.getpid()
        info["time"] = datetime.utcnow().isoformat()
        conf = celery.conf
        info["celery_broker"] = getattr(conf, "broker_url", None)
        info["celery_backend"] = getattr(conf, "result_backend", None)
        info["registered_tasks"] = sorted(list(celery.tasks.keys()))
        info["redis_ping"] = None
        if redis and info["celery_broker"] and "redis" in str(info["celery_broker"]):
            try:
                r = redis.Redis.from_url(str(info["celery_broker"]))
                info["redis_ping"] = bool(r.ping())
            except Exception as e:
                info["redis_ping"] = f"error: {e}"
        info.update(_safe_get_db_info())
        return {"status": "ok", "info": info}
    except Exception:
        logger.exception("debug_info failed")
        return {"status": "error", "error": "debug_info_exception"}
