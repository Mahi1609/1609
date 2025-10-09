# discovery/sources.py
"""
Central place to configure discovery sources.

Each list is an iterable of tuples:
  (source_name, url_or_seed, discovery_fn)

discovery_fn should be a callable that matches one of:
  - fn(feed_url, source_name)
  - fn(feed_url)
  - fn()            (the scheduler will call appropriately)

This file tries to import recommended discovery functions from the
modules present in the repo; if any import fails the function is replaced
with a safe no-op that returns an empty list (so scheduler stays robust).
"""

from typing import List, Tuple, Callable, Iterable
import logging

logger = logging.getLogger("discovery.sources")
logger.setLevel(logging.INFO)

# Defensive imports - replace with no-op if missing
def _noop_discover(*_args, **_kwargs):
    return []

try:
    from discovery.rss_discovery import discover_from_rss
except Exception:
    logger.exception("Could not import discover_from_rss; RSS discovery disabled.", exc_info=False)
    discover_from_rss = _noop_discover

# sitemap discovery (should return iterable of urls or dicts)
try:
    from discovery.sitemap_discovery import discover_from_sitemap
except Exception:
    logger.exception("Could not import discover_from_sitemap; sitemap discovery disabled.", exc_info=False)
    discover_from_sitemap = _noop_discover

# list page processor (extracts article links from section/list pages)
try:
    from discovery.list_extractor import process_list_page
except Exception:
    logger.exception("Could not import process_list_page; list extraction disabled.", exc_info=False)
    process_list_page = _noop_discover

# a simple html crawler (optional)
try:
    from discovery.html_crawler import crawl_for_links
except Exception:
    crawl_for_links = _noop_discover

# -------------------------
# Configure sources below
# -------------------------

# A compact set of Indian news RSS feeds (good for getting started).
# Each entry: (source_name, feed_url, discovery_fn)
RSS_SOURCES: List[Tuple[str, str, Callable[..., Iterable]]] = [
    ("Hacker News", "https://news.ycombinator.com/rss", discover_from_rss),  # keep as example
    ("India Today - Home", "https://www.indiatoday.in/rss/home", discover_from_rss),
    ("India Today - Economy", "https://www.indiatoday.in/rss/1206513", discover_from_rss),
    ("India Today - Sports", "https://www.indiatoday.in/rss/1206550", discover_from_rss),
    ("The Hindu - Latest", "https://www.thehindu.com/news/feeder/default.rss", discover_from_rss),
    ("Times of India - Top Stories", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms", discover_from_rss),
    ("Indian Express - India", "https://indianexpress.com/section/india/feed/", discover_from_rss),
    ("NDTV - India", "https://feeds.feedburner.com/ndtvnews-india-news", discover_from_rss),
    ("Economic Times - Top Stories", "https://economictimes.indiatimes.com/feeds/aggregatedarticles.cms", discover_from_rss),
]

# Sitemap discovery: use sitemap XMLs where available (good for breadth/backfill).
# Each entry: (source_name, sitemap_url, discover_from_sitemap)
SITEMAP_SOURCES: List[Tuple[str, str, Callable[..., Iterable]]] = [
    ("The Hindu - Sitemap", "https://www.thehindu.com/sitemap.xml", discover_from_sitemap),
    ("Times of India - Sitemap", "https://timesofindia.indiatimes.com/sitemap.xml", discover_from_sitemap),
    ("Indian Express - Sitemap", "https://indianexpress.com/sitemap.xml", discover_from_sitemap),
    ("India Today - Sitemap", "https://www.indiatoday.in/sitemap.xml", discover_from_sitemap),
    ("NDTV - Sitemap", "https://www.ndtv.com/sitemaps/news-sitemap.xml", discover_from_sitemap),
    ("Economic Times - Sitemap", "https://economictimes.indiatimes.com/sitemap.xml", discover_from_sitemap),
]

# LIST_SOURCES: pages that contain lists/sections (process_list_page should extract article links)
# Each entry: (source_name, section_url, process_list_page)
LIST_SOURCES: List[Tuple[str, str, Callable[..., Iterable]]] = [
    ("The Hindu - National", "https://www.thehindu.com/news/national/", process_list_page),
    ("Times of India - India", "https://timesofindia.indiatimes.com/india", process_list_page),
    ("Indian Express - India", "https://indianexpress.com/section/india/", process_list_page),
    ("India Today - Home", "https://www.indiatoday.in/india", process_list_page),
    ("NDTV - News", "https://www.ndtv.com/india", process_list_page),
    ("Economic Times - Politics", "https://economictimes.indiatimes.com/news/politics-and-nation", process_list_page),
]

# SEED_SOURCES: arbitrary seed pages for crawlers (optional). supply a crawler fn that returns URLs.
# Use crawl_for_links if available; else keep seeds empty / rely on list_extractor above.
SEED_SOURCES: List[Tuple[str, str, Callable[..., Iterable]]] = [
    ("Times of India - Seed", "https://timesofindia.indiatimes.com/", crawl_for_links),
    ("The Hindu - Seed", "https://www.thehindu.com/", crawl_for_links),
    ("Indian Express - Seed", "https://indianexpress.com/", crawl_for_links),
]

# Export a consolidated list for quick debugging (not used by scheduler directly)
ALL_SOURCES = {
    "rss": RSS_SOURCES,
    "sitemap": SITEMAP_SOURCES,
    "list": LIST_SOURCES,
    "seed": SEED_SOURCES,
}

# If you'd like automatic logging on import show counts:
try:
    logger.info("Sources loaded: RSS=%d sitemap=%d list=%d seed=%d", 
                len(RSS_SOURCES), len(SITEMAP_SOURCES), len(LIST_SOURCES), len(SEED_SOURCES))
except Exception:
    pass
