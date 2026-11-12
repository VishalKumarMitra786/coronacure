import json
from app import config, db, scraper, agent
import pytest

PAGE1 = """<html><body>
<div class="listing"><a href="/p/1"><span class="title">3BHK Whitefield</span></a>
 <span class="price">₹1.2 Cr</span><span class="location">Whitefield, Bangalore</span><span class="beds">3 Beds</span></div>
<div class="listing"><a href="/p/2"><span class="title">2BHK Indiranagar</span></a>
 <span class="price">80 lakh</span><span class="location">Indiranagar</span><span class="beds">2 Beds</span></div>
<a class="next" href="/page2">Next</a></body></html>"""
PAGE2 = """<html><head><script type="application/ld+json">{"@type":"Apartment","name":"4BHK Koramangala",
"url":"/p/3","numberOfBedrooms":4,"address":{"addressLocality":"Koramangala"},"offers":{"price":"2.5 Cr"}}</script></head></html>"""

@pytest.fixture(autouse=True)
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))

def fetch(url): return PAGE2 if "page2" in url else PAGE1
CFG = dict(scraper.DEFAULT_CONFIG, start_url="https://x.test/listings")

def test_parse_price():
    assert scraper.parse_price("₹1.2 Cr") == 12000000
    assert scraper.parse_price("80 lakh") == 8000000
    assert scraper.parse_price("$500,000") == 500000

def test_scrape_paginates_and_searches():
    assert scraper.run(CFG, fetch) == 3          # 2 via selectors, 1 via JSON-LD on page 2
    r = db.search_listings(location="Whitefield", max_price=13000000)
    assert [x["url"] for x in r] == ["https://x.test/p/1"] and r[0]["bedrooms"] == 3
    assert db.search_listings(max_price=9000000)[0]["location"] == "Indiranagar"
    out = agent.apply_tool(1, "search_listings", {"location": "Koramangala"})
    assert "https://x.test/p/3" in out

def test_failed_scrape_keeps_catalogue():
    scraper.run(CFG, fetch)
    db.upsert_listings([], 9e12)                 # empty scrape must not deactivate everything
    assert len(db.search_listings(limit=10)) == 3
