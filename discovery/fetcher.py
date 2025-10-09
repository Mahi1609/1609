# fetcher.py
import requests

def fetch_url(url: str):
    headers = {"User-Agent": "MVP-NewsBot/1.0 (+contact@example.com)"}
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        return {"url": url, "status": resp.status_code, "html": resp.text, "headers": dict(resp.headers)}
    except Exception as e:
        print(f"[Fetcher] Failed {url}: {e}")
        return {"url": url, "status": None, "html": None, "headers": {}}
