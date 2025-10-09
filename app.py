# api/app.py
import os
import logging
import socket
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from discovery.db import init_db, get_session, get_engine
from discovery.models import Article
from sqlmodel import select

from typing import Optional
from sqlalchemy import func, inspect
from celery.exceptions import TimeoutError as CeleryTimeout
from discovery.db import get_engine
from discovery.celery_app import celery


# Celery debug runner (safe import)
try:
    from discovery.celery_app import celery
except Exception:
    celery = None

# Import scheduler function lazily in endpoints to avoid circular imports at module import time
from discovery.scheduler import run_discovery_cycle

logger = logging.getLogger("api.app")
logger.setLevel(logging.INFO)

app = FastAPI(title="MVP News Aggregator with Celery")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("DB initialized. Celery should be running for background tasks.")


def _session_ctx():
    """
    Helper that returns whatever get_session() returns (either a context manager or a session).
    Use like:
        sess_ctx = _session_ctx()
        if hasattr(sess_ctx, '__enter__'):
            with sess_ctx as session: ...
        else:
            session = sess_ctx; ...; session.close()
    """
    return get_session()


@app.get("/articles")
def list_articles(limit: int = 20, offset: int = 0, query: Optional[str] = None):
    """
    List articles. Order by COALESCE(published_at, created_at) desc, then id desc
    (so newest always on top even when published_at is NULL).
    """
    # prefer DB-side ordering; fall back to Python sort if needed
    order_expr = func.coalesce(Article.published_at, Article.created_at)

    def build_stmt(qval: Optional[str]):
        if qval:
            likeq = f"%{qval}%"
            return select(Article).where(
                (Article.title.ilike(likeq)) | (Article.cleaned_text.ilike(likeq))
            )
        return select(Article)

    sess_ctx = _session_ctx()  # your helper that returns get_session()

    try:
        if hasattr(sess_ctx, "__enter__") and hasattr(sess_ctx, "__exit__"):
            with sess_ctx as session:
                stmt = (
                    build_stmt(query)
                    .order_by(order_expr.desc(), Article.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
                try:
                    return session.exec(stmt).all()
                except Exception:
                    # fallback: fetch, then sort in Python
                    rows = session.exec(build_stmt(query).offset(offset).limit(limit)).all()
                    rows.sort(
                        key=lambda a: ((a.published_at or a.created_at), a.id or 0),
                        reverse=True,
                    )
                    return rows
        else:
            session = sess_ctx
            try:
                stmt = (
                    build_stmt(query)
                    .order_by(order_expr.desc(), Article.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
                try:
                    return session.exec(stmt).all()
                except Exception:
                    rows = session.exec(build_stmt(query).offset(offset).limit(limit)).all()
                    rows.sort(
                        key=lambda a: ((a.published_at or a.created_at), a.id or 0),
                        reverse=True,
                    )
                    return rows
            finally:
                try:
                    session.close()
                except Exception:
                    logger.exception("session.close() failed")
    except Exception as exc:
        logger.exception("list_articles failed")
        raise HTTPException(status_code=500, detail=str(exc))



@app.get("/articles/{article_id}")
def get_article(article_id: int):
    sess_ctx = _session_ctx()
    try:
        if hasattr(sess_ctx, "__enter__") and hasattr(sess_ctx, "__exit__"):
            with sess_ctx as session:
                article = session.get(Article, article_id)
                if not article:
                    raise HTTPException(status_code=404, detail="Article not found")
                return article
        else:
            session = sess_ctx
            try:
                article = session.get(Article, article_id)
                if not article:
                    raise HTTPException(status_code=404, detail="Article not found")
                return article
            finally:
                try:
                    session.close()
                except Exception:
                    logger.exception("session.close() failed")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_article failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/admin/fetch")
def admin_fetch():
    """
    Trigger discovery immediately (enqueue feed items into Celery).
    Returns a simple ack; the discovery routine logs more detail.
    """
    try:
        run_discovery_cycle()
        return {"status": "discovery_enqueued"}
    except Exception as exc:
        logger.exception("admin_fetch failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/admin/run_discovery")
def manual_discovery():
    try:
        run_discovery_cycle()
        return {"status": "discovery_started"}
    except Exception as exc:
        logger.exception("manual_discovery failed")
        raise HTTPException(status_code=500, detail=str(exc))


# ----------------
# Debug / health
# ----------------
@app.get("/debug/dbpath")
def debug_dbpath():
    try:
        engine = get_engine()
        db_url = str(engine.url) if engine is not None else None
    except Exception:
        db_url = None
    return {"api_pid": os.getpid(), "db_url": db_url}


@app.get("/debug/count")
def debug_count():
    """
    Returns DB path and article count (safe attempts).
    """
    info = {"db_url": None, "article_count": None}
    try:
        engine = get_engine()
        info["db_url"] = str(engine.url)
    except Exception:
        info["db_url"] = None

    try:
        sess_ctx = _session_ctx()
        if hasattr(sess_ctx, "__enter__"):
            with sess_ctx as session:
                stmt = select(Article)
                try:
                    rows = session.exec(stmt).all()
                    info["article_count"] = len(rows)
                except Exception:
                    # fallback to raw count via SQL execution if present
                    try:
                        cnt = session.execute("SELECT COUNT(*) FROM articles").scalar_one()
                        info["article_count"] = int(cnt)
                    except Exception:
                        info["article_count"] = "count_failed"
        else:
            session = sess_ctx
            try:
                stmt = select(Article)
                try:
                    rows = session.exec(stmt).all()
                    info["article_count"] = len(rows)
                except Exception:
                    try:
                        cnt = session.execute("SELECT COUNT(*) FROM articles").scalar_one()
                        info["article_count"] = int(cnt)
                    except Exception:
                        info["article_count"] = "count_failed"
            finally:
                try:
                    session.close()
                except Exception:
                    pass
    except Exception:
        logger.exception("debug_count failed")
        info["article_count"] = "error"

    return info


@app.get("/health")
def health():
    """
    Health/debug:
      - DB reachable + path + article_count
      - Celery reachable via debug_info task (with safe timeout)
      - Redis ping (reported by worker if available)
    """
    out = {
        "db": False,
        "db_url": None,
        "article_count": None,
        "db_error": None,
        "celery": None,
        "redis_ping": None,
    }

    # --- DB check ---
    try:
        engine = get_engine()
        out["db_url"] = str(engine.url)

        # touch the schema
        _ = inspect(engine).get_table_names()
        out["db"] = True

        # article count (fast COUNT(*))
        sess_ctx = _session_ctx()
        if hasattr(sess_ctx, "__enter__") and hasattr(sess_ctx, "__exit__"):
            with sess_ctx as s:
                out["article_count"] = s.exec(select(func.count(Article.id))).one()
        else:
            s = sess_ctx
            try:
                out["article_count"] = s.exec(select(func.count(Article.id))).one()
            finally:
                try:
                    s.close()
                except Exception:
                    pass
    except Exception as e:
        logger.exception("health: DB check failed")
        out["db"] = False
        out["db_error"] = str(e)

    # --- Celery check ---
    try:
        res = celery.send_task("discovery.tasks.debug_info")
        info = res.get(timeout=6)  # more generous timeout
        # echo back worker's structured info if present
        if isinstance(info, dict) and info.get("status") == "ok":
            out["celery"] = "ok"
            details = info.get("info") or {}
            out["redis_ping"] = details.get("redis_ping")
        else:
            out["celery"] = {"status": info}
    except CeleryTimeout:
        out["celery"] = {"error": "timeout"}
    except Exception as e:
        out["celery"] = {"error": str(e)}

    return out
