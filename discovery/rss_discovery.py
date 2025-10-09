# discovery/rss_discovery.py
import feedparser
from datetime import datetime

def discover_from_rss(feed_url: str, source_name: str):
    """
    Return list of discovered items: {url,title,published_at,source,discovered_at}
    """
    try:
        feed = feedparser.parse(feed_url)
        results = []
        for entry in feed.entries:
            url = entry.get("link")
            title = entry.get("title", "") or ""
            published = None
            if entry.get("published_parsed"):
                try:
                    published = datetime(*entry.published_parsed[:6])
                except Exception:
                    published = None
            results.append({
                "url": url,
                "title": title,
                "published_at": published,
                "source": source_name,
                "discovered_at": datetime.utcnow()
            })
        return results
    except Exception as e:
        print(f"[RSS Discovery] Failed {feed_url}: {e}")
        return []
