# debug/check_db.py
from discovery.db import get_session, init_db
from discovery.models import Article
from sqlmodel import select

def main():
    init_db()
    with get_session() as s:
        rows = s.exec(select(Article)).all()
        print("Found", len(rows), "articles")
        for r in rows[-5:]:
            print(f"id={r.id} | title={(r.title or '')[:80]}")

if __name__ == "__main__":
    main()
