"""Conversation brain: Claude chats naturally and records lead details via tools."""
import anthropic
from . import config, db
from .scoring import score_lead

_client = None
def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client

TOOLS = [
    {
        "name": "update_lead",
        "description": "Save details the lead has shared. Call whenever you learn something new. "
                       "Only include fields the lead actually stated; never guess.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "intent": {"type": "string", "enum": ["buy", "rent", "sell", "invest", "unsure"]},
                "property_type": {"type": "string", "description": "apartment, villa, plot, commercial..."},
                "location": {"type": "string", "description": "Preferred areas/cities"},
                "budget": {"type": "string", "description": "As stated, e.g. '80-90 lakh'"},
                "bedrooms": {"type": "string"},
                "timeline": {"type": "string", "description": "When they want to move/buy, as stated"},
                "financing": {"type": "string", "description": "cash, loan pre-approved, need loan..."},
                "notes": {"type": "string", "description": "Other useful context (family size, school, pets...)"},
            },
        },
    },
    {
        "name": "search_listings",
        "description": "Search our property catalogue. Use once you know at least the area or budget. "
                       "Convert budgets to plain numbers (1.2 crore = 12000000, 80 lakh = 8000000).",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string"}, "max_price": {"type": "number"},
                "min_bedrooms": {"type": "integer"}, "property_type": {"type": "string"},
                "intent": {"type": "string", "enum": ["buy", "rent"]},
            },
        },
    },
    {
        "name": "handoff_to_agent",
        "description": "Hand the lead to a human agent. Use when they ask for a person, want to book a viewing "
                       "or call, are ready to make an offer, or are upset/confused beyond what you can handle.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]

def system_prompt(lead: dict) -> str:
    known = {k: lead[k] for k in db.FIELDS if lead.get(k)}
    return f"""You are {config.AGENT_NAME}, a friendly assistant for {config.AGENCY_NAME}, a real estate agency. \
You chat with people on WhatsApp who enquired about property.

Goals, in order: (1) be genuinely helpful and human, (2) learn what they need, (3) get them to a call or viewing with a human agent.

Style:
- Short WhatsApp-style messages: 1-3 sentences, plain text, no markdown, no bullet lists. At most one emoji, and only if it fits.
- Ask ONE question at a time. Acknowledge what they said before asking the next thing.
- Mirror their language (including Hinglish or other languages) and tone.
- Weave in qualifying info naturally: buy/rent, area, budget, bedrooms, timeline, financing, name. Don't interrogate; skip what they've already told you.
- Only suggest properties returned by search_listings (share at most 2-3, with the link); never invent listings, prices, availability or legal/financial advice. If asked something you can't know, say a human agent will confirm it and offer a call.
- If asked whether you are a bot, say you're {config.AGENCY_NAME}'s virtual assistant and can connect them with a human any time.
- Never pressure. If they say not now, be gracious and leave the door open.
- Save facts with update_lead as you learn them. Call handoff_to_agent when appropriate (then tell the lead an agent will reach out shortly and when).

Already known about this lead: {known or 'nothing yet'}."""

def _to_api_messages(hist):
    """Merge consecutive same-role turns and make sure we start with a user turn."""
    out = []
    for m in hist:
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n" + m["content"]
        else:
            out.append({"role": m["role"], "content": m["content"]})
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": "(lead enquired)"})
    return out

def _text(resp):
    return "".join(b.text for b in resp.content if b.type == "text").strip()

def _call(system, messages, tools=None):
    kw = dict(model=config.MODEL, max_tokens=1024, system=system, messages=messages,
              output_config={"effort": "medium"})
    if tools:
        kw["tools"] = tools
    return client().messages.create(**kw)

def apply_tool(lead_id: int, name: str, args: dict) -> str:
    if name == "update_lead":
        clean = {k: str(v) for k, v in args.items() if k in db.FIELDS and v}
        db.update_lead(lead_id, **clean)
        lead = db.get_lead(lead_id)
        db.update_lead(lead_id, score=score_lead(lead),
                       status="qualifying" if lead["status"] in ("new", "cold") else lead["status"])
        return "saved"
    if name == "search_listings":
        a = {k: v for k, v in args.items() if v}
        rows = db.search_listings(**a)
        if not rows:
            return "No matching listings. Say so honestly and offer to have an agent look for off-market options."
        return "\n".join(f"- {r['title']} | {r['price_text'] or 'price on request'} | {r['location'] or ''} | "
                         f"{r['bedrooms'] or '?'} bed | {r['url']}" for r in rows)
    if name == "handoff_to_agent":
        db.update_lead(lead_id, status="handoff", handoff_reason=args.get("reason", ""))
        return "handoff requested; tell the lead a human agent will contact them soon"
    return "unknown tool"

def reply_to(lead_id: int) -> str:
    """Generate the next reply. The inbound message must already be stored in history."""
    lead = db.get_lead(lead_id)
    messages = _to_api_messages(db.history(lead_id))
    for _ in range(5):  # tool loop
        resp = _call(system_prompt(db.get_lead(lead_id)), messages, TOOLS)
        if resp.stop_reason != "tool_use":
            return _text(resp) or "Sorry, could you say that again?"
        messages.append({"role": "assistant", "content": resp.content})
        results = [{"type": "tool_result", "tool_use_id": b.id,
                    "content": apply_tool(lead_id, b.name, b.input)}
                   for b in resp.content if b.type == "tool_use"]
        messages.append({"role": "user", "content": results})
    return "Let me get an agent to help you with this."

def followup_text(lead_id: int, step: int) -> str:
    lead = db.get_lead(lead_id)
    nudge = [
        "a light, friendly check-in picking up exactly where the chat stopped",
        "a helpful nudge adding one small piece of value (e.g. offer to shortlist options for their area/budget)",
        "a no-pressure check-in asking if their plans have changed",
        "a graceful last message: say you'll stop messaging, they can reply any time",
    ][min(step, 3)]
    messages = _to_api_messages(db.history(lead_id))
    messages.append({"role": "user", "content":
        f"[System: the lead has gone quiet. Write {nudge}. 1-2 short sentences, WhatsApp style, "
        f"reference something specific they said, no markdown. Output only the message.]"})
    return _text(_call(system_prompt(lead), messages))
