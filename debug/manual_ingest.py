# debug/manual_ingest.py
from discovery.tasks import fetch_and_process_url

def main():
    url = input("Enter article URL: ").strip()
    item = {"url": url, "title": None, "published_at": None, "source": "manual", "discovered_at": None}
    print("Running ingestion for:", url)
    result = fetch_and_process_url(item)
    print("Result:", result)

if __name__ == "__main__":
    main()
