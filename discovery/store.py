# discovery/store.py
from typing import Optional, Dict, Any
from datetime import datetime
import logging
import re

from discovery.db import get_session, init_db
from discovery.models import Article  # SQLModel mapping for table 'articles'
from sqlmodel import select

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- heuristics / thresholds ---
MIN_WORDS_DEFAULT = 60  # allow short items but avoid pure index pages
INDEX_TITLE_RE = re.compile(
    r"(latest .+ news(?: today)?(?: & headlines)?|news today|headlines|live updates|"
    r"cities|state news|technology news|sports news|political news|"
    r"entertainment news|mobile news|gadgets news|book reviews|about us|contact)",
    re.IGNORECASE,
)

def _normalize_url(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    u = u.strip()
    if u.endswith("/") and len(u) > 1:
        u = u[:-1]
    return u

def _normalize_authors(a) -> Optional[str]:
    if not a:
        return None
    if isinstance(a, (list, tuple)):
        clean = [str(x).strip() for x in a if x is not None and str(x).strip()]
        return ", ".join(clean) if clean else None
    s = str(a).strip()
    return s if s else None

def _ensure_datetime(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        from dateutil import parser as _p
        return _p.parse(str(val))
    except Exception:
        return None

def save_article_to_sql(item: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upsert an Article from discovery item + extracted content.
    Skips obvious index/list pages.
    """
    try:
        try:
            init_db()
        except Exception:
            pass

        url = item.get("url") if isinstance(item, dict) else None
        canonical_url = (item.get("canonical_url") if isinstance(item, dict) else None) \
                        or extracted.get("canonical_url")
        canonical_url = _normalize_url(canonical_url) or _normalize_url(url)

        title = (item.get("title") if isinstance(item, dict) else "") or extracted.get("title") or ""
        published_at = (item.get("published_at") if isinstance(item, dict) else None) \
                        or extracted.get("published_at")
        published_at = _ensure_datetime(published_at)

        discovered_at = (item.get("discovered_at") if isinstance(item, dict) else None) or datetime.utcnow()
        discovered_at = _ensure_datetime(discovered_at) or datetime.utcnow()

        source = (item.get("source") if isinstance(item, dict) else None) or None

        cleaned_text = (extracted.get("cleaned_text") or extracted.get("text") or "") or ""
        short_summary = extracted.get("short_summary") or None
        top_image_url = extracted.get("top_image_url") or extracted.get("top_image") or None
        authors_val = _normalize_authors(item.get("authors") if isinstance(item, dict) and item.get("authors")
                                         else extracted.get("authors"))
        content_hash = extracted.get("content_hash") or extracted.get("content_hash_hex") or extracted.get("hash")

        word_count = extracted.get("word_count")
        if not isinstance(word_count, int):
            word_count = len((cleaned_text or "").split())

        is_index_like = bool(extracted.get("is_index_like"))

        # ---- Skip heuristics ----
        if is_index_like:
            return {"status": "skipped", "id": None, "msg": "index_like_page"}

        if word_count < MIN_WORDS_DEFAULT and INDEX_TITLE_RE.search(title or ""):
            return {"status": "skipped", "id": None, "msg": "too_short_and_index_title"}

        # ---- Upsert ----
        with get_session() as session:
            existing = None
            if canonical_url:
                stmt = select(Article).where(Article.canonical_url == canonical_url)
                existing = session.exec(stmt).first()
            if not existing and content_hash:
                stmt2 = select(Article).where(Article.content_hash == content_hash)
                existing = session.exec(stmt2).first()
            if not existing and url and not canonical_url:
                cand = _normalize_url(url)
                if cand:
                    stmt3 = select(Article).where(Article.canonical_url == cand)
                    existing = session.exec(stmt3).first()

            if existing:
                updated = False
                if title and existing.title != title:
                    existing.title = title; updated = True
                if cleaned_text and existing.cleaned_text != cleaned_text:
                    existing.cleaned_text = cleaned_text; updated = True
                if short_summary and existing.short_summary != short_summary:
                    existing.short_summary = short_summary; updated = True
                if top_image_url and existing.top_image_url != top_image_url:
                    existing.top_image_url = top_image_url; updated = True
                if authors_val and existing.authors != authors_val:
                    existing.authors = authors_val; updated = True
                if content_hash and existing.content_hash != content_hash:
                    existing.content_hash = content_hash; updated = True
                if canonical_url and existing.canonical_url != canonical_url:
                    existing.canonical_url = canonical_url; updated = True
                if source and existing.source != source:
                    existing.source = source; updated = True
                if published_at and existing.published_at != published_at:
                    existing.published_at = published_at; updated = True

                if updated:
                    session.add(existing)
                    session.commit()
                    session.refresh(existing)
                return {"status": "ok", "id": existing.id, "msg": "updated"}

            # create new
            article = Article(
                canonical_url=canonical_url or _normalize_url(url),
                title=title,
                cleaned_text=cleaned_text,
                short_summary=short_summary,
                top_image_url=top_image_url,
                content_hash=content_hash,
                source=source,
                authors=authors_val,
                discovered_at=discovered_at,
                published_at=published_at,
                word_count=word_count,
            )
            session.add(article)
            session.commit()
            session.refresh(article)
            return {"status": "ok", "id": article.id, "msg": "created"}

    except Exception as exc:
        logger.exception("save_article_to_sql failed: %s", exc)
        return {"status": "error", "id": None, "msg": str(exc)}
