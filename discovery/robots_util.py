# discovery/robots_util.py
import requests
from urllib.parse import urljoin, urlparse

CACHE = {}

def fetch_robots(base_url):
    parsed = urlparse(base_url)
    robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
    if robots_url in CACHE:
        return CACHE[robots_url]
    try:
        r = requests.get(robots_url, timeout=5, headers={"User-Agent": "MVP-NewsBot/1.0"})
        if r.status_code == 200:
            CACHE[robots_url] = r.text
            return r.text
    except Exception:
        pass
    CACHE[robots_url] = ""
    return ""

def is_allowed(base_url, path):
    robots = fetch_robots(base_url)
    # Very naive: if Disallow has an entry that matches path prefix, block
    # This is simple and not a full robots parser. For production use, use robotparser.
    for line in robots.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("disallow:"):
            rule = line.split(":", 1)[1].strip()
            if rule == "":
                continue
            if path.startswith(rule):
                return False
    return True
