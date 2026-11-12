import asyncio, hmac, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException, Header, Query, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from . import config, db, agent, whatsapp, notify, followups, scraper

STOP_WORDS = {"stop", "unsubscribe", "cancel", "opt out", "optout"}

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(followups.loop())
    yield
    task.cancel()

app = FastAPI(title="Real Estate Follow-up Bot", lifespan=lifespan)

def handle_inbound(phone: str, text: str, profile_name: str | None = None) -> str | None:
    """Core flow: store -> (opt-out?) -> Claude reply -> store -> alert. Returns the reply."""
    lead = db.get_or_create_lead(phone)
    now = time.time()
    updates = {"last_inbound_at": now}
    if profile_name and not lead.get("name"):
        updates["name"] = profile_name
    if lead["status"] in ("cold",):
        updates["status"] = "qualifying"
    updates["followups_sent"] = 0  # they re-engaged; restart the follow-up ladder
    db.update_lead(lead["id"], **updates)
    db.add_message(lead["id"], "user", text)

    if text.strip().lower() in STOP_WORDS:
        db.update_lead(lead["id"], status="opted_out")
        reply = "No problem, I won't message you again. Reply anytime if you change your mind."
    elif lead["status"] == "opted_out":
        db.update_lead(lead["id"], status="qualifying")
        reply = agent.reply_to(lead["id"])
    else:
        reply = agent.reply_to(lead["id"])

    db.add_message(lead["id"], "assistant", reply)
    db.update_lead(lead["id"], last_outbound_at=time.time())
    notify.check_alert(lead["id"])
    return reply

def process_and_send(phone, text, name):
    reply = handle_inbound(phone, text, name)
    if reply:
        whatsapp.send_text(phone, reply)

# ---- WhatsApp webhook ----
@app.get("/webhook")
def verify(mode: str = Query(None, alias="hub.mode"), token: str = Query(None, alias="hub.verify_token"),
           challenge: str = Query(None, alias="hub.challenge")):
    if mode == "subscribe" and token == config.WA_VERIFY:
        return Response(challenge)
    raise HTTPException(403)

@app.post("/webhook")
async def inbound(request: Request, bg: BackgroundTasks, x_hub_signature_256: str = Header(None)):
    body = await request.body()
    if not whatsapp.verify_signature(body, x_hub_signature_256):
        raise HTTPException(403, "bad signature")
    for phone, text, name in whatsapp.parse_inbound(await request.json()):
        bg.add_task(process_and_send, phone, text, name)  # reply after ACKing Meta fast
    return {"ok": True}

# ---- Dashboard / API (token protected) ----
def auth(token: str | None):
    if not token or not hmac.compare_digest(token, config.DASHBOARD_TOKEN):
        raise HTTPException(401, "bad token")

@app.get("/api/leads")
def leads(token: str = Query(None)):
    auth(token)
    return db.all_leads()

@app.get("/api/leads/{lead_id}/messages")
def lead_messages(lead_id: int, token: str = Query(None)):
    auth(token)
    return db.history(lead_id, limit=500)

class Sim(BaseModel):
    phone: str
    text: str

@app.post("/api/simulate")
def simulate(s: Sim, token: str = Query(None)):
    """Chat with the bot without WhatsApp (testing). Doesn't send anything out."""
    auth(token)
    return {"reply": handle_inbound(s.phone, s.text)}

@app.post("/api/followups/run")
def run_followups(token: str = Query(None)):
    auth(token)
    return {"sent": followups.run_once()}

@app.post("/api/scrape")
def run_scrape(token: str = Query(None)):
    auth(token)
    return {"listings": scraper.run()}

@app.get("/")
@app.get("/dashboard")
def dashboard():
    return FileResponse("static/dashboard.html")
