import os

def env(name, default=""):
    return os.environ.get(name, default)

MODEL = env("CLAUDE_MODEL", "claude-sonnet-5-5")
AGENT_NAME = env("AGENT_NAME", "Priya")
AGENCY_NAME = env("AGENCY_NAME", "Your Realty")
DASHBOARD_TOKEN = env("DASHBOARD_TOKEN", "change-me")
DB_PATH = env("DB_PATH", "leads.db")

WA_TOKEN = env("WHATSAPP_TOKEN")
WA_PHONE_ID = env("WHATSAPP_PHONE_NUMBER_ID")
WA_VERIFY = env("WHATSAPP_VERIFY_TOKEN", "choose-a-string")
WA_APP_SECRET = env("WHATSAPP_APP_SECRET")
WA_TEMPLATE = env("WHATSAPP_FOLLOWUP_TEMPLATE")
WA_TEMPLATE_LANG = env("WHATSAPP_TEMPLATE_LANG", "en")

AGENT_PHONE = env("AGENT_PHONE")
ALERT_WEBHOOK_URL = env("ALERT_WEBHOOK_URL")

# Hours of silence before follow-up #1, #2, ... (measured from our last outbound message).
FOLLOWUP_DELAYS_H = [2, 20, 72, 168]
HOT_SCORE = 70
