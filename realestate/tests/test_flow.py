import os, time, types, pytest
os.environ["DB_PATH"] = ":memory:"  # replaced per-test below

from app import config, db, agent, main, followups, whatsapp

def block(type_, **kw): return types.SimpleNamespace(type=type_, **kw)
def resp(blocks, stop): return types.SimpleNamespace(content=blocks, stop_reason=stop)

class FakeClaude:
    """First call: save lead details via tool; second call: plain reply."""
    def __init__(self): self.calls = 0; self.messages = self
    def create(self, **kw):
        self.calls += 1
        last = kw["messages"][-1]
        if last["role"] == "user" and isinstance(last["content"], str) and last["content"].startswith("[System"):
            return resp([block("text", text="Hi again! Still looking in Whitefield?")], "end_turn")
        if isinstance(last["content"], list):
            return resp([block("text", text="Great, 3BHK in Whitefield noted. Want a call with an agent?")], "end_turn")
        return resp([block("tool_use", id="t1", name="update_lead",
                           input={"intent": "buy", "location": "Whitefield", "budget": "1.2 cr",
                                  "bedrooms": "3", "timeline": "this month", "financing": "loan approved",
                                  "name": "Ravi", "email": "r@x.com"})], "tool_use")

@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(agent, "_client", FakeClaude())
    monkeypatch.setattr(whatsapp, "_post", lambda p: True)

def test_qualify_and_alert(monkeypatch):
    alerts = []
    monkeypatch.setattr(main.notify, "alert_agent", lambda lead, why: alerts.append(why))
    reply = main.handle_inbound("911", "Looking for a 3BHK in Whitefield, 1.2cr, this month")
    assert "Whitefield" in reply
    lead = db.get_or_create_lead("911")
    assert lead["location"] == "Whitefield" and lead["score"] >= config.HOT_SCORE
    assert lead["status"] == "hot" and alerts == ["Hot lead"]

def test_optout():
    main.handle_inbound("912", "STOP")
    assert db.get_or_create_lead("912")["status"] == "opted_out"
    assert followups.run_once(now=time.time() + 10**7) == 0

def test_followup_ladder():
    main.handle_inbound("913", "hi, 3BHK")
    lead = db.get_or_create_lead("913")
    t0 = lead["last_outbound_at"]
    assert followups.run_once(now=t0 + 3600) == 0            # too early
    assert followups.run_once(now=t0 + 3 * 3600) == 1        # 2h nudge, inside 24h window
    assert db.get_or_create_lead("913")["followups_sent"] == 1
