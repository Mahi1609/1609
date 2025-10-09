# discovery/html_crawler.py
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from datetime import datetime
import time

HEADERS = {"User-Agent": "MVP-NewsBot/1.0 (+contact@example.com)"}

def _same_domain(seed, url):
    try:
        return urlparse(seed).netloc == urlparse(url).netloc
    except Exception:
        return False

def _normalize_link(base, link):
    try:
        return urljoin(base, link.split('#')[0])
    except Exception:
        return None

def crawl_seed(seed_url, max_pages=100, max_depth=2, delay=0.5):
    """
    Simple BFS crawler:
    - start from seed_url (home or section page)
    - follow internal links (same domain) up to max_depth
    - returns list of discovered page URLs (unique) with discovered_at
    - will not follow external domains
    - delay between requests = politeness
    """
    discovered = []
    visited = set()
    queue = [(seed_url, 0)]
    visited.add(seed_url)

    while queue and len(discovered) < max_pages:
        url, depth = queue.pop(0)
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            r.raise_for_status()
            html = r.text
        except Exception as e:
            # skip on fetch errors
            # print("[crawler] fetch failed:", url, e)
            time.sleep(delay)
            continue

        # parse links
        soup = BeautifulSoup(html, "html.parser")

        # Heuristic: many sites include <link rel="canonical" href="..."> for canonical URL
        can = soup.find("link", rel="canonical")
        canonical = can.get("href").strip() if can and can.get("href") else url

        # Heuristic: treat pages that include article-like structures as article candidates
        # We'll include all links for now; fetcher + extractor will drop non-articles.
        discovered.append({"url": canonical, "title": None, "published_at": None, "source": seed_url, "discovered_at": datetime.utcnow()})

        if depth < max_depth:
            for a in soup.find_all("a", href=True):
                link = _normalize_link(url, a["href"])
                if not link:
                    continue
                # same domain only
                if not _same_domain(seed_url, link):
                    continue
                if link in visited:
                    continue
                # skip mailto, javascript
                if link.startswith("mailto:") or link.startswith("javascript:"):
                    continue
                visited.add(link)
                queue.append((link, depth + 1))

        time.sleep(delay)

    # dedupe by url, preserve order
    seen = set()
    out = []
    for it in discovered:
        if it["url"] not in seen:
            out.append(it)
            seen.add(it["url"])
    return out
