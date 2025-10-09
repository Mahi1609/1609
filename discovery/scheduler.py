# discovery/scheduler.py
import inspect
import logging
from typing import Any, Callable, Iterable, List, Optional, Tuple

from discovery import deduper

# Try to use shared URL filtering/normalization
try:
    from discovery.url_filters import allowed_article_url, normalize_url
    _HAS_URL_FILTERS = True
except Exception:
    allowed_article_url = None  # type: ignore
    normalize_url = None        # type: ignore
    _HAS_URL_FILTERS = False

logger = logging.getLogger("discovery.scheduler")
logger.setLevel(logging.WARNING)


def _get_tasks():
    """
    Import Celery task wrappers lazily so module import at startup doesn't cause circular imports.
    Returns (fetch_task, process_list_task)
    """
    from discovery.tasks import fetch_and_process_url, process_list_page
    return fetch_and_process_url, process_list_page


def _filter_url(u: Optional[str]) -> Optional[str]:
    """
    Normalize + filter a URL. Returns normalized URL if accepted, else None.
    Falls back to a minimal heuristic if url_filters isn't available.
    """
    if not u or not isinstance(u, str):
        return None
    try:
        if _HAS_URL_FILTERS:
            nu = normalize_url(u)  # may strip utm/fragment, lower host, etc.
            if not nu:
                return None
            return nu if allowed_article_url(nu) else None
        # Fallback: very light heuristic — keep HTTP(S) and drop obvious non-articles
        if not u.startswith(("http://", "https://")):
            return None
        # very simple block-list
        bad = ("/about", "/contact", "/privacy", "/terms", "/subscribe", "/login",
               "/signin", "/register", "/advertis", "/epaper", "/sitemap", "/tag/",
               "/topic/", "/category/", "/section/", "/archive", "/videos", "/video",
               "/photos", "/photo", "/newsletter")
        if any(b in u.lower() for b in bad):
            return None
        return u
    except Exception:
        return None


def call_discovery_fn(fn: Callable[..., Any], feed_url: Optional[str], source_name: Optional[str]):
    """
    Call a discovery function `fn` in a robust way:
      - If fn accepts two parameters: return fn(feed_url, source_name)
      - If fn accepts one parameter: return fn(feed_url) (or fn(source_name) if feed_url is None)
      - If fn accepts no parameters: return fn()
    If underlying call raises, let the caller handle it (we do not swallow here).
    """
    try:
        sig = inspect.signature(fn)
        params = len(sig.parameters)
    except Exception:
        params = None

    # Try best-effort invocations
    try:
        if params == 2:
            return fn(feed_url, source_name)
        if params == 1:
            # prefer feed_url when present
            return fn(feed_url) if feed_url is not None else fn(source_name)
        if params == 0:
            return fn()
        # Unknown -> attempt typical variants
        try:
            return fn(feed_url, source_name)
        except TypeError:
            try:
                return fn(feed_url)
            except TypeError:
                return fn()
    except Exception:
        # bubble up to caller to decide how to log/handle
        raise


def _discover_rss_sources(rss_sources: Iterable[Tuple[str, str, Callable[..., Iterable[Any]]]]):
    """
    Discover items from RSS sources.
    rss_sources: iterable of tuples (source_name, feed_url, discovery_fn)
    Returns (final_urls_list, errors_list)
    """
    discovered: List[str] = []
    errors: List[Tuple[str, str]] = []

    for source_name, feed_url, fn in rss_sources:
        try:
            logger.warning(
                "[scheduler] Discovering RSS %s -> %s using %s",
                source_name,
                feed_url,
                getattr(fn, "__name__", repr(fn)),
            )
            items = call_discovery_fn(fn, feed_url, source_name)

            if items is None:
                logger.warning("[scheduler] RSS %s -> discovered None (treated as 0 items)", source_name)
                continue

            if isinstance(items, dict):
                items = [items]
            elif isinstance(items, str):
                items = [items]
            try:
                iter(items)
            except TypeError:
                items = [items]

            before = len(discovered)
            for it in items:
                # dict-like items may have 'url' or 'link'
                url = it.get("url") if isinstance(it, dict) else it
                if not url:
                    url = it.get("link") if isinstance(it, dict) else None
                nu = _filter_url(url)
                if nu:
                    discovered.append(nu)

            logger.warning("[scheduler] RSS %s -> discovered %d items (accepted %d)",
                           source_name, len(items), len(discovered) - before)

        except Exception as e:
            logger.exception("[scheduler] Error running discover_from_rss for %s - %s", source_name, e)
            errors.append((source_name, str(e)))

    # dedupe early
    try:
        deduped = deduper.dedupe_urls(discovered)
    except Exception:
        logger.exception("[scheduler] dedupe failed, falling back to unique-preserve-order")
        deduped = list(dict.fromkeys(discovered))
    return deduped, errors


