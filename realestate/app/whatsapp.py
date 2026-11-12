import hashlib, hmac
import httpx2 as httpx
from . import config

API = "https://graph.facebook.com/v21.0"

def verify_signature(body: bytes, header: str) -> bool:
    if not config.WA_APP_SECRET:
        return True  # dev mode
    expected = "sha256=" + hmac.new(config.WA_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")

def _post(payload):
    if not (config.WA_TOKEN and config.WA_PHONE_ID):
        print("[whatsapp:dry-run]", payload)
        return True
    r = httpx.post(f"{API}/{config.WA_PHONE_ID}/messages", json=payload, timeout=15,
                   headers={"Authorization": f"Bearer {config.WA_TOKEN}"})
    if r.status_code >= 400:
        print("[whatsapp:error]", r.status_code, r.text)
    return r.status_code < 400

def send_text(to, body):
    return _post({"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}})

def send_template(to, name, lang, params):
    return _post({"messaging_product": "whatsapp", "to": to, "type": "template",
                  "template": {"name": name, "language": {"code": lang},
                               "components": [{"type": "body", "parameters":
                                              [{"type": "text", "text": p} for p in params]}]}})

def parse_inbound(data):
    """Yield (phone, text, profile_name) for each text message in a webhook payload."""
    for entry in data.get("entry", []):
        for ch in entry.get("changes", []):
            v = ch.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in v.get("contacts", [])}
            for m in v.get("messages", []):
                if m.get("type") == "text":
                    yield m["from"], m["text"]["body"], names.get(m["from"])
                else:
                    yield m["from"], "[sent a non-text message]", names.get(m["from"])
