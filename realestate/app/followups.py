import asyncio, time
from . import config, db, agent, whatsapp

WINDOW_S = 23.5 * 3600  # WhatsApp lets free-form messages only within 24h of the lead's last message

def run_once(now=None) -> int:
    """Send any due follow-ups. Returns how many were sent."""
    now = now or time.time()
    sent = 0
    for lead in db.due_candidates():
        n = lead["followups_sent"]
        if n >= len(config.FOLLOWUP_DELAYS_H):
            db.update_lead(lead["id"], status="cold")
            continue
        # Lead replied after our last message -> not waiting on them; skip.
        if (lead["last_inbound_at"] or 0) > lead["last_outbound_at"]:
            continue
        if now - lead["last_outbound_at"] < config.FOLLOWUP_DELAYS_H[n] * 3600:
            continue
        in_window = now - (lead["last_inbound_at"] or 0) < WINDOW_S
        if in_window:
            text = agent.followup_text(lead["id"], n)
            ok = whatsapp.send_text(lead["phone"], text)
        elif config.WA_TEMPLATE:
            text = f"[template:{config.WA_TEMPLATE}]"
            ok = whatsapp.send_template(lead["phone"], config.WA_TEMPLATE, config.WA_TEMPLATE_LANG,
                                        [lead.get("name") or "there"])
        else:
            continue  # outside window and no approved template configured
        if ok:
            db.add_message(lead["id"], "assistant", text)
            db.update_lead(lead["id"], followups_sent=n + 1, last_outbound_at=now,
                           status="cold" if n + 1 >= len(config.FOLLOWUP_DELAYS_H) else lead["status"])
            sent += 1
    return sent

async def loop(interval_s=300):
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception as e:
            print("[followups:error]", e)
        await asyncio.sleep(interval_s)
