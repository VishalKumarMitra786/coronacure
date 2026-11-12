import json, types, pytest
from app import config, db, agent, sources, scraper
from tests.test_scraper import PAGE1, PAGE2, CFG

URL = "https://x.test/listings"
GOOD = {"card": ".listing", "link": "a", "title": ".title", "price": ".price", "location": ".location",
        "bedrooms": ".beds", "property_type": "", "image": "img", "next_page": "a.next", "default_intent": "buy"}

class FakeLearner:
    def __init__(self, answers): self.answers, self.calls, self.messages = list(answers), 0, self
    def create(self, **kw):
        self.calls += 1
        a = self.answers.pop(0)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(a))])

@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))

def fetch(url): return PAGE2 if "page2" in url else PAGE1

def test_learns_selectors_with_retry(monkeypatch):
    monkeypatch.setattr(agent, "_client", FakeLearner([{**GOOD, "card": ".nothing"}, GOOD]))  # first guess wrong
    src = sources.add_source(URL)
    res = sources.refresh_source(src, fetch)
    assert res["status"] == "ok" and res["listings"] == 3 and agent._client.calls == 2
    assert sources.list_sources()[0]["config"]            # selectors stored for next time
    agent._client.answers = []                            # second run must NOT call Claude again
    assert sources.refresh_all(fetch)[0]["listings"] == 3

def test_failed_source_does_not_wipe_others(monkeypatch):
    monkeypatch.setattr(agent, "_client", FakeLearner([GOOD, GOOD, GOOD]))
    a = sources.add_source(URL); b = sources.add_source("https://y.test/l")
    sources.refresh_source(a, fetch)
    res = sources.refresh_source(b, lambda u: "<html><body>js app</body></html>")
    assert res["status"] == "error"
    assert len(db.search_listings(limit=10)) == 3          # source A untouched

def test_stays_on_domain():
    page = PAGE1.replace('href="/p/2"', 'href="https://evil.test/p/2"')
    items = scraper.scrape(CFG, lambda u: page if "page2" not in u else PAGE2)
    assert all("evil.test" not in i["url"] for i in items)
