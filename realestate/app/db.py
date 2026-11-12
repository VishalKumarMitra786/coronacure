import sqlite3, time
from . import config

FIELDS = ["name", "email", "intent", "property_type", "location", "budget",
          "bedrooms", "timeline", "financing", "notes"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY, phone TEXT UNIQUE NOT NULL,
  name TEXT, email TEXT, intent TEXT, property_type TEXT, location TEXT, budget TEXT,
  bedrooms TEXT, timeline TEXT, financing TEXT, notes TEXT,
  score INTEGER DEFAULT 0, status TEXT DEFAULT 'new', handoff_reason TEXT,
  followups_sent INTEGER DEFAULT 0, alerted INTEGER DEFAULT 0,
  last_inbound_at REAL, last_outbound_at REAL, created_at REAL);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL, role TEXT NOT NULL,
  content TEXT NOT NULL, created_at REAL);
"""

def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c

def get_or_create_lead(phone):
    with conn() as c:
        row = c.execute("SELECT * FROM leads WHERE phone=?", (phone,)).fetchone()
        if not row:
            c.execute("INSERT INTO leads(phone, created_at) VALUES(?,?)", (phone, time.time()))
            row = c.execute("SELECT * FROM leads WHERE phone=?", (phone,)).fetchone()
        return dict(row)

def get_lead(lead_id):
    with conn() as c:
        row = c.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        return dict(row) if row else None

def update_lead(lead_id, **kw):
    if not kw:
        return
    cols = ", ".join(f"{k}=?" for k in kw)
    with conn() as c:
        c.execute(f"UPDATE leads SET {cols} WHERE id=?", (*kw.values(), lead_id))

def add_message(lead_id, role, content):
    with conn() as c:
        c.execute("INSERT INTO messages(lead_id, role, content, created_at) VALUES(?,?,?,?)",
                  (lead_id, role, content, time.time()))

def history(lead_id, limit=40):
    with conn() as c:
        rows = c.execute("SELECT role, content FROM messages WHERE lead_id=? ORDER BY id DESC LIMIT ?",
                         (lead_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]

def all_leads():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM leads ORDER BY score DESC, last_inbound_at DESC")]

def due_candidates():
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM leads WHERE status NOT IN ('opted_out','cold','handoff') "
            "AND last_outbound_at IS NOT NULL")]
