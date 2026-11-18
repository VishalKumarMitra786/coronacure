"""Keyless, LLM-free catalogue crawler.

- discover(area): finds candidate agency sites (seed list/file, or a robots.txt-permitted search page).
- crawl_site(seed): polite same-domain BFS that extracts listings from JSON-LD, falling back to
  heuristics (price + bedrooms + title on a detail page).
Never scrapes blocked portals (BLOCKED_DOMAINS), obeys robots.txt, rate-limits, stays on one domain.
"""
import os, re, time
from collections import deque
from urllib.parse import urljoin, urlparse, quote_plus, unquote, parse_qs
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from . import scraper

# Big portals forbid scraping in their terms; skip them by default. Extend via BLOCKED_DOMAINS="a.com,b.com".
BLOCKED_DOMAINS = {d for d in """99acres.com magicbricks.com housing.com nobroker.in commonfloor.com squareyards.com
 zillow.com realtor.com redfin.com trulia.com rightmove.co.uk zoopla.co.uk propertyfinder.ae bayut.com dubizzle.com
 facebook.com instagram.com youtube.com linkedin.com twitter.com x.com wikipedia.org google.com""".split()} | \
 {d.strip() for d in os.environ.get("BLOCKED_DOMAINS", "").split(",") if d.strip()}
MAX_PAGES_PER_SITE = int(os.environ.get("CRAWL_MAX_PAGES", "60"))
LISTINGISH = re.compile(r"propert|listing|for-?sale|for-?rent|buy|rent|flat|apartment|villa|house|home|residen|project", re.I)
PRICE_RE = re.compile(r"(?:₹|rs\.?|inr|\$|usd|€|£|aed|gbp)\s?\d[\d,\.]*\s?(?:crore|cr|lakhs?|lacs?|lac|million|mn|m|k)?\b", re.I)
BEDS_RE = re.compile(r"(\d+)\s*(?:bhk|bed(?:room)?s?|br)\b", re.I)
TYPE_RE = re.compile(r"\b(apartment|flat|villa|house|plot|land|penthouse|studio|townhouse|duplex|condo|office|shop)\b", re.I)

def is_blocked(url):
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)

def _meta(soup, *names):
    for n in names:
        el = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if el and el.get("content"): return el["content"].strip()

def extract_listing(url, html):
    """Return a listing dict if this page looks like ONE property detail page, else None."""
    soup = BeautifulSoup(html, "html.parser")
    ld = scraper.from_jsonld(soup, url)
    if ld:
        return ld[0] if len(ld) == 1 else None  # several JSON-LD items = an index page
    for t in soup(["script", "style", "nav", "footer", "header"]): t.decompose()
    text = soup.get_text(" ", strip=True)
    prices = set(m.group().lower() for m in PRICE_RE.finditer(text))
    if not 1 <= len(prices) <= 4: return None  # no price, or an index page full of them
    h1 = soup.find("h1")
    title = (h1.get_text(" ", strip=True) if h1 else None) or _meta(soup, "og:title") or (soup.title.string.strip() if soup.title and soup.title.string else None)
    if not title: return None
    beds = BEDS_RE.search(title + " " + url) or BEDS_RE.search(text[:3000])
    ptype = TYPE_RE.search(title + " " + url)
    if not (beds or ptype): return None
    price_el = soup.find(class_=re.compile("price", re.I))
    price_text = None
    if price_el:
        m = PRICE_RE.search(price_el.get_text(" ", strip=True)); price_text = m.group() if m else None
    price_text = price_text or next(iter(PRICE_RE.finditer(text))).group()
    loc_el = soup.find(class_=re.compile(r"locat|address|area", re.I))
    loc = loc_el.get_text(" ", strip=True)[:120] if loc_el else None
    if not loc:
        m = re.search(r"\bin ([A-Z][\w]+(?:[ ,]+[A-Z][\w]+){0,3})", title)
        loc = m.group(1) if m else None
    low = (url + " " + title).lower()
    return {"url": url, "title": title[:200], "price_text": price_text, "price_num": scraper.parse_price(price_text),
            "location": loc, "bedrooms": int(beds.group(1)) if beds else None,
            "property_type": ptype.group(1).lower() if ptype else None,
            "intent": "rent" if re.search(r"for[- ]rent|/rent|\brent\b", low) else "buy",
            "image": _meta(soup, "og:image"), "description": (_meta(soup, "og:description", "description") or "")[:500]}

def crawl_site(seed, fetch=None, max_pages=MAX_PAGES_PER_SITE):
    """BFS within the seed's domain, listing-like links first. Returns deduped listings."""
    if is_blocked(seed): raise PermissionError(f"{urlparse(seed).netloc} is on the blocked-portal list")
    domain = urlparse(seed).netloc
    fetch = fetch or scraper.make_fetcher(seed)
    queue, seen, found = deque([seed]), {seed}, {}
    pages = 0
    while queue and pages < max_pages:
        url = queue.popleft()
        try: html = fetch(url)
        except Exception: continue
        pages += 1
        item = extract_listing(url, html)
        if item and urlparse(item["url"]).netloc == domain: found[item["url"]] = item
        soup = BeautifulSoup(html, "html.parser")
        good, rest = [], []
        for a in soup.find_all("a", href=True):
            u = urljoin(url, a["href"]).split("#")[0]
            p = urlparse(u)
            if p.scheme not in ("http", "https") or p.netloc != domain or u in seen: continue
            if re.search(r"\.(jpg|jpeg|png|gif|pdf|zip|svg|webp)$", p.path, re.I): continue
            seen.add(u); (good if LISTINGISH.search(p.path) else rest).append(u)
        queue.extendleft(reversed(good)); queue.extend(rest)  # listing-like links jump the queue
    return list(found.values())

def discover(area, limit=8, fetch=None):
    """Find candidate agency sites for an area. Uses SEED_URLS (comma list) and/or seeds.txt first;
    otherwise a search results page, only if that site's robots.txt permits automated access."""
    seeds = [u.strip() for u in os.environ.get("SEED_URLS", "").split(",") if u.strip()]
    if os.path.exists("seeds.txt"):
        seeds += [l.strip() for l in open("seeds.txt") if l.strip().startswith("http")]
    if not seeds:
        q = quote_plus(f"{area} real estate agency properties for sale")
        search = f"https://html.duckduckgo.com/html/?q={q}"
        try:
            if fetch is None:
                rp = RobotFileParser("https://html.duckduckgo.com/robots.txt"); rp.read()
                if not rp.can_fetch(scraper.UA, search):
                    print("[discover] search engine robots.txt disallows automated queries; provide SEED_URLS/seeds.txt")
                    return []
                fetch = scraper.make_fetcher(search)
            soup = BeautifulSoup(fetch(search), "html.parser")
            for a in soup.select("a.result__a, a[href*='uddg=']"):
                href = a.get("href", "")
                u = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
                if u.startswith("http"): seeds.append(u)
        except Exception as e:
            print("[discover] search failed:", e)
    out, doms = [], set()
    for u in seeds:
        root = f"{urlparse(u).scheme}://{urlparse(u).netloc}/"
        if urlparse(u).netloc and urlparse(u).netloc not in doms and not is_blocked(u):
            doms.add(urlparse(u).netloc); out.append(root)
    return out[:limit]

if __name__ == "__main__":
    import sys
    from . import sources
    area = " ".join(sys.argv[1:]) or "your city"
    for u in discover(area):
        print("approved + queued:", sources.add_source(u)["url"])
    print(sources.refresh_all())
