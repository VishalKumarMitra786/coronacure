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

LISTING_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings(
  id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, title TEXT, price_text TEXT, price_num REAL,
  location TEXT, bedrooms INTEGER, property_type TEXT, intent TEXT, image TEXT, description TEXT,
  active INTEGER DEFAULT 1, last_seen REAL);
"""

def upsert_listings(items, scrape_started):
    """Insert/update scraped listings; deactivate ones no longer on the site."""
    with conn() as c:
        c.executescript(LISTING_SCHEMA)
        for it in items:
            c.execute("""INSERT INTO listings(url,title,price_text,price_num,location,bedrooms,property_type,
                         intent,image,description,active,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,1,?)
                         ON CONFLICT(url) DO UPDATE SET title=excluded.title, price_text=excluded.price_text,
                         price_num=excluded.price_num, location=excluded.location, bedrooms=excluded.bedrooms,
                         property_type=excluded.property_type, intent=excluded.intent, image=excluded.image,
                         description=excluded.description, active=1, last_seen=excluded.last_seen""",
                      (it["url"], it.get("title"), it.get("price_text"), it.get("price_num"), it.get("location"),
                       it.get("bedrooms"), it.get("property_type"), it.get("intent"), it.get("image"),
                       it.get("description"), scrape_started))
        # only deactivate if the scrape found something (a failed scrape must not wipe the catalogue)
        if items:
            c.execute("UPDATE listings SET active=0 WHERE last_seen < ?", (scrape_started,))

def search_listings(location=None, max_price=None, min_bedrooms=None, property_type=None, intent=None, limit=3):
    q, args = "SELECT * FROM listings WHERE active=1", []
    if location:
        q += " AND (location LIKE ? OR title LIKE ?)"; args += [f"%{location}%"] * 2
    if max_price: q += " AND (price_num IS NULL OR price_num <= ?)"; args.append(max_price)
    if min_bedrooms: q += " AND (bedrooms IS NULL OR bedrooms >= ?)"; args.append(min_bedrooms)
    if property_type: q += " AND property_type LIKE ?"; args.append(f"%{property_type}%")
    if intent: q += " AND (intent IS NULL OR intent = ?)"; args.append(intent)
    q += " ORDER BY price_num DESC LIMIT ?"; args.append(limit)
    with conn() as c:
        c.executescript(LISTING_SCHEMA)
        return [dict(r) for r in c.execute(q, args)]
