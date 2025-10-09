# discovery/extractor.py
import hashlib
import logging
import re
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from dateutil import tz
from urllib.parse import urljoin

logger = logging.getLogger("discovery.extractor")
logger.setLevel(logging.INFO)

# Try to import newspaper3k; it's optional but preferred for nicer parsing
try:
    from newspaper import Article as NArticle  # type: ignore
except Exception:
    NArticle = None

# readability is optional
try:
    from readability import Document  # type: ignore
except Exception:
    Document = None


# -------------------------
# Utilities
# -------------------------
INDEX_LIKE_TITLE_RE = re.compile(
    r"(latest .+ news(?: today)?(?: & headlines)?|news today|headlines|live updates|"
    r"cities|state news|technology news|sports news|political news|"
    r"entertainment news|mobile news|gadgets news|book reviews|about us|contact)",
    re.IGNORECASE,
)

def _best_meta_image(soup_full, base_url: str) -> Optional[str]:
    if soup_full is None:
        return None

    def _get_content(sel_prop: str, is_name=False):
        if is_name:
            tag = soup_full.find("meta", attrs={"name": sel_prop})
        else:
            tag = soup_full.find("meta", property=sel_prop)
        return (tag.get("content").strip() if tag and tag.get("content") else None)

    cands = [
        _get_content("og:image"),
        _get_content("og:image:secure_url"),
        _get_content("twitter:image"),
        _get_content("twitter:image:src"),
        _get_content("og:image", is_name=True),
        _get_content("twitter:image", is_name=True),
    ]
    for c in cands:
        if c:
            try:
                return urljoin(base_url, c)
            except Exception:
                return c
    return None

