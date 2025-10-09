# discovery/list_extractor.py
"""
Fetch a list page and extract candidate article URLs.

`process_list_page(url)` returns a list of absolute, normalized URLs found on
the page, filtered through discovery.url_filters.allowed_article_url.
"""

from typing import List
from urllib.parse import urljoin, urlparse
import logging

logger = logging.getLogger("discovery.list_extractor")
logger.setLevel(logging.INFO)

# Local imports guarded to avoid top-level failures
try:
    import requests
    from lxml import html as lxml_html
except Exception as e:
    requests = None
    lxml_html = None
    logger.exception("requests or lxml not available for list_extractor")

# Bring in URL filtering + normalization
try:
    from discovery.url_filters import allowed_article_url, normalize_url
except Exception:
    # Fallback no-ops if the module isn't importable (won't crash scheduler)
    def allowed_article_url(u: str) -> bool:  # type: ignore
        return True
    def normalize_url(u: str) -> str:         # type: ignore
        return u


def _same_scheme_host(base: str, candidate: str) -> bool:
    try:
        pb = urlparse(base)
        pc = urlparse(candidate)
        return (pb.scheme.lower() == pc.scheme.lower()) and (pb.netloc.lower() == pc.netloc.lower())
    except Exception:
        return False


def _safe_int(val, default: int) -> int:
    try:
        return int(val)
    except Exception:
        return default


def process_list_page(url: str, max_links: int = 200) -> List[str]:
    """
    Fetch `url` and return a list of absolute links discovered on the page.

    - Limits to `max_links` results (string or int accepted).
    - Converts relative links to absolute via urljoin.
    - Prefers same-origin links, but will include cross-origin if allowed by filters.
    - Applies discovery.url_filters.allowed_article_url and normalize_url on each link.
    """
    max_links = _safe_int(max_links, 200)

    logger.info("process_list_page: %s (cap=%d)", url, max_links)
    if requests is None or lxml_html is None:
        logger.error("requests or lxml not available; cannot process list page")
        return []

    # Fetch
    try:
        resp = requests.get(url, timeout=12, headers={"User-Agent": "nu-scop-listbot/1.0"})
        resp.raise_for_status()
    except Exception as e:
        logger.exception("Failed to fetch list page %s: %s", url, e)
        return []

    try:
        doc = lxml_html.fromstring(resp.content)
        anchors = doc.xpath("//a[@href]")

        base = resp.url  # requests follows redirects; use final URL as base
        same_origin: List[str] = []
        other: List[str] = []
        seen_raw = set()

        # Collect raw absolute links first
        for a in anchors:
            try:
                href = a.get("href")
                if not href:
                    continue
                href = href.strip()
                if not href:
                    continue

                abs_url = urljoin(base, href)

                # Skip javascript/mailto and strip fragments
                if abs_url.startswith(("javascript:", "mailto:")):
                    continue
                abs_url = abs_url.split("#", 1)[0]
                if not abs_url:
                    continue

                if abs_url in seen_raw:
                    continue
                seen_raw.add(abs_url)

                if _same_scheme_host(base, abs_url):
                    same_origin.append(abs_url)
                else:
                    other.append(abs_url)
            except Exception:
                continue

        raw_found = same_origin + other
        raw_count = len(raw_found)

        # Normalize + filter with allowed_article_url
        filtered: List[str] = []
        seen_norm = set()
        for link in raw_found:
            try:
                norm = normalize_url(link)
                if not norm:
                    continue
                if norm in seen_norm:
                    continue
                if allowed_article_url(norm):
                    seen_norm.add(norm)
                    filtered.append(norm)
            except Exception:
                # Be safe: if filtering raises, skip that URL
                continue

            if len(filtered) >= max_links:
                break

        logger.info(
            "process_list_page %s -> raw=%d, filtered=%d (cap=%d)",
            url, raw_count, len(filtered), max_links
        )
        return filtered

    except Exception as e:
        logger.exception("Error parsing list page %s: %s", url, e)
        return []
