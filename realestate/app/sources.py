"""Approved catalogue sources. Adding a URL = approving that domain. Claude learns each site's layout."""
import json, os, time
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from . import db, agent, scraper, crawler

CONFIG_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "card": {"type": "string", "description": "CSS selector matching ONE element per property listing"},
        "link": {"type": "string", "description": "selector, relative to card, for the <a> to the listing page ('a' is usually fine)"},
        "title": {"type": "string"}, "price": {"type": "string"}, "location": {"type": "string"},
        "bedrooms": {"type": "string"}, "property_type": {"type": "string"}, "image": {"type": "string"},
        "next_page": {"type": "string", "description": "selector for the next-page link, or empty string"},
        "default_intent": {"type": "string", "enum": ["buy", "rent"]},
    },
    "required": ["card", "link", "title", "price", "location", "bedrooms", "property_type", "image",
                 "next_page", "default_intent"],
}

def _shrink(html, limit=60000):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "svg", "noscript", "head"]):
        t.decompose()
    return str(soup)[:limit]

def learn_config(url, html, feedback=""):
    """Ask Claude for CSS selectors for this listings page."""
    prompt = (f"This is the HTML of a real-estate listings page ({url}). Return CSS selectors that extract each property. "
              "Selectors for title/price/location/bedrooms/property_type/image are relative to the card element. "
              "Use an empty string for a field the page doesn't show. Prefer stable class names over positional selectors.\n"
              f"{feedback}\n\nHTML:\n{_shrink(html)}")
    resp = agent.client().messages.create(
        model=agent.config.MODEL, max_tokens=2000, messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": CONFIG_SCHEMA}})
    cfg = json.loads("".join(b.text for b in resp.content if b.type == "text"))
    cfg["start_url"] = url
    return cfg

def _learn_and_verify(url, fetch):
    html = fetch(url)
    if scraper.from_jsonld(BeautifulSoup(html, "html.parser"), url):
        return {**scraper.DEFAULT_CONFIG, "start_url": url}  # structured data: no selectors needed
    feedback = ""
    for _ in range(2):  # one retry with feedback
        cfg = learn_config(url, html, feedback)
        try:
            found = scraper.from_selectors(BeautifulSoup(html, "html.parser"), url, cfg)
        except Exception as e:  # bad selector syntax
            found, feedback = [], f"Your previous selectors raised an error: {e}. Fix them."
        else:
            if len([f for f in found if f.get("title")]) >= 1:
                return cfg
            feedback = f"Your previous selectors {json.dumps(cfg)} matched no listings with a title. Try again."
    raise ValueError("couldn't find listings on this page (it may be JavaScript-rendered)")

def add_source(url):
    domain = urlparse(url).netloc
    if urlparse(url).scheme not in ("http", "https") or not domain:
        raise ValueError("need a full http(s) URL")
    with db.conn() as c:
        db._listing_conn()
        c.execute("INSERT OR IGNORE INTO sources(url, domain) VALUES(?,?)", (url, domain))
        return dict(c.execute("SELECT * FROM sources WHERE url=?", (url,)).fetchone())

def list_sources():
    with db._listing_conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM sources ORDER BY id")]

def remove_source(source_id):
    with db._listing_conn() as c:
        c.execute("UPDATE listings SET active=0 WHERE source_id=?", (source_id,))
        c.execute("DELETE FROM sources WHERE id=?", (source_id,))

def refresh_source(src, fetch=None):
    """Scrape one source; (re)learn selectors if none stored or the layout seems to have changed."""
    started = time.time()
    fetch = fetch or scraper.make_fetcher(src["url"])
    cfg = json.loads(src["config"]) if src["config"] else None
    try:
        if cfg is None:
            cfg = _choose_config(src["url"], fetch)
        if cfg.get("crawl"):
            items = crawler.crawl_site(src["url"], fetch)
            if not items: raise ValueError("crawled the site but found no listing pages")
            db.upsert_listings(items, started, source_id=src["id"])
            return _record(src, cfg, items, "ok", None)
        items = scraper.scrape(cfg, fetch)
        if not items and src["config"]:  # worked before, now empty -> site probably changed
            cfg = _learn_and_verify(src["url"], fetch)
            items = scraper.scrape(cfg, fetch)
        if not items:
            raise ValueError("no listings found")
        db.upsert_listings(items, started, source_id=src["id"])
        status, err = "ok", None
    except Exception as e:
        items, status, err = [], "error", str(e)[:300]
    return _record(src, cfg, items, status, err)

def _record(src, cfg, items, status, err):
    with db._listing_conn() as c:
        c.execute("UPDATE sources SET config=?, status=?, last_count=?, last_scraped=?, error=? WHERE id=?",
                  (json.dumps(cfg) if cfg else None, status, len(items), time.time(), err, src["id"]))
    return {"url": src["url"], "status": status, "listings": len(items), "error": err}

def _choose_config(url, fetch):
    """Claude-learned selectors when an API key exists; otherwise (or if learning fails) keyless crawling."""
    if os.environ.get("ANTHROPIC_API_KEY") or agent._client is not None:
        try:
            return _learn_and_verify(url, fetch)
        except Exception:
            pass
    return {"crawl": True, "start_url": url}

def refresh_all(fetch=None):
    return [refresh_source(s, fetch) for s in list_sources()]

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "add":
        print(add_source(sys.argv[2]))
    else:
        print(json.dumps(refresh_all(), indent=2))
