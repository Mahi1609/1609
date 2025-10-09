# discovery/deduper.py
"""
Simple, deterministic deduper used by the scheduler.
It accepts an iterable of items which may be:
 - strings (urls)
 - dict-like with 'url' or 'link' keys
It normalizes URLs by stripping whitespace and trailing slash (simple).
It preserves first-seen order.
This is intentionally conservative (no network calls) so it's safe to debug.
"""
from typing import Iterable, List, Optional
import logging

logger = logging.getLogger("discovery.deduper")
logger.setLevel(logging.WARNING)

def _normalize_url(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    u = u.strip()
    if u.endswith("/") and len(u) > 1:
        u = u[:-1]
    return u

def dedupe_urls(items: Iterable) -> List[str]:
    """
    Return a list of unique normalized URLs preserving first-seen order.
    """
    seen = set()
    out = []
    if not items:
        return []
    for it in items:
        url = None
        # dict-like
        try:
            if isinstance(it, dict):
                url = it.get("url") or it.get("link")
            else:
                url = str(it)
        except Exception:
            try:
                url = str(it)
            except Exception:
                continue
        url = _normalize_url(url)
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    logger.debug("dedupe_urls: input=%d output=%d", (len(list(items)) if hasattr(items, '__len__') else -1), len(out))
    return out
