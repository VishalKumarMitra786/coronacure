def score_lead(lead: dict) -> int:
    """Deterministic 0-100 score from what the lead has told us."""
    s = 0
    if lead.get("budget"): s += 15
    if lead.get("location"): s += 10
    if lead.get("intent"): s += 10
    if lead.get("property_type") or lead.get("bedrooms"): s += 5
    if lead.get("financing"): s += 10
    if lead.get("email"): s += 5
    if lead.get("name"): s += 5
    t = (lead.get("timeline") or "").lower()
    if any(w in t for w in ("now", "asap", "immediate", "this month", "1 month", "30 day", "2 week", "week")):
        s += 40
    elif any(w in t for w in ("month", "soon", "quarter")):
        s += 25
    elif t:
        s += 10
    return min(s, 100)