def _fallback_body_image(soup_full, base_url: str) -> Optional[str]:
    if soup_full is None:
        return None
    imgs = soup_full.find_all("img")
    for img in imgs:
        src = (img.get("src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        try:
            absu = urljoin(base_url, src)
        except Exception:
            absu = src
        try:
            w = int(img.get("width") or 0)
            h = int(img.get("height") or 0)
            if w >= 200 or h >= 200:
                return absu
        except Exception:
            pass
        return absu
    return None

def _clean_repetitive_lines(text: str) -> str:
    if not text:
        return ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    cleaned = []
    prev = None
    repeat_count = 0
    for ln in lines:
        if ln == prev:
            repeat_count += 1
        else:
            repeat_count = 0
        if repeat_count >= 2:
            continue
        cleaned.append(ln)
        prev = ln
    joined = "\n\n".join(cleaned)
    joined = re.sub(r'\n{3,}', '\n\n', joined)
    return joined.strip()

def _compute_content_hash(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

def _to_naive_utc(dt: datetime) -> Optional[datetime]:
    if dt is None:
        return None
    try:
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(tz.tzutc()).replace(tzinfo=None)
    except Exception:
        try:
            return _normalize_publish_date(dt)
        except Exception:
            return None

def _normalize_publish_date(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return _to_naive_utc(val)
    try:
        dt = dateparser.parse(str(val))
        return _to_naive_utc(dt)
    except Exception:
        return None

def _safe_json_ld_parse(text: str):
    if not text:
        return None
    try:
        import json
        return json.loads(text)
    except Exception:
        try:
            m = re.search(r'(\{.*\})', text, flags=re.S)
            if m:
                import json
                return json.loads(m.group(1))
        except Exception:
            return None
    return None

def _extract_canonical(soup: BeautifulSoup) -> Optional[str]:
    try:
        link = soup.find("link", rel="canonical")
        if link and link.get("href"):
            return link.get("href")
        og = soup.find("meta", property="og:url")
        if og and og.get("content"):
            return og.get("content")
    except Exception:
        pass
    return None

def _page_type_flags(soup_full: BeautifulSoup) -> Dict[str, bool]:
    """
    Heuristically decide whether page is an article or an index/list/category page.
    Returns {'is_article_like': bool, 'is_index_like': bool}
    """
    is_article_like = False
    is_index_like = False

    try:
        # og:type
        og_type = soup_full.find("meta", property="og:type")
        if og_type and og_type.get("content"):
            ot = og_type.get("content").lower()
            if "article" in ot or "news" in ot or "blogposting" in ot:
                is_article_like = True
            if "website" in ot or "profile" in ot:
                is_index_like = True

        # JSON-LD types
        ld_nodes = soup_full.find_all("script", type="application/ld+json")
        for ld in ld_nodes:
            if not ld.string:
                continue
            j = _safe_json_ld_parse(ld.string)
            if not j:
                continue
            objs = j if isinstance(j, list) else [j]
            for obj in objs:
                if not isinstance(obj, dict):
                    continue
                t = obj.get("@type")
                if isinstance(t, list):
                    t = " ".join([str(x).lower() for x in t])
                elif isinstance(t, str):
                    t = t.lower()
                else:
                    t = ""
                if any(x in t for x in ["newsarticle", "article", "blogposting"]):
                    is_article_like = True
                if any(x in t for x in ["collectionpage", "webpage", "searchresultspage", "itemlist"]):
                    is_index_like = True
    except Exception:
        pass

    try:
        # lots of <article> teasers -> likely index
        art_tags = soup_full.find_all("article")
        if len(art_tags) >= 4:
            is_index_like = True
    except Exception:
        pass

    try:
        # H1 patterns like "Latest Pune News …"
        if soup_full.h1 and soup_full.h1.get_text(strip=True):
            if INDEX_LIKE_TITLE_RE.search(soup_full.h1.get_text(strip=True)):
                is_index_like = True
    except Exception:
        pass

    return {"is_article_like": is_article_like, "is_index_like": is_index_like}


# -------------------------
# Core extractors
# -------------------------
def extract_article(url: str, fetch_html_first: bool = True, timeout: int = 12) -> Dict[str, Any]:
    """
    Return:
      title, text, cleaned_text, short_summary, top_image_url, authors, published_at,
      html, canonical_url, word_count, is_index_like
    """
    headers = {"User-Agent": "MVP-NewsBot/1.0 (+your-email@example.com)"}
    html: Optional[str] = None

    if fetch_html_first:
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            html = r.text
        except Exception as e:
            logger.debug("initial fetch failed for %s : %s", url, e)
            html = None

    # 1) newspaper3k
    if NArticle is not None:
        try:
            art = NArticle(url)
            if html:
                art.set_html(html)
            art.download()
            art.parse()
            title = art.title or ""
            text = (art.text or "").strip()
            cleaned = _clean_repetitive_lines(text)
            authors = art.authors or []
            publish_date = _normalize_publish_date(art.publish_date)
            top_image = getattr(art, "top_image", None)
            canonical = None
            is_index_like = False
            if html:
                soup_full = BeautifulSoup(html, "html.parser")
                canonical = _extract_canonical(soup_full)
                flags = _page_type_flags(soup_full)
                is_index_like = flags["is_index_like"]

            if text and len(text.split()) > 40:
                return {
                    "title": title,
                    "text": text,
                    "cleaned_text": cleaned,
                    "short_summary": (cleaned[:400] + "...") if len(cleaned) > 400 else cleaned,
                    "top_image_url": top_image,
                    "authors": authors,
                    "published_at": publish_date,
                    "html": html,
                    "canonical_url": canonical,
                    "word_count": len((cleaned or text).split()),
                    "is_index_like": is_index_like,
                }
        except Exception:
            logger.debug("newspaper extractor failed for %s", url)
            logger.debug(traceback.format_exc())

    # 2) readability
    if Document is not None:
        try:
            if not html:
                r = requests.get(url, headers=headers, timeout=timeout)
                r.raise_for_status()
                html = r.text
            doc = Document(html)
            summary_html = doc.summary()
            soup = BeautifulSoup(summary_html or "", "html.parser")
            text = soup.get_text(separator="\n").strip()
            cleaned = _clean_repetitive_lines(text)

            soup_full = BeautifulSoup(html or "", "html.parser")
            title = (soup_full.find("meta", property="og:title").get("content")
                     if soup_full.find("meta", property="og:title") else doc.short_title() or "")
            top_image = _best_meta_image(soup_full, url) or _fallback_body_image(soup_full, url)

            # LD+JSON and meta date
            authors = []
            publish_date = None
            try:
                flags = _page_type_flags(soup_full)
            except Exception:
                flags = {"is_article_like": False, "is_index_like": False}

            try:
                ld_nodes = soup_full.find_all("script", type="application/ld+json")
                for ld in ld_nodes:
                    if not ld.string:
                        continue
                    j = _safe_json_ld_parse(ld.string)
                    if not j:
                        continue
                    objs = j if isinstance(j, list) else [j]
                    for obj in objs:
                        if not isinstance(obj, dict):
                            continue
                        a = obj.get("author") or obj.get("creator")
                        if a:
                            if isinstance(a, list):
                                for x in a:
                                    if isinstance(x, dict):
                                        n = x.get("name") or x.get("givenName") or x.get("familyName")
                                        if n:
                                            authors.append(n)
                                    else:
                                        authors.append(str(x))
                            elif isinstance(a, dict):
                                n = a.get("name") or a.get("givenName") or a.get("familyName")
                                if n:
                                    authors.append(n)
                            else:
                                authors.append(str(a))
                        for k in ("datePublished", "datepublished", "dateCreated", "datecreated", "uploadDate"):
                            if k in obj and obj.get(k):
                                pd = _normalize_publish_date(obj.get(k))
                                if pd:
                                    publish_date = pd
                                    break
                        if publish_date:
                            break
            except Exception:
                logger.debug("ld+json parse error", exc_info=True)

            if not publish_date:
                meta_date = (soup_full.find("meta", attrs={"name": "pubdate"})
                             or soup_full.find("meta", property="article:published_time")
                             or soup_full.find("meta", attrs={"name": "publication_date"}))
                if meta_date and meta_date.get("content"):
                    publish_date = _normalize_publish_date(meta_date.get("content"))
            if not publish_date:
                t = soup_full.find("time")
                if t:
                    dtv = t.get("datetime") or t.get("title") or t.string
                    if dtv:
                        publish_date = _normalize_publish_date(dtv)

            canonical = _extract_canonical(soup_full)

            if text and len(text.split()) > 20:
                return {
                    "title": title or "",
                    "text": text,
                    "cleaned_text": cleaned,
                    "short_summary": (cleaned[:400] + "...") if len(cleaned) > 400 else cleaned,
                    "top_image_url": top_image,
                    "authors": authors or [],
                    "published_at": publish_date,
                    "html": html,
                    "canonical_url": canonical,
                    "word_count": len((cleaned or text).split()),
                    "is_index_like": flags["is_index_like"],
                }
        except Exception:
            logger.debug("readability extractor failed for %s", url)
            logger.debug(traceback.format_exc())

    # 3) BeautifulSoup fallback
    try:
        if not html:
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            html = r.text
        soup_full = BeautifulSoup(html or "", "html.parser")

        for s in soup_full(["script", "style", "noscript"]):
            s.extract()
        raw_text = soup_full.get_text(separator="\n")
        lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        raw_text = "\n\n".join(lines[:1000])
        cleaned = _clean_repetitive_lines(raw_text)

        og_title_tag = soup_full.find("meta", property="og:title")
        title = (og_title_tag.get("content") if og_title_tag and og_title_tag.get("content")
                 else (soup_full.title.string if soup_full.title else ""))

        top_image = _best_meta_image(soup_full, url) or _fallback_body_image(soup_full, url)

        # flags (article vs index)
        flags = _page_type_flags(soup_full)

        # dates
        authors = []
        publish_date = None
        try:
            ld_nodes = soup_full.find_all("script", type="application/ld+json")
            for ld in ld_nodes:
                if not ld.string:
                    continue
                j = _safe_json_ld_parse(ld.string)
                if not j:
                    continue
                objs = j if isinstance(j, list) else [j]
                for obj in objs:
                    if not isinstance(obj, dict):
                        continue
                    for k in ("datePublished", "datepublished", "dateCreated", "datecreated", "uploadDate"):
                        if k in obj and obj.get(k):
                            pd = _normalize_publish_date(obj.get(k))
                            if pd:
                                publish_date = pd
                                break
                    if publish_date:
                        break
        except Exception:
            pass

        if not publish_date:
            meta_date = (soup_full.find("meta", attrs={"name": "pubdate"})
                         or soup_full.find("meta", property="article:published_time"))
            if meta_date and meta_date.get("content"):
                publish_date = _normalize_publish_date(meta_date.get("content"))
        if not publish_date:
            t = soup_full.find("time")
            if t:
                dtv = t.get("datetime") or t.get("title") or t.string
                if dtv:
                    publish_date = _normalize_publish_date(dtv)

        canonical = _extract_canonical(soup_full)

        return {
            "title": title or "",
            "text": raw_text or "",
            "cleaned_text": cleaned,
            "short_summary": (cleaned[:400] + "...") if len(cleaned) > 400 else cleaned,
            "top_image_url": top_image,
            "authors": authors or [],
            "published_at": publish_date,
            "html": html,
            "canonical_url": canonical,
            "word_count": len((cleaned or raw_text).split()),
            "is_index_like": flags["is_index_like"],
        }
    except Exception:
        logger.debug("final fallback extractor failed for %s", url)
        logger.debug(traceback.format_exc())
        return {
            "title": "",
            "text": "",
            "cleaned_text": "",
            "short_summary": "",
            "top_image_url": None,
            "authors": [],
            "published_at": None,
            "html": None,
            "canonical_url": None,
            "word_count": 0,
            "is_index_like": False,
        }


# -------------------------
# Task-facing wrapper
# -------------------------
def fetch_and_process(item: Any) -> Dict[str, Any]:
    try:
        if isinstance(item, str):
            item_dict = {"url": item}
        elif isinstance(item, dict):
            item_dict = item.copy()
        else:
            if hasattr(item, "get"):
                item_dict = dict(item)
            elif hasattr(item, "url"):
                item_dict = {"url": getattr(item, "url")}
            else:
                item_dict = {"url": str(item)}
    except Exception:
        logger.exception("Failed to normalize item input")
        return {"status": "failed", "error": "normalize_failure", "item": str(item)}

    url = item_dict.get("url")
    if not url:
        return {"status": "failed", "error": "no_url_provided", "item": item_dict}

    try:
        extracted = extract_article(url, fetch_html_first=True)
    except Exception as e:
        logger.exception("extract_article crashed for %s", url)
        return {"status": "failed", "url": url, "error": f"extractor_crash:{e}"}

    title = (extracted.get("title") or item_dict.get("title") or "").strip()
    text = extracted.get("text") or ""
    cleaned_text = extracted.get("cleaned_text") or _clean_repetitive_lines(text)
    short_summary = extracted.get("short_summary") or (cleaned_text[:300] + "..." if len(cleaned_text) > 300 else cleaned_text)
    html = extracted.get("html")
    top_image_url = extracted.get("top_image_url") or extracted.get("top_image") or None
    authors = extracted.get("authors") or item_dict.get("authors") or []
    published_at_raw = extracted.get("published_at") or item_dict.get("published_at")
    published_at = _normalize_publish_date(published_at_raw)
    canonical_url = extracted.get("canonical_url") or None

    content_hash = _compute_content_hash(cleaned_text or text)
    word_count = extracted.get("word_count") or len((cleaned_text or text).split())
    is_index_like = bool(extracted.get("is_index_like"))

    result = {
        "status": "ok",
        "url": url,
        "title": title,
        "text": text,
        "cleaned_text": cleaned_text,
        "short_summary": short_summary,
        "html": html,
        "top_image_url": top_image_url,
        "authors": authors,
        "published_at": published_at,
        "canonical_url": canonical_url,
        "content_hash": content_hash,
        "word_count": word_count,
        "is_index_like": is_index_like,
        "fetched_at": datetime.utcnow().isoformat(),
    }

    logger.info("extracted url=%s title_len=%d text_words=%d index_like=%s",
                url, len(title or ""), len((text or "").split()), is_index_like)
    return result
