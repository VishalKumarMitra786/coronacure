import httpx2 as httpx
from . import config, db, whatsapp

def alert_agent(lead: dict, why: str):
    text = (f"🔥 {why}: {lead.get('name') or 'Unknown'} ({lead['phone']}) | "
            f"{lead.get('intent') or '?'} | {lead.get('location') or '?'} | "
            f"budget {lead.get('budget') or '?'} | timeline {lead.get('timeline') or '?'} | "
            f"score {lead.get('score')}")
    print("[alert]", text)
    if config.AGENT_PHONE:
        whatsapp.send_text(config.AGENT_PHONE, text)
    if config.ALERT_WEBHOOK_URL:
        try:  # Slack/Discord/Teams-compatible
            httpx.post(config.ALERT_WEBHOOK_URL, json={"text": text, "content": text}, timeout=10)
        except Exception as e:
            print("[alert:webhook error]", e)

def check_alert(lead_id: int):
    """Alert once when a lead turns hot or is handed off."""
    lead = db.get_lead(lead_id)
    if lead["alerted"]:
        return
    if lead["status"] == "handoff":
        alert_agent(lead, f"Handoff requested ({lead.get('handoff_reason')})")
    elif lead["score"] >= config.HOT_SCORE:
        db.update_lead(lead_id, status="hot")
        alert_agent(lead, "Hot lead")
    else:
        return
    db.update_lead(lead_id, alerted=1)
