# Real Estate WhatsApp Follow-up Bot

Chats naturally with property leads on WhatsApp (Claude), qualifies them, follows up when they go quiet,
scores them, and alerts you when one is hot or wants a human.

## Run
```bash
cd realestate
pip install -r requirements.txt
cp .env.example .env   # fill in, then: set -a; source .env; set +a
uvicorn app.main:app --reload
```
- Dashboard: `/dashboard?token=$DASHBOARD_TOKEN`
- Try without WhatsApp: `curl -XPOST "localhost:8000/api/simulate?token=change-me" -H 'content-type: application/json' -d '{"phone":"911","text":"Looking for a 3BHK in Whitefield"}'`
- Tests: `pytest`

## Connect WhatsApp (Meta Cloud API)
1. Create a Meta app + WhatsApp Business number; copy the token and phone-number ID into `.env`.
2. Expose the server over HTTPS and set the webhook to `https://<host>/webhook` with your `WHATSAPP_VERIFY_TOKEN`; subscribe to `messages`.
3. Set `WHATSAPP_APP_SECRET` so webhook signatures are verified.
4. **24-hour rule:** free-form messages are only allowed within 24h of the lead's last message. Later follow-ups
   must use a pre-approved template: create one (one body variable = lead name) and set `WHATSAPP_FOLLOWUP_TEMPLATE`.
   Without it, out-of-window follow-ups are skipped.

## How it works
- `app/agent.py` – persona + tools (`update_lead`, `handoff_to_agent`); one question at a time, no invented listings.
- `app/scoring.py` – deterministic 0–100 score; `>= 70` marks the lead hot.
- `app/followups.py` – background loop; nudges after 2h, 20h, 72h, 168h of silence, then marks the lead cold. Lead replying resets the ladder.
- `app/notify.py` – one-time alert on hot/handoff via WhatsApp to `AGENT_PHONE` and/or a Slack-style `ALERT_WEBHOOK_URL`.
- "STOP" opts a lead out permanently until they message again.

## Before going live
Only message people who contacted you or opted in; keep the STOP handling; review local rules on messaging consent
(e.g. TRAI/DND in India, TCPA in the US). Replace SQLite and the in-process scheduler if you run multiple instances.

## Property catalogue (auto-learning scraper)
Approve sites, and the bot builds its own catalogue from them (`search_listings` tool).
```bash
export SCRAPER_USER_AGENT="YourAgencyBot/1.0 (you@example.com)"
curl -XPOST "localhost:8000/api/sources?token=$DASHBOARD_TOKEN" -H 'content-type: application/json' \
     -d '{"url":"https://your-agency.example/listings"}'      # adding a URL = approving that site
curl -XPOST "localhost:8000/api/scrape?token=$DASHBOARD_TOKEN"   # or: python -m app.sources
```
- **Auto-learns layouts:** if the page has schema.org JSON-LD it uses that; otherwise Claude proposes CSS selectors,
  they are test-run on the page (one retry with feedback), and the working set is stored per site. If a site later
  returns nothing, selectors are re-learned once.
- **Safe by design:** only approved sites, never leaves the approved domain, obeys robots.txt, rate-limited.
  One site failing never deactivates another site's listings; listings that vanish from a site are deactivated.
- `GET /api/sources` shows status, last count and errors per site; `DELETE /api/sources/{id}` removes one.
- Plain HTML only: JavaScript-rendered sites report an error (headless-browser support is a possible next step).
- Only approve sites you own or have permission to scrape. Run `/api/scrape` on a cron to keep it fresh.

## Keyless web crawling (no URL or API key needed for the catalogue)
```bash
python -m app.crawler "Whitefield Bangalore"     # or: POST /api/discover {"area": "..."}
```
- **Discovery:** reads `SEED_URLS` / `seeds.txt` if present; otherwise queries a search page *only if its robots.txt
  allows automated access* (many engines don't - then it tells you and finds nothing; add a few agency sites to `seeds.txt`).
- **Crawl:** same-domain BFS (listing-like links first, `CRAWL_MAX_PAGES`=60), robots.txt + delay respected.
  Extraction needs no LLM: JSON-LD if present, else a heuristic (detail page with one price + bedrooms/type + title).
- **Skipped on purpose:** big portals (99acres, MagicBricks, Zillow, Rightmove, ...) - their terms forbid scraping.
  Extend with `BLOCKED_DOMAINS`.
- Sources added without an `ANTHROPIC_API_KEY` (or where selector-learning fails) automatically use the crawler.
- The WhatsApp *chat* itself still needs Claude access (`ANTHROPIC_API_KEY`).
