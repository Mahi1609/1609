# discovery/url_filters.py
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# ---------------------------
# Global hard-deny patterns
# ---------------------------
GLOBAL_DENY_PATTERNS = [
    r"/about([/\-]|$)",
    r"/contact([/\-]|$)",
    r"/privacy",
    r"/terms",
    r"/cookies?",
    r"/advertis",                   # advertise/advertising
    r"/brand(?!-new)",              # brandstudio/brand solutions etc.
    r"/subscribe|/subscription",
    r"/newsletter",
    r"/sitemap",
    r"/epaper",
    r"/apps?",
    r"/careers?",
    r"/jobs?",
    r"/login|/signin|/sign-in|/sign_in|/signup|/register",
    r"/rss([/\-]|$)",
    r"/feedback|/help|/faq",
    r"/copyright|/press|/partners?",
    r"/events?",
    r"/investor|/company|/corporate",
    r"/account|/profile",
    r"/static/",
    r"/tag/[^/]+/?$",
    r"/topic/[^/]+/?$",
    r"/page/\d+/?$",
    r"/page-\d+/?$",
    # Social domains (full URL match)
    r"^https?://(www\.)?(facebook|twitter|x|instagram|linkedin|youtube)\.com",
]

# ---------------------------
# Domain-scoped allow rules
# ---------------------------
DOMAIN_ALLOW = {
    # India Today
    "indiatoday.in": [
        r"/(news|india|world|business|technology|science|sports|cities|opinion)/",
        r"/story/",
        r"/education/",
        r"/[^/]+/\d{4}/\d{2}/\d{2}/",  # dated path variants
    ],
    # The Hindu
    "thehindu.com": [
        r"/news/",
        r"/sport/",
        r"/business/",
        r"/sci-tech/",
        r"/opinion/",
        r"/education/",
        r"/entertainment/",
        r"/life-and-style/",
        r"/(news|sport)/[^/]+/\d{4}/\d{2}/\d{2}/",
        r"/news/[^/]+/article\d+\.ece",
    ],
    # Indian Express
    "indianexpress.com": [
        r"/article/",
        r"/section/(india|cities|world|business|technology|sports)/",
        r"/\d{4}/\d{2}/\d{2}/",
    ],
    # Times of India
    "timesofindia.indiatimes.com": [
        r"/city/",
        r"/india/",
        r"/world/",
        r"/business/",
        r"/sports/",
        r"/tech/",
        r"/entertainment/",
        r"/life-style/",
        r"/articleshow/\d+",
        r"/videos/[^/]+/\d+",  # news videos with IDs
    ],
    # NDTV
    "ndtv.com": [
        r"/india-news/",
        r"/world-news/",
        r"/business/",
        r"/sports/",
        r"/science/",
        r"/education/",
        r"/news/[^/]+/",
        r"/\d{4}-\d{2}-\d{2}-",
    ],
    # Economic Times
    "economictimes.indiatimes.com": [
        r"/news/",
        r"/markets/",
        r"/industry/",
        r"/tech/",
        r"/small-biz/",
        r"/articleshow/\d+",
    ],
}