def run_discovery_cycle():
    """Run a single discovery cycle: RSS -> sitemap -> seeds -> enqueue tasks."""
    logger.warning("[scheduler] running single discovery cycle")

    # load configured sources if available
    try:
        from discovery import sources as sources_module

        rss_sources = getattr(sources_module, "RSS_SOURCES", [])
        sitemap_sources = getattr(sources_module, "SITEMAP_SOURCES", [])
        seed_sources = getattr(sources_module, "SEED_SOURCES", [])
        list_sources = getattr(sources_module, "LIST_SOURCES", [])
    except Exception:
        rss_sources = []
        sitemap_sources = []
        seed_sources = []
        list_sources = []

    # fallback example if none configured (keep current behavior)
    if not rss_sources:
        try:
            from discovery.rss_discovery import discover_from_rss

            rss_sources = [
                ("Hacker News", "https://news.ycombinator.com/rss", discover_from_rss),
            ]
        except Exception:
            rss_sources = []

    all_discovered: List[str] = []
    errors_count = 0

    # RSS
    try:
        rss_list, rss_errors = _discover_rss_sources(rss_sources)
    except Exception as e:
        logger.exception("[scheduler] Unexpected exception during RSS discovery: %s", e)
        rss_list, rss_errors = [], [(None, str(e))]

    if rss_list is None:
        rss_list = []
    logger.warning("[scheduler] rss_list count=%d sample=%s", len(rss_list), (rss_list[:5] if rss_list else []))
    all_discovered.extend(rss_list)
    errors_count += len(rss_errors)

    # Generic discovery helper (sitemap, seed, list)
    def _generic_discover(sources_iter, kind_name):
        discovered: List[str] = []
        errs: List[Tuple[str, str]] = []
        for source_name, url_or_seed, fn in sources_iter:
            try:
                logger.warning("[scheduler] %s %s -> calling %s", kind_name, source_name, getattr(fn, "__name__", repr(fn)))
                items = call_discovery_fn(fn, url_or_seed, source_name)

                if items is None:
                    logger.warning("[scheduler] %s %s -> discovered None (0 items)", kind_name, source_name)
                    continue

                if isinstance(items, dict):
                    items = [items]
                elif isinstance(items, str):
                    items = [items]
                try:
                    iter(items)
                except TypeError:
                    items = [items]

                accepted = 0
                for it in items:
                    u = it.get("url") if isinstance(it, dict) else it
                    if not u and isinstance(it, dict):
                        u = it.get("link")
                    nu = _filter_url(u)
                    if nu:
                        discovered.append(nu)
                        accepted += 1

                logger.warning("[scheduler] %s %s -> discovered %d items (accepted %d)",
                               kind_name, source_name, len(items), accepted)
            except Exception as e:
                logger.exception("[scheduler] Error discovering %s - %s", source_name, e)
                errs.append((source_name, str(e)))
        return discovered, errs

    sitemap_list, sitemap_errs = _generic_discover(sitemap_sources, "Sitemap")
    seed_list, seed_errs = _generic_discover(seed_sources, "Seed")
    list_list, list_errs = _generic_discover(list_sources, "List")

    # Safely extend if lists have content
    for lst, name in ((sitemap_list, "Sitemap"), (seed_list, "Seed"), (list_list, "List")):
        if lst:
            logger.warning("[scheduler] extending discovered with %d items from %s", len(lst), name)
            all_discovered.extend(lst)

    errors_count += len(sitemap_errs) + len(seed_errs) + len(list_errs)

    logger.warning("[scheduler] total discovered before final dedupe: %d", len(all_discovered))

    # final dedupe
    try:
        final_urls = deduper.dedupe_urls(all_discovered)
    except Exception:
        logger.exception("[scheduler] final dedupe failed")
        final_urls = list(dict.fromkeys(all_discovered))

    if final_urls is None:
        final_urls = []

    logger.warning("[scheduler] final_urls count=%d sample=%s", len(final_urls), (final_urls[:5] if final_urls else []))

    # enqueue to celery
    fetch_task, process_list_task = _get_tasks()
    enqueued = 0
    for url in final_urls:
        try:
            fetch_task.delay(str(url))
            enqueued += 1
        except Exception as e:
            logger.exception("[scheduler] Failed to enqueue %s : %s", url, e)

    summary = {"discovered": len(final_urls), "enqueued": enqueued, "errors": errors_count}
    logger.warning("[scheduler] Discovery finished: %s", summary)
    return summary
