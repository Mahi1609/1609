# debug/check_articles.py
from discovery.db import get_session, init_db
from discovery.models import Article
from sqlmodel import select

def main():
    init_db()
    s = get_session()
    rows = s.exec(select(Article).order_by(Article.created_at.desc()).limit(30)).all()
    print("Found", len(rows), "recent articles:")
    for a in rows:
        text_len = len(a.cleaned_text or "")
        summary_len = len(a.short_summary or "")
        print(f"id={a.id} | title={(a.title or '')[:80]!r} | url={a.canonical_url} | "
              f"published_at={a.published_at} | text_len={text_len} | summary_len={summary_len}")
    s.close()

if __name__ == "__main__":
    main()