# ---------------------------
# Domain-scoped deny rules
# ---------------------------
DOMAIN_DENY = {
    "indiatoday.in": [
        r"/magazine-subscription",
        r"/brandstudio",
        r"/videos?/?$",
        r"/photos?/?$",
        r"/about",
        r"/contact",
        r"/subscribe",
        r"/partners",
        r"/apps?",
        r"instagram\.com|facebook\.com|x\.com|twitter\.com",
    ],
    "thehindu.com": [
        r"/about[-/]",
        r"/contact[-/]",
        r"/brand[-/]",
        r"/epaper",
        r"/subscription",
        r"/archive",
        r"/page-\d+/?$",
        # list/pagination
        r"/news/?$",
        r"/news/[^/]+/?$",
        r"/news/[^/]+/page-\d+/?$",
    ],
    "indianexpress.com": [
        r"/about-us",
        r"/advertise",
        r"/privac",
        r"/term",
        r"/subscribe",
        r"/tag/[^/]+/?$",
        r"/photos/",
        r"/videos/?$",
        r"/elections/[^/]+/page/\d+",
        # cities (landing + pagination) — blocks pages like /cities/delhi/
        r"/cities/[^/]+/?$",
        r"/cities/[^/]+/page/\d+/?$",
        # generic section paginations
        r"/section/[^/]+/?$",
        r"/section/[^/]+/page/\d+/?$",
    ],
    "timesofindia.indiatimes.com": [
        r"/sitemap",
        r"/contact",
        r"/privac",
        r"/term",
        r"/subscribe",
        r"/briefs$",
        r"/tv$",
        r"/moviereviews",
        r"/etimes",
        r"/education/newsletter",
        r"/podcasts",
        r"/slideshows",
        # section roots & pagination (problematic: /india/2 etc.)
        r"/india/?$",
        r"/india/\d+/?$",
        r"/city/?$",
        r"/city/[^/]+/?$",
        r"/city/[^/]+/\d+/?$",
    ],
    "ndtv.com": [
        r"/sitemaps?/",
        r"/video/",
        r"/photos?/",
        r"/privac",
        r"/term",
        r"/about",
        r"/contact",
        r"/apps?",
        # section landing/pagination
        r"/india/?$",
        r"/india/page-\d+/?$",
        r"/news/?$",
        r"/news/page-\d+/?$",
    ],
    "economictimes.indiatimes.com": [
        r"/sitemap",
        r"/contact",
        r"/privac",
        r"/term",
        r"/subscribe",
        r"/tv",
        r"/podcasts",
        r"/slideshows",
        # section roots/pagination
        r"/news/?$",
        r"/news/[^/]+/?$",
        r"/news/[^/]+/page-\d+/?$",
    ],
}

# ---------------------------
# Helpers
# ---------------------------
def _host(domain: str) -> str:
    return domain.lower().lstrip("www.")

def _any_match(url: str, patterns) -> bool:
    return any(re.search(p, url, flags=re.I) for p in patterns)

def normalize_url(url: str) -> str:
    """
    Remove tracking params (utm_*, fbclid, gclid, icid) and fragments.
    """
    if not url:
        return url
    try:
        p = urlparse(url)
        q = [
            (k, v)
            for k, v in parse_qsl(p.query, keep_blank_values=True)
            if not k.lower().startswith("utm")
            and k.lower() not in ("fbclid", "gclid", "icid")
        ]
        p2 = p._replace(query=urlencode(q), fragment="")
        return urlunparse(p2)
    except Exception:
        return url

# ---------------------------
# Main predicate
# ---------------------------
def allowed_article_url(url: str) -> bool:
    """
    Return True if URL looks like a news article, False otherwise.
    """
    if not url or not url.startswith(("http://", "https://")):
        return False

    # Global hard deny first
    if _any_match(url, GLOBAL_DENY_PATTERNS):
        return False

    netloc = _host(urlparse(url).netloc)

    # Domain-specific deny
    for dom, pats in DOMAIN_DENY.items():
        if netloc.endswith(_host(dom)) and _any_match(url, pats):
            return False

    # Domain-specific allow
    for dom, pats in DOMAIN_ALLOW.items():
        if netloc.endswith(_host(dom)) and _any_match(url, pats):
            return True

    # Generic heuristics if no domain rule matched:
    if re.search(r"/\d{4}/\d{2}/\d{2}/", url):           # /YYYY/MM/DD/
        return True
    if re.search(r"/(article|story|articleshow)/", url, flags=re.I):
        return True
    if re.search(r"/news/[^/]+/\d{4}/\d{2}/\d{2}/", url, flags=re.I):
        return True

    return False

# Backward-compat alias
is_probable_article = allowed_article_url
