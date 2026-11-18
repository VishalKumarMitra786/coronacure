import json
from app import config, db, crawler, sources, agent
import pytest

SITE = {
 "https://agency.test/": '<a href="/properties">Properties</a><a href="/about">About</a><a href="https://99acres.com/x">x</a>',
 "https://agency.test/about": "<h1>About us</h1><p>We sell homes since 1999.</p>",
 "https://agency.test/properties": '<a href="/properties/3bhk-apartment-whitefield">a</a><a href="/properties/villa-for-rent-hsr">b</a><p>From ₹50 Lakh, ₹1.2 Cr, ₹3 Cr, ₹4 Cr, ₹5 Cr</p>',
 "https://agency.test/properties/3bhk-apartment-whitefield":
   '<h1>3 BHK Apartment in Whitefield</h1><div class="price">₹1.2 Cr</div><div class="location">Whitefield, Bangalore</div>'
   '<meta property="og:image" content="https://agency.test/i.jpg">',
 "https://agency.test/properties/villa-for-rent-hsr":
   '<html><head><title>x</title></head><h1>4 Bedroom Villa for rent in HSR Layout</h1><span class="price">$2,500</span>',
}
def fetch(u):
    if u in SITE: return SITE[u]
    raise IOError(u)

@pytest.fixture(autouse=True)
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(agent, "_client", None)

def test_crawl_extracts_without_llm():
    items = {i["url"].rsplit("/", 1)[1]: i for i in crawler.crawl_site("https://agency.test/", fetch)}
    assert set(items) == {"3bhk-apartment-whitefield", "villa-for-rent-hsr"}   # index/about pages skipped
    a = items["3bhk-apartment-whitefield"]
    assert (a["bedrooms"], a["price_num"], a["location"], a["intent"]) == (3, 12000000, "Whitefield, Bangalore", "buy")
    v = items["villa-for-rent-hsr"]
    assert v["intent"] == "rent" and v["price_num"] == 2500 and v["location"].startswith("HSR")

def test_blocked_portal_refused():
    with pytest.raises(PermissionError): crawler.crawl_site("https://www.99acres.com/", fetch)
    assert crawler.is_blocked("https://m.zillow.com/x") and not crawler.is_blocked("https://agency.test")

def test_keyless_source_falls_back_to_crawl():
    src = sources.add_source("https://agency.test/")
    res = sources.refresh_source(src, fetch)
    assert res["status"] == "ok" and res["listings"] == 2
    assert len(db.search_listings(location="Whitefield")) == 1

def test_discover_from_seeds(monkeypatch):
    monkeypatch.setenv("SEED_URLS", "https://agency.test/foo, https://www.zillow.com/a, https://agency.test/bar")
    assert crawler.discover("anywhere") == ["https://agency.test/"]   # blocked portal + duplicate domain dropped
