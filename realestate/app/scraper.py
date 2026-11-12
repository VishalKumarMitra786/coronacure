"""Catalogue scraper for listing pages you own or have permission to scrape.

Strategy: (1) schema.org JSON-LD if the page has it, else (2) CSS selectors from SCRAPER_CONFIG.
Respects robots.txt, rate-limits, and identifies itself.  Run:  python -m app.scraper
"""
import json, re, time, os, sys
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import httpx2 as httpx
from bs4 import BeautifulSoup
from . import config, db

UA = os.environ.get("SCRAPER_USER_AGENT", "CatalogueBot/1.0 (+contact: set SCRAPER_USER_AGENT)")
DELAY_S = float(os.environ.get("SCRAPER_DELAY_S", "2"))
MAX_PAGES = int(os.environ.get("SCRAPER_MAX_PAGES", "20"))

# Edit for your site, or point SCRAPER_CONFIG at a JSON file with the same keys.
DEFAULT_CONFIG = {
    "start_url": os.environ.get("CATALOGUE_URL", ""),
    "card": ".listing",            # one element per property
    "link": "a",                   # inside card; href = listing url
    "title": ".title",
    "price": ".price",
    "location": ".location",
    "bedrooms": ".beds",
    "property_type": ".type",
    "image": "img",
    "next_page": "a.next",         # pagination link (optional)
    "default_intent": "buy",       # buy | rent
}

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    p = os.environ.get("SCRAPER_CONFIG")
    if p:
        cfg.update(json.load(open(p)))
    return cfg

def parse_price(text):
    """'₹1.2 Cr' -> 12000000, '80 lakh' -> 8000000, '$500,000' -> 500000, '45k' -> 45000."""
    if not text: return None
    t = text.lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(crore|cr|lakhs?|lacs?|lac|million|mn|m|thousand|k)?\b", t)
    if not m: return None
    mult = {"crore": 1e7, "cr": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
            "million": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}.get(m.group(2) or "", 1)
    return float(m.group(1)) * mult

def _int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None

def _txt(node, sel):
    if not sel: return None
    el = node.select_one(sel)
    return el.get_text(" ", strip=True) if el else None

def from_jsonld(soup, base):
    out = []
    def walk(o):
        if isinstance(o, list):
            for x in o: walk(x)
        elif isinstance(o, dict):
            t = o.get("@type"); t = " ".join(t) if isinstance(t, list) else (t or "")
            if any(k in t for k in ("RealEstateListing", "Residence", "House", "Apartment", "SingleFamilyResidence", "Product")) and o.get("url"):
                offers = o.get("offers") or {}
                offers = offers[0] if isinstance(offers, list) and offers else offers
                price = offers.get("price") if isinstance(offers, dict) else None
                addr = o.get("address")
                loc = ", ".join(str(v) for k, v in addr.items() if k in ("addressLocality", "addressRegion")) if isinstance(addr, dict) else addr
                img = o.get("image"); img = img[0] if isinstance(img, list) and img else img
                out.append({"url": urljoin(base, o["url"]), "title": o.get("name"), "price_text": str(price) if price else None,
                            "price_num": parse_price(str(price)) if price else None, "location": loc,
                            "bedrooms": _int(str(o.get("numberOfBedrooms") or o.get("numberOfRooms") or "")),
                            "property_type": t.split()[0], "image": img if isinstance(img, str) else None,
                            "description": (o.get("description") or "")[:500]})
            for v in o.values(): walk(v)
    for s in soup.find_all("script", type="application/ld+json"):
        try: walk(json.loads(s.string or ""))
        except Exception: pass
    return out

def from_selectors(soup, base, cfg):
    out = []
    for card in soup.select(cfg["card"]):
        a = card.select_one(cfg["link"]) if cfg["link"] else None
        href = (a.get("href") if a else None) or (card.get("href"))
        if not href: continue
        img = card.select_one(cfg["image"]) if cfg.get("image") else None
        price = _txt(card, cfg.get("price"))
        title = _txt(card, cfg.get("title"))
        out.append({"url": urljoin(base, href), "title": title, "price_text": price, "price_num": parse_price(price),
                    "location": _txt(card, cfg.get("location")), "bedrooms": _int(_txt(card, cfg.get("bedrooms"))),
                    "property_type": _txt(card, cfg.get("property_type")),
                    "image": urljoin(base, img["src"]) if img and img.get("src") else None})
    return out

def scrape(cfg=None, fetch=None):
    """Returns the list of listings found. `fetch(url)->html` is injectable for tests."""
    cfg = cfg or load_config()
    start = cfg["start_url"]
    if not start: raise SystemExit("Set CATALOGUE_URL (or start_url in SCRAPER_CONFIG).")
    root = f"{urlparse(start).scheme}://{urlparse(start).netloc}"
    if fetch is None:
        rp = RobotFileParser(root + "/robots.txt"); rp.read()
        client = httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        def fetch(url):
            if not rp.can_fetch(UA, url): raise PermissionError(f"robots.txt disallows {url}")
            time.sleep(DELAY_S)
            r = client.get(url); r.raise_for_status(); return r.text
    items, seen, url = {}, set(), start
    for _ in range(MAX_PAGES):
        if url in seen: break
        seen.add(url)
        soup = BeautifulSoup(fetch(url), "html.parser")
        found = from_jsonld(soup, url) or from_selectors(soup, url, cfg)
        for it in found:
            it.setdefault("intent", cfg.get("default_intent"))
            items[it["url"]] = it
        nxt = soup.select_one(cfg["next_page"]) if cfg.get("next_page") else None
        if not (nxt and nxt.get("href")): break
        url = urljoin(url, nxt["href"])
    return list(items.values())

def run(cfg=None, fetch=None):
    started = time.time()
    items = scrape(cfg, fetch)
    db.upsert_listings(items, started)
    return len(items)

if __name__ == "__main__":
    print(f"Scraped {run()} listings")
