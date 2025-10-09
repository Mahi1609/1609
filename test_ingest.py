# api/test_ingest.py
from discovery.rss_discovery import discover_from_rss
from discovery.fetcher import fetch_url
from discovery.extractor import extract_article
from discovery.deduper import compute_content_hash, is_duplicate
from discovery.db import init_db, get_session
from discovery.models import Article
from discovery.hf_summarizer import summarize_text
from datetime import datetime

def run_once_for_feed(feed_url, source_name):
    print("Discovering:", feed_url)
    items = discover_from_rss(feed_url, source_name)
    print(f"Discovered {len(items)} items.")
    session = get_session()
    try:
        for item in items[:5]:  # limit for quick test
            url = item.get("url")
            print("Processing:", url)
            fetched = fetch_url(url)
            if not fetched.get("html"):
                print(" fetch failed")
                continue
            # Use the extractor function you have
            ext = extract_article(url, fetch_html_first=False)
            text = ext.get("text") or ""
            if not text or len(text) < 20:
                print(" no text")
                continue
            ch = compute_content_hash(text)
            if is_duplicate(session, url, ch):
                print(" duplicate")
                continue
            summary = summarize_text(text)
            art = Article(
                title = ext.get("title") or item.get("title") or "",
                canonical_url = url,
                source = source_name,
                published_at = ext.get("publish_date") or item.get("published_at"),
                cleaned_text = text,
                short_summary = summary,
                top_image_url = ext.get("top_image"),
                authors = ", ".join(ext.get("authors") or []),
                content_hash = ch,
                created_at = datetime.utcnow(),
                updated_at = datetime.utcnow()
            )
            session.add(art)
            session.commit()
            print(" saved id", art.id)
    finally:
        session.close()

if __name__ == "__main__":
    init_db()
    # quick test on India Today sports feed (or change to a feed you like)
    run_once_for_feed("https://www.indiatoday.in/rss/1206550", "India Today - Sports")
