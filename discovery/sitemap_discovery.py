# discovery/sitemap_discovery.py
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlparse

HEADERS = {"User-Agent": "MVP-NewsBot/1.0 (+contact@example.com)"}

# Try to use the shared URL filter/normalizer; fall back to local heuristics if missing.
try:
    from discovery.url_filters import allowed_article_url, normalize_url
    _HAS_URL_FILTERS = True
except Exception:
    allowed_article_url = None  # type: ignore
    normalize_url = None        # type: ignore
    _HAS_URL_FILTERS = False

# ---------- Local heuristics (fallback only) ----------
_GLOBAL_DENY = (
    "about", "contact", "privacy", "terms", "subscribe", "subscription",
    "login", "signin", "register", "advertise", "advertorial", "promo",
    "profile", "sitemap", "tag", "topic", "category", "section",
    "page-", "archive", "epaper", "e-paper", "newsletter",
    "weather", "photos", "photo", "videos", "video", "live-updates", "liveblog",
    "authors", "author", "careers"
)
_DATE_PATH = re.compile(r"/20\d{2}/\d{1,2}/\d{1,2}/")
_BIG_ID    = re.compile(r"/\d{6,}/")
_DOMAIN_ALLOW = {
    "thehindu.com": [re.compile(r"/news/.*article\d+\.ece"), re.compile(r"/news/.+"), _DATE_PATH, _BIG_ID],
    "indiatimes.com": [re.compile(r"/articleshow/\d+\.cms"), _BIG_ID],
    "timesofindia.indiatimes.com": [re.compile(r"/articleshow/\d+\.cms"), _BIG_ID],
    "indianexpress.com": [re.compile(r"/article/"), _DATE_PATH, _BIG_ID],
    "indiatoday.in": [re.compile(r"/story/"), _DATE_PATH, _BIG_ID],
    "ndtv.com": [re.compile(r"/news/"), _BIG_ID],
}

def _fallback_probable_article(url: str) -> bool:
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        path = p.path.lower()

        if any(f"/{k}/" in path or path.endswith(f"/{k}") for k in _GLOBAL_DENY):
            return False
        for domain, rules in _DOMAIN_ALLOW.items():
            if host.endswith(domain):
                return any(rgx.search(path) for rgx in rules)
        return bool(_DATE_PATH.search(path) or _BIG_ID.search(path))
    except Exception:
        return False

def _is_article_url(url: str) -> str | None:
    """
    Returns normalized URL string if it looks like an article, else None.
    Uses shared url_filters when available; otherwise uses fallback heuristics.
    """
    if not url or not url.startswith("http"):
        return None
    if _HAS_URL_FILTERS:
        try:
            norm = normalize_url(url)  # type: ignore
            if norm and allowed_article_url(norm):  # type: ignore
                return norm
            return None
        except Exception:
            # if shared filters blow up, fall back gracefully
            pass
    # Fallback heuristics
    return url if _fallback_probable_article(url) else None

# ---------- helpers ----------
def _safe_int(val, default):
    try:
        return int(val)
    except Exception:
        return default

def _fetch_xml(url, timeout=8):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[sitemap] fetch failed {url}: {e}")
        return None

def parse_sitemap(xml_text):
    """
    Return list of (loc, lastmod or None) from a urlset.
    """
    urls = []
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print("[sitemap] parse error:", e)
        return urls

    # With namespace
    for elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
        loc = elem.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        lastmod = elem.find("{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod")
        if loc is not None and loc.text:
            urls.append((loc.text.strip(), (lastmod.text.strip() if lastmod is not None and lastmod.text else None)))

    # Fallback without namespace
    if not urls:
        for elem in root.findall(".//url"):
            loc = elem.find("loc")
            lastmod = elem.find("lastmod")
            if loc is not None and loc.text:
                urls.append((loc.text.strip(), (lastmod.text.strip() if lastmod is not None and lastmod.text else None)))
    return urls

def parse_sitemap_index(xml_text):
    """
    If sitemap is an index, return list of sitemap urls.
    """
    sitemaps = []
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print("[sitemap-index] parse error:", e)
        return sitemaps

    # With namespace
    for elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap"):
        loc = elem.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        if loc is not None and loc.text:
            sitemaps.append(loc.text.strip())

    # Fallback without namespace
    if not sitemaps:
        for elem in root.findall(".//sitemap"):
            loc = elem.find("loc")
            if loc is not None and loc.text:
                sitemaps.append(loc.text.strip())
    return sitemaps

def discover_from_sitemap(sitemap_url, max_urls=200):
    """
    Discover *article* URLs from a sitemap or sitemap index.
    Returns list of dicts:
      {url, title=None, published_at, source=sitemap_url, discovered_at}
    """
    max_urls = _safe_int(max_urls, 200)

    text = _fetch_xml(sitemap_url)
    if not text:
        return []

    sitemaps = parse_sitemap_index(text)
    pairs = []  # (loc, lastmod)
    seen = set()  # dedupe normalized URLs

    def _extend_from(xml_txt):
        nonlocal pairs, seen
        found = parse_sitemap(xml_txt)
        for (loc, lm) in found:
            norm = _is_article_url(loc)
            if not norm:
                continue
            if norm in seen:
                continue
            seen.add(norm)
            pairs.append((norm, lm))

    if sitemaps:
        for sm in sitemaps:
            if len(pairs) >= max_urls:
                break
            txt = _fetch_xml(sm)
            if txt:
                _extend_from(txt)
                if len(pairs) >= max_urls:
                    break
    else:
        _extend_from(text)

    if len(pairs) > max_urls:
        pairs = pairs[:max_urls]

    results = []
    for loc, lastmod in pairs:
        try:
            published = None
            if lastmod:
                from dateutil import parser as dateparser
                published = dateparser.parse(lastmod)
            results.append({
                "url": loc,
                "title": None,
                "published_at": published,
                "source": sitemap_url,
                "discovered_at": datetime.utcnow()
            })
        except Exception:
            results.append({
                "url": loc,
                "title": None,
                "published_at": None,
                "source": sitemap_url,
                "discovered_at": datetime.utcnow()
            })
    return results
