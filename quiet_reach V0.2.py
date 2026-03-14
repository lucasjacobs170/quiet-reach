# 🤫 QUIET REACH v1.2
import discord, tkinter as tk, sqlite3, asyncio, threading, random, os, json
from tkinter import ttk, scrolledtext, messagebox
import tkinter.font as tkfont
from datetime import datetime, date, timedelta
import requests
from datetime import time, timezone
from zoneinfo import ZoneInfo

BOT_TOKEN=''
OWNER_ID=434809771124719616
SERVER_INVITE='https://discord.gg/yAvVewhD3c'
DB_PATH='quiet_reach.db'
CONFIG_PATH='quiet_reach_config.json'
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
KB_PATH = "lucas_kb.txt"
# Keyword / engagement mode
KEYWORD_MODE_ENABLED = True

PROMO_TZ = ZoneInfo("America/Los_Angeles")  # PT (handles DST)
PROMO_DEFAULT_WINDOW_START = 18  # 6pm PT
PROMO_DEFAULT_WINDOW_END   = 22  # 10pm PT

# Public engagement pacing
PUBLIC_TOUCH_COOLDOWN_SECONDS = 60 * 30   # 30 minutes per user
NUDGE_AFTER_TOUCHES = 2                   # after N touches, start nudging opt-in

def load_kb() -> str:
    try:
        with open(KB_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

IMAGES_FILE = "images.txt"  # shared pool for DMs + promos

def load_shared_images() -> list[str]:
    try:
        if not os.path.exists(IMAGES_FILE):
            return []
        with open(IMAGES_FILE, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f.readlines() if ln.strip() and not ln.strip().startswith("#")]
    except Exception as e:
        log(f"⚠️ Failed reading {IMAGES_FILE}: {e}")
        return []

LUCAS_KB = load_kb()
ABOUT_LUCAS = f"""
You are Quiet Reach, Lucas Jacobs's assistant (not Lucas).

Identity rules:
- Never claim you are Lucas.
- If asked "are you Lucas?", say: "No—I'm Lucas's assistant."
- Speak in first-person as the assistant ("I can help you connect with Lucas"), not as Lucas.

Personality:
- Bubbly, upbeat, outdoorsy vibe (nature/outdoors metaphors are okay).
- Friendly and concise.

Safety/accuracy rules:
- Use only the KNOWLEDGE BASE facts when answering about Lucas.
- Do NOT invent links.
- If the user asks for a link, ONLY give this Discord invite: {SERVER_INVITE}
- If you don't know, say so and offer the Discord invite.
"""
DM_OPENERS = [
    "Hey, I represent a cammer and content creator named Lucas Jacobs — are you interested in seeing more? 😏",
    "Hi there! I'm reaching out on behalf of Lucas Jacobs, a content creator — would you be curious to check out what he's offering?",
    "Hey! I assist Lucas Jacobs, a cam content creator — thought you might be interested in seeing more. What do you think?",
    "Hi! I work with Lucas Jacobs, who creates exclusive cam content — are you interested in taking a look? 👀",
    "Hey there, I represent Lucas Jacobs, a creator with some really engaging content — interested in learning more?",
    "Hi! I'm here on behalf of Lucas Jacobs — he creates exclusive cam content and I thought you might vibe with it. Interested? 😊",
    "Hey! I reach out for Lucas Jacobs, a content creator — he's got some fun exclusive stuff going on. Curious?",
    "Hi there! I assist Lucas Jacobs, a cam creator with exclusive content — would you be interested in checking it out?",
    "Hey, I represent Lucas Jacobs, a content creator with exclusive cam material — thought you might be interested. Sound good?",
    "Hi! I'm messaging on behalf of Lucas Jacobs — he's a cam and content creator with exclusive offerings. Interested in seeing more? 🔥",
    "Hey! I work with Lucas Jacobs, a content creator — he's got exclusive cam content that might interest you. Worth a look?",
    "Hi there, I represent Lucas Jacobs, a creator with exclusive content — are you interested in checking out what he offers?"
]
YES_RESPONSES=[f"Yesss okay! 🎉 Here's an invite to Lucas's server, come hang: {SERVER_INVITE}",f"Ugh okay let's gooo 🙌 — drop into the server and we can chat more: {SERVER_INVITE}",f"Ahh okay I love that for you 😏 — here's the link, come through: {SERVER_INVITE}",f"Yay!! 🎉 Okay here's the server link — it's chill in there I promise 😊: {SERVER_INVITE}",f"Okay yes! 👏 Come hang with us — here's the invite: {SERVER_INVITE}",f"Let's gooo! 🔥 Here's where the fun is: {SERVER_INVITE}",f"Omg hi yes! 😊 Jump in here and we can chat more: {SERVER_INVITE}",f"Ayyy welcome! 🎊 Here's the link — see you in there: {SERVER_INVITE}"]
NO_RESPONSES=["Totally cool, no worries at all! 👌","All good! Sorry to bother 😊 have a great day!","No worries at all! Take care 💙","Totally understand! Have a good one 👋","All good, no hard feelings! 😊","Haha fair enough! Sorry to slide in 😅 take care!","No worries! Hope you have an amazing day 🌟","Understood! Sorry for the interruption 😊💙"]
OPT_OUT_RESPONSES=["Done! You've been opted out — I won't message you again. Take care! 💙","Of course! Removing you now — sorry for the bother 😊 take care!","Got it! You won't hear from me again. Have a great one 💙","Absolutely! All done — sorry if I bothered you 😊 take care!"]

# ============================================================
# 🔐 CONFIG / LOGIN (local, per-machine)
# ============================================================

def load_config():
    """Load config from CONFIG_PATH (if present)."""
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        log(f"⚠️ Config load failed: {e}")
        return {}

def save_config(cfg: dict):
    """Persist config to CONFIG_PATH."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        log(f"⚠️ Config save failed: {e}")

def apply_config(cfg: dict):
    """Apply config values into globals used by the bot."""
    global BOT_TOKEN
    BOT_TOKEN = (cfg.get("BOT_TOKEN") or "").strip()

def login_dialog(root):
    """
    Always prompt on startup.
    Prefills values from saved config, saves on Continue.
    """
    cfg = load_config()
    log("🔐 Login dialog opened (waiting for input)")
    win = tk.Toplevel(root)
    win.update_idletasks()
    win.lift()
    win.attributes("-topmost", True)
    win.after(250, lambda: win.attributes("-topmost", False))
    win.focus_force()
    win.title("Quiet Reach — Login")
    win.configure(bg="#1a1a2e")
    win.resizable(False, False)
    win.geometry("520x220+200+200")

    tk.Label(
        win, text="Bot Login / Setup",
        font=("Helvetica", 14, "bold"),
        bg="#1a1a2e", fg="white"
    ).pack(padx=16, pady=(14, 6))

    form = tk.Frame(win, bg="#1a1a2e")
    form.pack(padx=16, pady=8)

    tk.Label(form, text="Discord BOT_TOKEN", bg="#1a1a2e", fg="#cccccc").grid(row=0, column=0, sticky="w")
    token_var = tk.StringVar(value=cfg.get("BOT_TOKEN", ""))
    token_ent = tk.Entry(form, textvariable=token_var, width=48, show="•")
    token_ent.grid(row=1, column=0, pady=(2, 10))

    btns = tk.Frame(win, bg="#1a1a2e")
    btns.pack(padx=16, pady=(0, 14), fill="x")

    def on_continue():
        new_cfg = {"BOT_TOKEN": token_var.get().strip()}
        save_config(new_cfg)
        apply_config(new_cfg)
        win.destroy()

    def on_cancel():
        apply_config(cfg)
        win.destroy()

    tk.Button(
        btns, text="Continue", command=on_continue,
        bg="#27ae60", fg="white", relief="flat", padx=12, pady=6
    ).pack(side="right")

    tk.Button(
        btns, text="Cancel", command=on_cancel,
        bg="#444455", fg="white", relief="flat", padx=12, pady=6
    ).pack(side="right", padx=8)

    win.grab_set()
    token_ent.focus_set()
    root.wait_window(win)
def setup_database():
    c = sqlite3.connect(DB_PATH)
    k = c.cursor()

    k.execute(
        'CREATE TABLE IF NOT EXISTS users('
        'discord_id TEXT PRIMARY KEY,'
        'username TEXT,'
        'list_type TEXT DEFAULT "neutral",'
        'last_contacted TEXT,'
        'opt_out INTEGER DEFAULT 0)'
    )

    k.execute(
        'CREATE TABLE IF NOT EXISTS server_caps('
        'server_id TEXT,'
        'date TEXT,'
        'dm_count INTEGER DEFAULT 0,'
        'PRIMARY KEY(server_id,date))'
    )

    k.execute('CREATE TABLE IF NOT EXISTS keywords(word TEXT PRIMARY KEY, list_name TEXT)')

    k.execute(
        'CREATE TABLE IF NOT EXISTS dm_optins('
        'discord_id TEXT PRIMARY KEY,'
        'username TEXT,'
        'opted_in INTEGER DEFAULT 0,'
        'opted_in_at TEXT)'
    )

    k.execute(
        'CREATE TABLE IF NOT EXISTS public_touches('
        'discord_id TEXT PRIMARY KEY,'
        'username TEXT,'
        'touches INTEGER DEFAULT 0,'
        'last_touch TEXT)'
    )

    k.execute("SELECT COUNT(*) FROM keywords")
    if k.fetchone()[0] == 0:
        for w, l in [
            ('thirsty','trigger'),('live','trigger'),('of','trigger'),('cam','trigger'),
            ('preview','trigger'),('link','trigger'),
            ('yes','yes'),('yep','yes'),('sure','yes'),('yeah','yes'),('ok','yes'),
            ('interested','yes'),('tell me more','yes'),('lmk','yes'),('facts','yes'),
            ('no','no'),('nah','no'),('pass','no'),('no thanks','no'),('not interested','no'),
            ('stop','no'),('leave me alone','no'),('nope','no')
        ]:
            k.execute("INSERT INTO keywords VALUES(?,?)", (w, l))

    k.execute(
        'CREATE TABLE IF NOT EXISTS ambiguous('
        'id INTEGER PRIMARY KEY AUTOINCREMENT,'
        'discord_id TEXT,'
        'username TEXT,'
        'message TEXT,'
        'timestamp TEXT)'
    )

    k.execute(
        'CREATE TABLE IF NOT EXISTS promo_channels('
        'guild_id TEXT PRIMARY KEY,'
        'channel_id TEXT,'
        'enabled INTEGER DEFAULT 0,'
        'window_start_pt INTEGER DEFAULT 18,'
        'window_end_pt INTEGER DEFAULT 22,'
        'next_post_at_utc TEXT,'
        'last_post_at_utc TEXT)'
    )

    k.execute(
        'CREATE TABLE IF NOT EXISTS promo_history('
        'id INTEGER PRIMARY KEY AUTOINCREMENT,'
        'guild_id TEXT,'
        'channel_id TEXT,'
        'posted_at_utc TEXT,'
        'image_path TEXT,'
        'caption TEXT)'
    )
    c.commit()
    c.close()
    print("✅ Database ready!")

# ============================================================
# 📣 PROMO SCHEDULING HELPERS (PT window, stored as UTC)
# ============================================================

def _pt_now():
    return datetime.now(PROMO_TZ)

def _compute_next_post_at_utc(window_start_pt: int, window_end_pt: int) -> str:
    """
    Picks a random datetime inside today's (or next day's) PT window.
    Stores as ISO UTC string.
    Supports windows crossing midnight (e.g. 22 -> 2).
    """
    window_start_pt = int(window_start_pt) % 24
    window_end_pt   = int(window_end_pt) % 24

    now_pt = _pt_now()
    base_date = now_pt.date()

    start_dt = datetime.combine(base_date, time(window_start_pt, 0), tzinfo=PROMO_TZ)
    end_dt   = datetime.combine(base_date, time(window_end_pt, 0), tzinfo=PROMO_TZ)

    # window crosses midnight
    if window_end_pt <= window_start_pt:
        end_dt += timedelta(days=1)

    # if we're already past the window, schedule for next day's window
    if now_pt >= end_dt:
        start_dt += timedelta(days=1)
        end_dt   += timedelta(days=1)

    span = int((end_dt - start_dt).total_seconds())
    offset = random.randint(0, max(0, span - 1))
    scheduled_pt = start_dt + timedelta(seconds=offset)

    scheduled_utc = scheduled_pt.astimezone(timezone.utc)
    return scheduled_utc.isoformat()

def promo_set_channel(guild_id: int, channel_id: int):
    c = sqlite3.connect(DB_PATH); k = c.cursor()
    k.execute(
        "INSERT INTO promo_channels(guild_id, channel_id) VALUES(?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id",
        (str(guild_id), str(channel_id))
    )
    c.commit(); c.close()

def promo_set_window(guild_id: int, start_pt: int, end_pt: int):
    next_utc = _compute_next_post_at_utc(start_pt, end_pt)
    c = sqlite3.connect(DB_PATH); k = c.cursor()
    k.execute(
        "INSERT INTO promo_channels(guild_id, window_start_pt, window_end_pt, next_post_at_utc) "
        "VALUES(?,?,?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET window_start_pt=excluded.window_start_pt, "
        "window_end_pt=excluded.window_end_pt, next_post_at_utc=excluded.next_post_at_utc",
        (str(guild_id), int(start_pt), int(end_pt), next_utc)
    )
    c.commit(); c.close()

def promo_set_enabled(guild_id: int, enabled: bool):
    c = sqlite3.connect(DB_PATH); k = c.cursor()
    k.execute(
        "INSERT INTO promo_channels(guild_id, enabled) VALUES(?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled",
        (str(guild_id), 1 if enabled else 0)
    )
    c.commit(); c.close()

def promo_get_enabled_rows():
    c = sqlite3.connect(DB_PATH); k = c.cursor()
    k.execute(
        "SELECT guild_id, channel_id, window_start_pt, window_end_pt, next_post_at_utc "
        "FROM promo_channels WHERE enabled=1 AND channel_id IS NOT NULL"
    )
    rows = k.fetchall()
    c.close()
    return rows

def promo_update_next(guild_id: int, start_pt: int, end_pt: int):
    next_utc = _compute_next_post_at_utc(start_pt, end_pt)
    c = sqlite3.connect(DB_PATH); k = c.cursor()
    k.execute(
        "UPDATE promo_channels SET next_post_at_utc=? WHERE guild_id=?",
        (next_utc, str(guild_id))
    )
    c.commit(); c.close()

def promo_record_history(guild_id: int, channel_id: int, image_path: str, caption: str):
    now_utc = datetime.now(timezone.utc).isoformat()
    c = sqlite3.connect(DB_PATH); k = c.cursor()
    k.execute(
        "INSERT INTO promo_history(guild_id, channel_id, posted_at_utc, image_path, caption) "
        "VALUES(?,?,?,?,?)",
        (str(guild_id), str(channel_id), now_utc, image_path, caption)
    )
    k.execute(
        "UPDATE promo_channels SET last_post_at_utc=? WHERE guild_id=?",
        (now_utc, str(guild_id))
    )
    c.commit(); c.close()

def get_keywords(ln):
    c=sqlite3.connect(DB_PATH);k=c.cursor();k.execute("SELECT word FROM keywords WHERE list_name=?",(ln,));w=[r[0].lower().strip()for r in k.fetchall()];c.close();return w

def get_user(did):
    c=sqlite3.connect(DB_PATH);k=c.cursor();k.execute("SELECT*FROM users WHERE discord_id=?",(str(did),));u=k.fetchone();c.close();return u

def upsert_user(did, un, lt, opt_out=0):
    c = sqlite3.connect(DB_PATH)
    k = c.cursor()
    k.execute(
        'INSERT INTO users VALUES(?,?,?,?,?) '
        'ON CONFLICT(discord_id) DO UPDATE SET '
        'list_type=excluded.list_type, '
        'last_contacted=excluded.last_contacted, '
        'opt_out=excluded.opt_out',
        (str(did), un, lt, str(datetime.now()), opt_out)
    )
    c.commit()
    c.close()

def check_server_cap(sid):
    c=sqlite3.connect(DB_PATH);k=c.cursor();k.execute("SELECT dm_count FROM server_caps WHERE server_id=? AND date=?",(str(sid),str(date.today())));r=k.fetchone();c.close();return(r[0]if r else 0)>=5

def increment_server_cap(sid):
    c=sqlite3.connect(DB_PATH);k=c.cursor();k.execute('INSERT INTO server_caps VALUES(?,?,1)ON CONFLICT(server_id,date)DO UPDATE SET dm_count=dm_count+1',(str(sid),str(date.today())));c.commit();c.close()

def user_on_cooldown(did):
    u=get_user(did)
    if not u:return False
    if not u[3]:return False
    return(datetime.now()-datetime.fromisoformat(u[3])).days<7

def add_ambiguous(did,un,msg):
    c=sqlite3.connect(DB_PATH);k=c.cursor();k.execute("INSERT INTO ambiguous(discord_id,username,message,timestamp)VALUES(?,?,?,?)",(str(did),un,msg,str(datetime.now())));c.commit();c.close()

def get_users_by_list(lt):
    c=sqlite3.connect(DB_PATH);k=c.cursor();k.execute("SELECT discord_id,username,last_contacted FROM users WHERE list_type=? AND opt_out=0",(lt,));u=k.fetchall();c.close();return u

def get_ambiguous_entries():
    c=sqlite3.connect(DB_PATH);k=c.cursor();k.execute("SELECT id,discord_id,username,message,timestamp FROM ambiguous");e=k.fetchall();c.close();return e

def delete_ambiguous(eid):
    c=sqlite3.connect(DB_PATH);k=c.cursor();k.execute("DELETE FROM ambiguous WHERE id=?",(eid,));c.commit();c.close()

def get_stats():
    c=sqlite3.connect(DB_PATH);k=c.cursor()
    k.execute("SELECT COUNT(*)FROM users WHERE list_type='warm'");w=k.fetchone()[0]
    k.execute("SELECT COUNT(*)FROM users WHERE list_type='cold'");co=k.fetchone()[0]
    k.execute("SELECT COUNT(*)FROM users WHERE list_type='neutral'");n=k.fetchone()[0]
    k.execute("SELECT SUM(dm_count)FROM server_caps");t=k.fetchone()[0]or 0
    k.execute("SELECT COUNT(*)FROM ambiguous");p=k.fetchone()[0];c.close();return w,co,n,t,p
def get_opt_in(did: int) -> bool:
    c = sqlite3.connect(DB_PATH)
    k = c.cursor()
    k.execute("SELECT opted_in FROM dm_optins WHERE discord_id=?", (str(did),))
    row = k.fetchone()
    c.close()
    return bool(row and row[0] == 1)

def set_opt_in(did: int, username: str, opted_in: int = 1):
    c = sqlite3.connect(DB_PATH)
    k = c.cursor()
    k.execute(
        "INSERT INTO dm_optins(discord_id, username, opted_in, opted_in_at) "
        "VALUES(?,?,?,?) "
        "ON CONFLICT(discord_id) DO UPDATE SET "
        "username=excluded.username, opted_in=excluded.opted_in, opted_in_at=excluded.opted_in_at",
        (str(did), username, int(opted_in), str(datetime.now()))
    )
    c.commit()
    c.close()

def get_touches(did: int) -> int:
    c = sqlite3.connect(DB_PATH)
    k = c.cursor()
    k.execute("SELECT touches FROM public_touches WHERE discord_id=?", (str(did),))
    row = k.fetchone()
    c.close()
    return int(row[0]) if row else 0

def can_public_touch(did: int) -> bool:
    c = sqlite3.connect(DB_PATH)
    k = c.cursor()
    k.execute("SELECT last_touch FROM public_touches WHERE discord_id=?", (str(did),))
    row = k.fetchone()
    c.close()
    if not row or not row[0]:
        return True
    try:
        last = datetime.fromisoformat(row[0])
    except Exception:
        return True
    return (datetime.now() - last).total_seconds() >= PUBLIC_TOUCH_COOLDOWN_SECONDS

def record_touch(did: int, username: str) -> int:
    """Increment touch counter; return new touches count."""
    now = datetime.now().isoformat()

    c = sqlite3.connect(DB_PATH)
    k = c.cursor()

    # Fetch current count
    k.execute(
        "SELECT touches FROM public_touches WHERE discord_id=?",
        (str(did),)
    )
    row = k.fetchone()

    if row:
        touches = int(row[0]) + 1
        k.execute(
            "UPDATE public_touches SET username=?, touches=?, last_touch=? WHERE discord_id=?",
            (username, touches, now, str(did))
        )
    else:
        touches = 1
        k.execute(
            "INSERT INTO public_touches(discord_id, username, touches, last_touch) VALUES(?,?,?,?)",
            (str(did), username, touches, now)
        )

    c.commit()
    c.close()
    return touches

intents=discord.Intents.default();intents.message_content=True;intents.members=True;intents.presences=True
client=discord.Client(intents=intents);ui_log=None
# ============================================================
# 🤖 OLLAMA AI SETUP
# ============================================================
def ollama_generate(prompt: str) -> str:
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=90
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("response") or "").strip()
    except Exception as e:
        print(f"❌ Ollama error: {e}")
        return ""

import re

def has_keyword(msg: str, kw: str) -> bool:
    msg = (msg or "").lower()
    kw = (kw or "").lower().strip()
    if not kw:
        return False

    # For multi-word phrases, allow substring match
    if " " in kw:
        return kw in msg

    # For single words, require word boundaries (prevents "no" matching "know")
    return re.search(rf"\b{re.escape(kw)}\b", msg) is not None
    
async def classify_reply_with_ai(user_message: str) -> str:
    msg = (user_message or "").strip().lower()

    # If it's clearly a question / info request, do NOT classify as yes/no
    if looks_like_question(msg) or "about lucas" in msg or "who is lucas" in msg:
        return "other"

    # quick keyword fallback first (no model call)
    if any(has_keyword(msg, w) for w in get_keywords("yes")):
        return "yes"
    if any(has_keyword(msg, w) for w in get_keywords("no")):
        return "no"

    prompt = (
        "Classify this message as YES or NO if it is clearly accepting/declining an offer. "
        "If it is a question or anything else, return OTHER. "
        "Reply with exactly one word: YES, NO, or OTHER.\n\n"
        f"Message: {user_message}"
    )
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: ollama_generate(prompt))
    result = (result or "").strip().lower()

    if result.startswith("yes"):
        return "yes"
    if result.startswith("no"):
        return "no"
    return "other"

async def generate_ai_reply(user_message: str) -> str:
    try:
        prompt = f"""{ABOUT_LUCAS}

KNOWLEDGE BASE:
{LUCAS_KB}

User message:
\"\"\"{user_message}\"\"\"

Write the best possible reply now (friendly, concise).
"""
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, lambda: ollama_generate(prompt))
        return (reply or "").strip()
    except Exception as e:
        log(f"❌ Local model reply error: {e}")
        return ""
def log(m):
    print(m)
    if ui_log:ui_log(m)

# ============================================================
# 📣 PROMO AUTOPOST (daily PT window -> stored UTC)
# ============================================================

PROMO_SEEDS_FILE = "promo_seeds.txt"   # optional; one seed per line
PROMO_MAX_CHARS = 240

promo_task = None

def _parse_iso_utc(s: str):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        # if missing tzinfo, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def _utc_now():
    return datetime.now(timezone.utc)

def _load_promo_seeds() -> list[str]:
    try:
        if not os.path.exists(PROMO_SEEDS_FILE):
            return []
        with open(PROMO_SEEDS_FILE, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f.readlines() if ln.strip() and not ln.strip().startswith("#")]
        return lines
    except Exception as e:
        log(f"⚠️ Failed reading {PROMO_SEEDS_FILE}: {e}")
        return []

def _sanitize_caption(text: str) -> str:
    t = (text or "").strip()
    # prevent pings / mass mentions
    t = t.replace("@everyone", "everyone").replace("@here", "here")
    # hard cap
    if len(t) > PROMO_MAX_CHARS:
        t = t[:PROMO_MAX_CHARS - 1].rstrip() + "…"
    return t

def promo_get_config_row(guild_id: int):
    c = sqlite3.connect(DB_PATH); k = c.cursor()
    k.execute(
        "SELECT guild_id, channel_id, enabled, window_start_pt, window_end_pt, next_post_at_utc, last_post_at_utc "
        "FROM promo_channels WHERE guild_id=?",
        (str(guild_id),)
    )
    row = k.fetchone()
    c.close()
    return row

def promo_set_next_post_at(guild_id: int, next_post_at_utc_iso: str):
    c = sqlite3.connect(DB_PATH); k = c.cursor()
    k.execute(
        "UPDATE promo_channels SET next_post_at_utc=? WHERE guild_id=?",
        (next_post_at_utc_iso, str(guild_id))
    )
    c.commit(); c.close()

async def generate_promo_caption(theme: str, seed: str) -> str:
    """
    Keeps captions non-explicit (Discord-safe) while still flirty.
    """
    cta = f"Join the server: {SERVER_INVITE}"
    seed = (seed or "").strip()

    prompt = f"""
You write short promotional captions for an adult creator's Discord server.
Tone: playful, confident, outdoorsy vibe, attention-grabbing.
Rules:
- Non-explicit only: do NOT describe sex acts or graphic anatomy.
- No minors. No coercion. No threats. No harassment.
- No @everyone / @here.
- 1-2 short lines max, plus a clear call-to-action.
- Keep under {PROMO_MAX_CHARS} characters total.

Theme: {theme}
Seed idea (optional): {seed}

Return ONLY the caption text.
Include this CTA (exact link): {SERVER_INVITE}
"""

    loop = asyncio.get_event_loop()
    out = await loop.run_in_executor(None, lambda: ollama_generate(prompt))
    out = _sanitize_caption(out)

    if not out:
        # fallback if model fails
        base = seed if seed else "New drop today—come say hi."
        return _sanitize_caption(f"{base}\n{cta}")

    # ensure CTA exists
    if SERVER_INVITE not in out:
        out = _sanitize_caption(out.rstrip() + f"\n{cta}")

    return out

async def _post_promo(guild_id: int, channel_id: int, caption: str, image_path: str) -> bool:
    guild = client.get_guild(int(guild_id)) if guild_id else None
    if not guild:
        log(f"⚠️ Promo: guild not found/cached: {guild_id}")
        return False

    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if not channel:
        log(f"⚠️ Promo: channel not found/cached: {channel_id} in {guild.name}")
        return False

    # NSFW gate
    try:
        if hasattr(channel, "is_nsfw") and (not channel.is_nsfw()):
            log(f"🚫 Promo blocked (channel not NSFW): #{getattr(channel, 'name', channel_id)} in {guild.name}")
            return False
    except Exception:
        pass

    # Permission gate
    me = guild.get_member(client.user.id) if (client.user and guild) else None
    if me:
        perms = channel.permissions_for(me)
        if not perms.send_messages:
            log(f"🚫 Promo blocked (no send_messages): {guild.name} #{getattr(channel,'name','?')}")
            return False
        if image_path and (not perms.attach_files):
            log(f"🚫 Promo blocked (no attach_files): {guild.name} #{getattr(channel,'name','?')}")
            return False

    try:
        if image_path:
            with open(image_path, "rb") as f:
                await channel.send(
                    content=caption,
                    file=discord.File(f, filename=os.path.basename(image_path))
                )
        else:
            await channel.send(content=caption)

        promo_record_history(guild_id, channel_id, image_path or "", caption)
        log(f"📣 Promo posted in {guild.name} #{getattr(channel,'name','?')}")
        return True

    except FileNotFoundError:
        log(f"⚠️ Promo image missing: {image_path} (posting text only)")
        try:
            await channel.send(content=caption)
            promo_record_history(guild_id, channel_id, "", caption)
            return True
        except Exception as e:
            log(f"❌ Promo failed (text-only fallback): {e}")
            return False

    except discord.Forbidden:
        log(f"❌ Promo forbidden in {guild.name} #{getattr(channel,'name','?')}")
        return False
    except Exception as e:
        log(f"❌ Promo post error: {e}")
        return False

async def promo_loop():
    log("📣 Promo loop running.")
    themes = [
        "fresh drop",
        "tease + mystery",
        "outdoorsy flirty",
        "late-night vibes",
        "friendly invite",
    ]

    while True:
        try:
            rows = promo_get_enabled_rows()
            now = _utc_now()

            seeds = _load_promo_seeds()
            image_list = load_shared_images()

            for (gid, cid, start_pt, end_pt, next_iso) in rows:
                next_dt = _parse_iso_utc(next_iso)

                # If missing next schedule, create one
                if not next_dt:
                    promo_update_next(int(gid), int(start_pt), int(end_pt))
                    continue

                if now < next_dt:
                    continue

                # Pick content
                theme = random.choice(themes)
                seed = random.choice(seeds) if seeds else ""
                img = random.choice(image_list) if image_list else ""

                caption = await generate_promo_caption(theme, seed)

                ok = await _post_promo(int(gid), int(cid), caption, img)

                # Schedule the next one regardless (prevents rapid retry spam)
                promo_update_next(int(gid), int(start_pt), int(end_pt))

                # small delay between guild posts (rate-limit friendly)
                await asyncio.sleep(2)

        except Exception as e:
            log(f"❌ Promo loop error: {e}")

        await asyncio.sleep(30)

@client.event
async def on_ready():
    global promo_task
    log(f"✅ Logged in as {client.user} (ID: {client.user.id})")

    # Start promo loop once
    if promo_task is None or promo_task.done():
        promo_task = asyncio.create_task(promo_loop())
        log("📣 Promo loop started.")

async def handle_dm_reply(message):
    user_id = message.author.id
    username = str(message.author)
    content = (message.content or "").strip()
    content_lower = content.lower().strip()

    # Opt-out
    if content_lower in ["stop", "remove", "opt out", "optout"]:
        upsert_user(user_id, username, "neutral", opt_out=1)
        await message.channel.send(random.choice(OPT_OUT_RESPONSES))
        log(f"🛑 {username} opted out")
        return

    # If they just want the link, give it (and stop)
    if content_lower in ["link", "server", "invite"]:
        await message.channel.send(f"Here you go: {SERVER_INVITE}")
        return

    # If they are asking for info about Lucas, answer with AI (KB-grounded)
    if looks_like_question(content) or ("lucas" in content_lower):
        reply = await generate_ai_reply(content)
        if not reply:
            reply = "I don’t have that detail yet. If you want, ask me a more specific question about Lucas."
        reply += "\n\nIf you want to join the server, say `link`."
        await message.channel.send(reply)
        return

    # Otherwise try classification for YES/NO
    ai_result = await classify_reply_with_ai(content)

    if ai_result == "yes":
        upsert_user(user_id, username, "warm")
        await message.channel.send(random.choice(YES_RESPONSES))
        log(f"🔥 {username} added to WARM list")
        return

    if ai_result == "no":
        upsert_user(user_id, username, "cold")
        await message.channel.send(random.choice(NO_RESPONSES))
        log(f"❄️ {username} added to COLD list")
        return

    # Fallback: conversational AI
    reply = await generate_ai_reply(content)
    if not reply:
        reply = "Got you. What do you want to know about Lucas?"
    reply += "\n\nIf you want to join the server, say `link`."
    await message.channel.send(reply)
    log(f"🤖 AI replied to {username}")
# --- Anti-spam pacing (channel-level) ---
CHANNEL_REPLY_COOLDOWN_SECONDS = 90  # 1.5 minutes per channel
_last_channel_reply = {}            # channel_id -> datetime

def can_channel_reply(channel_id: int) -> bool:
    last = _last_channel_reply.get(channel_id)
    if not last:
        return True
    return (datetime.now() - last).total_seconds() >= CHANNEL_REPLY_COOLDOWN_SECONDS

def mark_channel_replied(channel_id: int):
    _last_channel_reply[channel_id] = datetime.now()

# --- Lightweight conversation follow-ups (per user, per channel) ---
FOLLOWUP_WINDOW_SECONDS = 120         # 2 minutes to keep chatting
FOLLOWUP_MAX_TURNS = 3               # up to 3 back-and-forth replies
FOLLOWUP_TURN_COOLDOWN_SECONDS = 8   # minimum spacing between bot replies to same user

_followups = {}  # (channel_id, user_id) -> {"expires": dt, "remaining": int, "last_turn": dt|None}


def start_followup(channel_id: int, user_id: int):
    _followups[(channel_id, user_id)] = {
        "expires": datetime.now() + timedelta(seconds=FOLLOWUP_WINDOW_SECONDS),
        "remaining": FOLLOWUP_MAX_TURNS,
        "last_turn": None,
    }


def can_followup(channel_id: int, user_id: int) -> bool:
    key = (channel_id, user_id)
    s = _followups.get(key)
    if not s:
        return False

    if datetime.now() > s["expires"] or s["remaining"] <= 0:
        _followups.pop(key, None)
        return False

    last_turn = s["last_turn"]
    if last_turn and (datetime.now() - last_turn).total_seconds() < FOLLOWUP_TURN_COOLDOWN_SECONDS:
        return False

    return True


def consume_followup(channel_id: int, user_id: int):
    key = (channel_id, user_id)
    s = _followups.get(key)
    if not s:
        return
    s["remaining"] -= 1
    s["last_turn"] = datetime.now()
    # extend the window a bit as long as they're actively chatting
    s["expires"] = datetime.now() + timedelta(seconds=FOLLOWUP_WINDOW_SECONDS)


# --- Organic DM consent window (per user, per channel) ---
DM_OFFER_WINDOW_SECONDS = 120  # 2 minutes to accept DM offer
_dm_offers = {}  # (channel_id, user_id) -> expires_at (datetime)


def start_dm_offer(channel_id: int, user_id: int):
    _dm_offers[(channel_id, user_id)] = datetime.now() + timedelta(seconds=DM_OFFER_WINDOW_SECONDS)


def dm_offer_active(channel_id: int, user_id: int) -> bool:
    exp = _dm_offers.get((channel_id, user_id))
    if not exp:
        return False
    if datetime.now() > exp:
        _dm_offers.pop((channel_id, user_id), None)
        return False
    return True


def clear_dm_offer(channel_id: int, user_id: int):
    _dm_offers.pop((channel_id, user_id), None)


def is_affirmative(text: str) -> bool:
    msg = (text or "").strip().lower()
    return any(has_keyword(msg, w) for w in get_keywords("yes"))


def is_negative(text: str) -> bool:
    msg = (text or "").strip().lower()
    return any(has_keyword(msg, w) for w in get_keywords("no"))
    
async def is_reply_to_bot(message) -> bool:
    """
    True only if the user is replying to a message authored by this bot.
    Prevents the bot from responding to every random reply-thread in the channel.
    """
    if not message.reference or not message.reference.message_id:
        return False

    # If Discord already resolved the referenced message, use it
    resolved = message.reference.resolved
    try:
        if resolved and getattr(resolved, "author", None) and client.user:
            return resolved.author.id == client.user.id
    except Exception:
        pass

    # Otherwise fetch the referenced message
    try:
        if client.user:
            replied_msg = await message.channel.fetch_message(message.reference.message_id)
            return replied_msg.author.id == client.user.id
    except Exception:
        return False

    return False
def looks_like_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if "?" in t:
        return True
    starters = ("who", "what", "when", "where", "why", "how", "can", "do", "is", "are", "does")
    return t.startswith(starters)

PUBLIC_SMALLTALK = [
    "Ooo good question.",
    "Love that you asked.",
    "Okay wait—yes.",
    "Real quick:",
    "Alright, trail-guide mode on:",
]

def optin_footer() -> str:
    return " If you want, I can DM details — just reply “yes”."

async def build_public_response(user_text: str, touches: int) -> str:
    """
    Returns a public reply that feels conversational:
    - If they asked a question -> answer it using generate_ai_reply()
    - Otherwise -> light engagement + invite a question
    """
    msg = (user_text or "").strip()

    # If it's a question (or early touches), answer with AI using KB
    if looks_like_question(msg):
        ai = await generate_ai_reply(msg)
        if ai:
            return f"{ai}{optin_footer()}"
        return f"I'm not 100% sure on that, but I can try to help here.{optin_footer()}"

    # Not a question: make it more organic + varied by touch count
    prefix = random.choice(PUBLIC_SMALLTALK)

    if touches <= 1:
        return (
            f"{prefix} I’m Lucas’s assistant. What were you looking for—"
            f"preview, schedule, or the server link?{optin_footer()}"
        )
    elif touches < NUDGE_AFTER_TOUCHES:
        return (
            f"{prefix} Tell me what you’re into / what you’re looking for and I’ll point you right."
            f"{optin_footer()}"
        )
    else:
        return (
            f"{prefix} Want me to keep it here in chat, or DM you details?"
            f" (Reply 'yes' and I’ll DM you.)"
        )
@client.event
async def on_message(message):
    # Ignore self
    if message.author == client.user:
        return

    # DMs: handle separately (no guild)
    if isinstance(message.channel, discord.DMChannel):
        await handle_dm_reply(message)
        return

    # In-server opt-in / opt-out commands
    raw = (message.content or "").strip().lower()

# ==========================
    # 📣 PROMO OWNER COMMANDS
    # ==========================
    if raw.startswith("!promo") or raw in ["!setpromochannel", "!promoon", "!promooff", "!promostatus"]:

        # Owner-only (change this if you want admins too)
        if message.author.id != OWNER_ID:
            return

        if raw == "!setpromochannel":
            promo_set_channel(message.guild.id, message.channel.id)
            # ensure a default window + next schedule exists
            promo_set_window(message.guild.id, PROMO_DEFAULT_WINDOW_START, PROMO_DEFAULT_WINDOW_END)
            await message.reply("✅ Promo channel set for this server.", mention_author=False)
            return

        if raw.startswith("!promowindow"):
            # usage: !promowindow 18 22  (PT hours)
            parts = (message.content or "").strip().split()
            if len(parts) != 3:
                await message.reply("Usage: `!promowindow <start_hour_pt> <end_hour_pt>` (0-23)", mention_author=False)
                return
            try:
                start_pt = int(parts[1]); end_pt = int(parts[2])
                promo_set_window(message.guild.id, start_pt, end_pt)
                await message.reply(f"✅ Promo window set: {start_pt}:00–{end_pt}:00 PT (next scheduled randomly inside window).", mention_author=False)
            except Exception as e:
                await message.reply(f"⚠️ Failed setting window: {e}", mention_author=False)
            return

        if raw == "!promoon":
            promo_set_enabled(message.guild.id, True)
            row = promo_get_config_row(message.guild.id)
            # if next not scheduled yet, schedule now using saved window
            if row:
                _, _, _, start_pt, end_pt, next_iso, _ = row
                if not next_iso:
                    promo_update_next(message.guild.id, int(start_pt), int(end_pt))
            await message.reply("✅ Promo enabled for this server.", mention_author=False)
            return

        if raw == "!promooff":
            promo_set_enabled(message.guild.id, False)
            await message.reply("🛑 Promo disabled for this server.", mention_author=False)
            return

        if raw == "!promostatus":
            row = promo_get_config_row(message.guild.id)
            if not row:
                await message.reply("No promo config yet. Run `!setpromochannel` first.", mention_author=False)
                return

            _, channel_id, enabled, start_pt, end_pt, next_iso, last_iso = row
            next_dt = _parse_iso_utc(next_iso)
            last_dt = _parse_iso_utc(last_iso)

            def fmt_pt(dt):
                if not dt: return "—"
                return dt.astimezone(PROMO_TZ).strftime("%Y-%m-%d %I:%M %p PT")

            await message.reply(
                "📣 **Promo Status**\n"
                f"- Enabled: `{bool(enabled)}`\n"
                f"- Channel ID: `{channel_id}`\n"
                f"- Window (PT): `{start_pt}:00`–`{end_pt}:00`\n"
                f"- Next: `{fmt_pt(next_dt)}`\n"
                f"- Last: `{fmt_pt(last_dt)}`",
                mention_author=False
            )
            return
    
    if raw in ["!optin", "!opt-in", "!dmme", "!dm me"]:
        set_opt_in(message.author.id, str(message.author), 1)
        await message.reply("Got it — you’re opted in. I’ll DM you.", mention_author=False)
        await send_outreach_dm(message.author, message.guild.id)
        return

    if raw in ["!optout", "!opt-out", "!nodm", "!no dm"]:
        set_opt_in(message.author.id, str(message.author), 0)
        await message.reply("Done — no DMs from me.", mention_author=False)
        return
    # If the bot recently offered to DM this user, accept natural "yes" as opt-in
    if dm_offer_active(message.channel.id, message.author.id):
        if is_affirmative(message.content):
            clear_dm_offer(message.channel.id, message.author.id)
            set_opt_in(message.author.id, str(message.author), 1)
            await message.reply("Perfect — I’ll DM you details.", mention_author=False)
            await send_outreach_dm(message.author, message.guild.id)
            return

        if is_negative(message.content):
            clear_dm_offer(message.channel.id, message.author.id)
            await message.reply("No worries — we can keep it here in chat.", mention_author=False)
            return
    
    # If we recently engaged this user in this channel, allow a short multi-turn convo
    if can_followup(message.channel.id, message.author.id):
        consume_followup(message.channel.id, message.author.id)

        reply = await generate_ai_reply(message.content)
        if not reply:
            reply = "Tell me what you’re looking for and I’ll point you the right way."

        await message.reply(reply, mention_author=False)
        # Don't mark_channel_replied here; follow-ups are already capped per-user
        return

    # If they reply to the bot or mention it, answer publicly (no DM needed)
    is_mention = bool(client.user and client.user.mentioned_in(message))
    is_reply = await is_reply_to_bot(message)

    if is_mention or is_reply:
        # If it's not a direct mention, respect channel cooldown
        if (not is_mention) and (not can_public_touch(message.author.id)):
            return

        touches = record_touch(message.author.id, str(message.author))
        reply_text = await build_public_response(message.content, touches)
        await message.reply(reply_text, mention_author=False)
        mark_channel_replied(message.channel.id)
        start_followup(message.channel.id, message.author.id)
        start_dm_offer(message.channel.id, message.author.id)
        return

    # If keyword mode is disabled, stop here (still allows opt-in/out above)
    if not KEYWORD_MODE_ENABLED:
        return

    # Keyword trigger scan (server-safe until opt-in)
    content = (message.content or "").lower()
    tw = get_keywords("trigger")

    if any(w in content for w in tw):
        log(f"🔍 Keyword match from {message.author} in {message.guild.name}")

        if check_server_cap(message.guild.id):
            log(f"🚫 Skipped — daily cap for {message.guild.name}")
            return

        u = get_user(message.author.id)
        if u and u[4] == 1:
            log(f"🚫 Skipped — {message.author} opted out")
            return

        if user_on_cooldown(message.author.id):
            log(f"🚫 Skipped — {message.author} on cooldown")
            return

        # Not opted in -> public touch + nudge (with cooldown)
        if not get_opt_in(message.author.id):
            if not can_public_touch(message.author.id):
                return
            if not can_channel_reply(message.channel.id):
                return

            touches = record_touch(message.author.id, str(message.author))
            reply_text = await build_public_response(message.content, touches)
            await message.reply(reply_text, mention_author=False)
            mark_channel_replied(message.channel.id)
            start_followup(message.channel.id, message.author.id)
            start_dm_offer(message.channel.id, message.author.id)
            return

        # Opted-in -> DM allowed
        await send_outreach_dm(message.author, message.guild.id)
        return


async def send_outreach_dm(user, sid):
    if not get_opt_in(user.id):
        log(f"🚫 DM blocked (not opted-in): {user}")
        return
    """Send outreach DM and notify owner."""
    opener = random.choice(DM_OPENERS)
    try:
        d = random.randint(5, 30)
        log(f"⏳ Waiting {d}s before DMing {user}...")
        await asyncio.sleep(d)

        dm = await user.create_dm()
        async with dm.typing():
            await asyncio.sleep(random.randint(1, 3))

        image_list = load_shared_images()
        if not image_list:
            image_list = ["preview.jpg"]
        ip = random.choice(image_list)

        try:
            with open(ip, 'rb') as f:
                await dm.send(content=opener, file=discord.File(f, filename=os.path.basename(ip)))
            log(f"📸 Sent DM with image to {user}")
        except FileNotFoundError:
            await dm.send(opener)
            log(f"⚠️ Image not found — text only to {user}")
        except:
            await dm.send(opener)
            log(f"⚠️ Image error — text only to {user}")

        upsert_user(user.id, str(user), 'neutral')
        increment_server_cap(sid)
        log(f"✅ DM sent to {user}")

        # 🔥 NOTIFY OWNER OF NEW CONTACT
        try:
            owner = await client.fetch_user(OWNER_ID)
            await owner.send(
                f"📬 **New Contact Made**\n"
                f"👤 Username: {user}\n"
                f"🆔 ID: {user.id}\n"
                f"💬 Message: \"{opener}\"\n"
                f"🕐 Time: {datetime.now().strftime('%H:%M:%S')}"
            )
            log(f"✅ Owner notified of new contact with {user}")
        except Exception as e:
            log(f"⚠️ Couldn't notify owner: {e}")

    except discord.Forbidden:
        log(f"🔒 Couldn't DM {user} — DMs closed")
    except Exception as e:
        log(f"❌ Error DMing {user}: {e}")

# ============================================================
# 🖥️ TKINTER DESKTOP UI
# ============================================================

class QuietReachUI:

    # ---- Nature theme palette ----
    THEME = {
        "bg":      "#0b1f14",  # deep forest
        "panel":   "#102a1c",  # evergreen panel
        "card":    "#153522",  # card background
        "text":    "#e7f6ee",  # near-white
        "muted":   "#a8c7b6",  # muted mint
        "accent":  "#3bb273",  # leaf green
        "accent2": "#4aa3df",  # sky blue
        "warn":    "#e67e22",  # orange
        "danger":  "#c0392b",  # red
        "border":  "#244a34",  # subtle border
        "log_bg":  "#07150e",  # very dark green for logs
        "log_fg":  "#9ff2c7",  # minty log text
    }
    def pick_font_family(self, candidates, fallback="Helvetica"):
        """Pick the first available font family from candidates."""
        try:
            available = set(tkfont.families(self.root))
            for fam in candidates:
                if fam in available:
                    return fam
        except Exception:
            pass
        return fallback

    def init_fonts(self):
        """Create font objects once; use them everywhere."""
        title_family = self.pick_font_family(
            ["Bebas Neue", "Montserrat", "Segoe UI Black", "Impact", "Arial Black", "Verdana"],
            fallback="Helvetica",
        )
        ui_family = self.pick_font_family(
            ["Montserrat", "Segoe UI Semibold", "Segoe UI", "Verdana", "Helvetica"],
            fallback="Helvetica",
        )
        mono_family = self.pick_font_family(
            ["Consolas", "Cascadia Mono", "Menlo", "Courier New"],
            fallback="Courier",
        )

        self.font_title = tkfont.Font(family=title_family, size=30, weight="bold")
        self.font_subtitle = tkfont.Font(family=ui_family, size=12)
        self.font_section = tkfont.Font(family=ui_family, size=12, weight="bold")
        self.font_button = tkfont.Font(family=ui_family, size=12, weight="bold")
        self.font_status = tkfont.Font(family=ui_family, size=12, weight="bold")
        self.font_log_title = tkfont.Font(family=ui_family, size=12, weight="bold")
        self.font_log = tkfont.Font(family=mono_family, size=11)

    def draw_header_art(self, canvas, w, h):
        """Draw simple mountain + tree outlines. Called on resize (<Configure>)."""
        t = self.THEME
        canvas.delete("all")

        stroke = t["muted"]
        stroke2 = t["accent"]
        width = 2

        ground_y = int(h * 0.78)

        # Ground line
        canvas.create_line(0, ground_y, w, ground_y, fill=t["border"], width=2)

        # Mountains
        def mountain(x0, x1, peakx, peaky, color):
            canvas.create_line(
                x0, ground_y, peakx, peaky, x1, ground_y,
                fill=color, width=width, smooth=True
            )

        mountain(int(w * 0.02), int(w * 0.40), int(w * 0.20), int(h * 0.22), stroke)
        mountain(int(w * 0.18), int(w * 0.62), int(w * 0.40), int(h * 0.10), stroke)

        # Ridge accents
        canvas.create_line(int(w * 0.20), int(h * 0.30), int(w * 0.28), int(h * 0.44), fill=stroke2, width=2)
        canvas.create_line(int(w * 0.40), int(h * 0.20), int(w * 0.48), int(h * 0.42), fill=stroke2, width=2)

        # Trees
        def tree(x, scale=1.0):
            tw = int(26 * scale)
            th = int(38 * scale)
            trunk_h = int(10 * scale)

            top_y = ground_y - th
            mid_x = x + tw // 2

            canvas.create_polygon(
                x, ground_y, mid_x, top_y, x + tw, ground_y,
                outline=stroke, fill="", width=width
            )
            canvas.create_line(mid_x, ground_y, mid_x, ground_y + trunk_h, fill=stroke, width=width)

        tree(int(w * 0.72), 1.0)
        tree(int(w * 0.78), 1.25)
        tree(int(w * 0.86), 1.05)
        tree(int(w * 0.92), 0.9)

        # Trail curve
        canvas.create_line(
            int(w * 0.55), ground_y,
            int(w * 0.58), int(h * 0.90),
            int(w * 0.62), ground_y,
            fill=t["border"], width=2, smooth=True
        )

    def __init__(self, root):
        self.root        = root
        self.bot_thread  = None
        self.bot_running = False
        self.loop        = None

        self.root.title("🤫 Quiet Reach — Control Panel")
        self.root.geometry("950x700")
        self.root.configure(bg=self.THEME["bg"])
        self.root.resizable(True, True)

        self.init_fonts()
        self.build_ui()

        global ui_log
        ui_log = self.append_log

    def build_ui(self):
        t = self.THEME

        # Root background
        self.root.configure(bg=t["bg"])

        # HEADER
        header_frame = tk.Frame(self.root, bg=t["bg"])
        header_frame.pack(fill="x", padx=20, pady=(15, 8))

        title_wrap = tk.Frame(header_frame, bg=t["bg"])
        title_wrap.pack(side="left")

        tk.Label(
            title_wrap, text="Quiet Reach",
            font=("Helvetica", 24, "bold"),
            bg=t["bg"], fg=t["text"]
        ).pack(anchor="w")

        tk.Label(
            title_wrap, text="forest-quiet outreach assistant",
            font=("Helvetica", 10),
            bg=t["bg"], fg=t["muted"]
        ).pack(anchor="w", pady=(2, 0))

        self.status_label = tk.Label(
            header_frame, text="⚫ Offline",
            font=("Helvetica", 12),
            bg=t["bg"], fg=t["muted"]
        )
        self.status_label.pack(side="right", padx=10)
        art_canvas = tk.Canvas(self.root, height=80, bg=t["bg"], highlightthickness=0)
        art_canvas.pack(fill="x", padx=20, pady=(0, 6))
        art_canvas.bind("<Configure>", lambda e: self.draw_header_art(art_canvas, e.width, e.height))
    
        # DIVIDER
        tk.Frame(self.root, bg=t["accent"], height=2).pack(fill="x", padx=20, pady=(0, 10))

        # MAIN AREA
        main_frame = tk.Frame(self.root, bg=t["bg"])
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # ---- LEFT SIDE: SCROLLABLE BUTTON PANEL ----
        btn_canvas = tk.Canvas(main_frame, bg=t["bg"], width=240, highlightthickness=0)
        btn_scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=btn_canvas.yview)
        btn_scroll_frame = tk.Frame(btn_canvas, bg=t["bg"])

        btn_scroll_frame.bind(
            "<Configure>",
            lambda e: btn_canvas.configure(scrollregion=btn_canvas.bbox("all"))
        )

        btn_canvas.create_window((0, 0), window=btn_scroll_frame, anchor="nw")
        btn_canvas.configure(yscrollcommand=btn_scrollbar.set)

        btn_canvas.pack(side="left", fill="y", padx=(0, 8))
        btn_scrollbar.pack(side="left", fill="y", padx=(0, 12))

        # Left “card” container (adds substance)
        left_card = tk.Frame(
            btn_scroll_frame,
            bg=t["card"],
            highlightbackground=t["border"],
            highlightthickness=1
        )
        left_card.pack(fill="x", padx=8, pady=8)

        # Button helper
        def make_button(parent, text, command, color, fg=None):
            if fg is None:
                fg = t["text"]

            btn = tk.Button(
                parent,
                text=text,
                command=command,
                bg=color,
                fg=fg,
                font=self.font_button,
                relief="flat",
                cursor="hand2",
                padx=12,
                pady=9,
                width=20,
                activebackground=t["border"],
                activeforeground=t["text"],
                highlightthickness=1,
                highlightbackground=t["border"],
            )
            btn.pack(pady=4, padx=8, fill="x")

            # Softer hover
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=t["border"]))
            btn.bind("<Leave>", lambda e, b=btn, c=color: b.config(bg=c))
            return btn

        # Collapsible section helper
        def make_collapsible_section(parent, title, color=t["accent"], open_by_default=True):
            outer = tk.Frame(parent, bg=t["card"])
            outer.pack(fill="x", padx=8, pady=(10, 6))

            header = tk.Frame(outer, bg=t["card"])
            header.pack(fill="x")

            is_open = tk.BooleanVar(value=open_by_default)

            icon = tk.Label(
                header,
                text=("▼" if open_by_default else "▶"),
                font=self.font_section,
                bg=t["card"],
                fg=color,
            )
            icon.pack(side="left", padx=(6, 0), pady=(6, 2))

            lbl = tk.Label(
                header,
                text=title,
                font=self.font_section,
                bg=t["card"],
                fg=t["text"],
            )
            lbl.pack(side="left", padx=(8, 0), pady=(6, 2))

            divider = tk.Frame(outer, bg=color, height=2)
            divider.pack(fill="x", padx=6, pady=(2, 8))

            content = tk.Frame(outer, bg=t["card"])

            def refresh_scrollregion():
                btn_canvas.update_idletasks()
                btn_canvas.configure(scrollregion=btn_canvas.bbox("all"))

            def set_open(open_: bool):
                is_open.set(open_)
                icon.config(text=("▼" if open_ else "▶"))
                if open_:
                    content.pack(fill="x")
                else:
                    content.pack_forget()
                outer.after(10, refresh_scrollregion)

            def toggle(_evt=None):
                set_open(not is_open.get())

            for w in (header, icon, lbl):
                w.bind("<Button-1>", toggle)

            if open_by_default:
                content.pack(fill="x")

            return content

        # Sections
        bot_controls = make_collapsible_section(left_card, "⚙️ Bot Controls", t["accent"], open_by_default=True)
        self.start_btn = make_button(bot_controls, "▶  Start Bot", self.start_bot, t["accent"])
        self.stop_btn  = make_button(bot_controls, "⏹  Stop Bot",  self.stop_bot,  t["danger"])
        self.stop_btn.config(state="disabled")

        view_lists = make_collapsible_section(left_card, "📋 View Lists", t["accent2"], open_by_default=False)
        make_button(view_lists, "🔥  Warm List",    lambda: self.view_list("warm"), t["accent2"])
        make_button(view_lists, "❄️  Cold List",    lambda: self.view_list("cold"), t["accent2"])
        make_button(view_lists, "😐  Neutral List", lambda: self.view_list("neutral"), t["accent2"])

        tools = make_collapsible_section(left_card, "🛠️ Tools", t["accent2"], open_by_default=False)
        make_button(tools, "🔍  Review Ambiguous", self.review_ambiguous, t["accent2"])
        make_button(tools, "✏️  Edit Keywords",    self.edit_keywords,   t["accent2"])
        make_button(tools, "📊  Stats",            self.show_stats,      t["accent2"])
        make_button(tools, "🖼️  Manage Images",    self.manage_images,   t["accent2"])

        reset_tools = make_collapsible_section(left_card, "🔄 Reset Tools", t["danger"], open_by_default=False)
        make_button(reset_tools, "🔄  Reset Warm",        self.reset_warm,      t["danger"])
        make_button(reset_tools, "🔄  Reset Cold",        self.reset_cold,      t["danger"])
        make_button(reset_tools, "🔄  Reset Neutral",     self.reset_neutral,   t["danger"])
        make_button(reset_tools, "🔄  Reset Ambiguous",   self.reset_ambiguous, t["danger"])
        make_button(reset_tools, "🔄  Reset Server Caps", self.reset_caps,      t["danger"])
        make_button(reset_tools, "💀  WIPE ALL DATA",     self.reset_all,       "#7b241c")

        # ---- RIGHT SIDE: LOG AREA (as a card) ----
        log_frame = tk.Frame(main_frame, bg=t["bg"])
        log_frame.pack(side="right", fill="both", expand=True)

        log_card = tk.Frame(
            log_frame,
            bg=t["card"],
            highlightbackground=t["border"],
            highlightthickness=1
        )
        log_card.pack(fill="both", expand=True, padx=6, pady=6)

        tk.Label(
            log_card, text="📡 Live Log",
            font=self.font_log_title,
            bg=t["card"], fg=t["text"]
        ).pack(anchor="w", padx=10, pady=(10, 6))

        self.log_area = scrolledtext.ScrolledText(
            log_card,
            bg=t["log_bg"],
            fg=t["log_fg"],
            font=self.font_log,
            relief="flat",
            state="disabled",
            wrap="word",
            padx=10,
            pady=10
        )
        self.log_area.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # FOOTER
        tk.Label(
            self.root,
            text="Running on discord.py  |  Quiet Reach v1.2",
            font=("Helvetica", 8),
            bg=t["bg"], fg=t["muted"]
        ).pack(pady=(8, 12))

    def append_log(self, message):
        def _update():
            self.log_area.config(state='normal')
            ts = datetime.now().strftime('%H:%M:%S')
            self.log_area.insert('end', f"[{ts}] {message}\n")
            self.log_area.see('end')
            self.log_area.config(state='disabled')
        self.root.after(0, _update)

    def start_bot(self):
        if self.bot_running:
            return
        if not BOT_TOKEN:
            messagebox.showerror("Token Missing!", "Enter BOT_TOKEN in the Login dialog.")
            return
        self.bot_running = True
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.status_label.config(text="🟢 Online", fg='#27ae60')
        self.append_log("🚀 Starting Quiet Reach bot...")
        self.bot_thread = threading.Thread(
            target=self.run_bot, daemon=True
        )
        self.bot_thread.start()

    def run_bot(self):
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(client.start(BOT_TOKEN))
        except Exception as e:
            log(f"❌ Bot error: {e}")
            self.bot_running = False
            self.root.after(0, self.reset_buttons)

    def stop_bot(self):
        if not self.bot_running:
            return
        self.append_log("⏹ Stopping bot...")
        if self.loop:
            asyncio.run_coroutine_threadsafe(client.close(), self.loop)
        self.bot_running = False
        self.reset_buttons()
        self.status_label.config(text="⚫ Offline", fg='#aaaaaa')

    def reset_buttons(self):
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')

    def view_list(self, list_type):
        users = get_users_by_list(list_type)
        emoji = {'warm': '🔥', 'cold': '❄️', 'neutral': '😐'}
        win = tk.Toplevel(self.root)
        win.title(f"{emoji.get(list_type, '')} {list_type.capitalize()} List")
        win.geometry("500x400")
        win.configure(bg='#1a1a2e')
        tk.Label(win,
            text=f"{list_type.capitalize()} List ({len(users)} users)",
            font=('Helvetica', 14, 'bold'),
            bg='#1a1a2e', fg='white').pack(pady=10)
        frame = tk.Frame(win, bg='#1a1a2e')
        frame.pack(fill='both', expand=True, padx=15, pady=5)
        sb = tk.Scrollbar(frame)
        sb.pack(side='right', fill='y')
        lb = tk.Listbox(frame, bg='#0d0d1a', fg='white',
            font=('Courier', 10), relief='flat', yscrollcommand=sb.set)
        lb.pack(fill='both', expand=True)
        sb.config(command=lb.yview)
        if users:
            for did, uname, lc in users:
                last = lc[:10] if lc else 'N/A'
                lb.insert('end', f"  {uname} | ID: {did} | Last: {last}")
        else:
            lb.insert('end', f"  No users in {list_type} list yet!")

    def review_ambiguous(self):
        entries = get_ambiguous_entries()
        win = tk.Toplevel(self.root)
        win.title("🔍 Review Ambiguous Replies")
        win.geometry("600x500")
        win.configure(bg='#1a1a2e')
        tk.Label(win,
            text=f"Ambiguous Replies — {len(entries)} pending",
            font=('Helvetica', 14, 'bold'),
            bg='#1a1a2e', fg='white').pack(pady=10)
        if not entries:
            tk.Label(win, text="✅ All clear!",
                font=('Helvetica', 12),
                bg='#1a1a2e', fg='#27ae60').pack(pady=20)
            return
        canvas = tk.Canvas(win, bg='#1a1a2e', highlightthickness=0)
        sb = ttk.Scrollbar(win, orient='vertical', command=canvas.yview)
        sf = tk.Frame(canvas, bg='#1a1a2e')
        sf.bind('<Configure>',
            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=sf, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True, padx=10, pady=5)
        sb.pack(side='right', fill='y')

        def make_clf(eid, uid, uname, cf):
            def clf(act):
                if act == 'warm':
                    upsert_user(uid, uname, 'warm')
                    self.append_log(f"🔥 Moved {uname} to WARM")
                elif act == 'cold':
                    upsert_user(uid, uname, 'cold')
                    self.append_log(f"❄️ Moved {uname} to COLD")
                delete_ambiguous(eid)
                cf.destroy()
            return clf

        for entry in entries:
            eid, did, uname, msg, ts = entry
            card = tk.Frame(sf, bg='#16213e', padx=10, pady=8)
            card.pack(fill='x', padx=10, pady=5)
            tk.Label(card, text=f"👤 {uname} (ID: {did})",
                font=('Helvetica', 10, 'bold'),
                bg='#16213e', fg='white').pack(anchor='w')
            tk.Label(card, text=f'💬 "{msg}"',
                font=('Helvetica', 10, 'italic'),
                bg='#16213e', fg='#aaaacc',
                wraplength=500, justify='left').pack(anchor='w', pady=3)
            tk.Label(card,
                text=f"🕐 {ts[:16] if ts else 'N/A'}",
                font=('Helvetica', 9),
                bg='#16213e', fg='#777799').pack(anchor='w')
            clf = make_clf(eid, did, uname, card)
            br = tk.Frame(card, bg='#16213e')
            br.pack(anchor='w', pady=5)
            tk.Button(br, text="🔥 Warm",
                command=lambda c=clf: c('warm'),
                bg='#27ae60', fg='white',
                font=('Helvetica', 9, 'bold'),
                relief='flat', padx=8, pady=4).pack(side='left', padx=3)
            tk.Button(br, text="❄️ Cold",
                command=lambda c=clf: c('cold'),
                bg='#e74c3c', fg='white',
                font=('Helvetica', 9, 'bold'),
                relief='flat', padx=8, pady=4).pack(side='left', padx=3)
            tk.Button(br, text="😐 Ignore",
                command=lambda c=clf: c('ignore'),
                bg='#777777', fg='white',
                font=('Helvetica', 9, 'bold'),
                relief='flat', padx=8, pady=4).pack(side='left', padx=3)

    def edit_keywords(self):
        win = tk.Toplevel(self.root)
        win.title("✏️ Edit Keywords")
        win.geometry("500x500")
        win.configure(bg='#1a1a2e')
        tk.Label(win, text="Edit Keywords",
            font=('Helvetica', 14, 'bold'),
            bg='#1a1a2e', fg='white').pack(pady=10)
        nb = ttk.Notebook(win)
        nb.pack(fill='both', expand=True, padx=15, pady=5)

        def make_tab(parent, ln):
            frame = tk.Frame(parent, bg='#1a1a2e')
            words = get_keywords(ln)
            lb = tk.Listbox(frame, bg='#0d0d1a', fg='white',
                font=('Courier', 10), relief='flat', height=12)
            lb.pack(fill='both', expand=True, padx=10, pady=5)
            for w in words:
                lb.insert('end', f"  {w}")
            af = tk.Frame(frame, bg='#1a1a2e')
            af.pack(fill='x', padx=10, pady=5)
            ent = tk.Entry(af, bg='#0d0d1a', fg='white',
                font=('Courier', 10), relief='flat')
            ent.pack(side='left', fill='x', expand=True, padx=(0, 5))

            def add_w():
                w = ent.get().strip().lower()
                if w:
                    c = sqlite3.connect(DB_PATH)
                    c.cursor().execute(
                        "INSERT OR IGNORE INTO keywords VALUES (?,?)",
                        (w, ln))
                    c.commit()
                    c.close()
                    lb.insert('end', f"  {w}")
                    ent.delete(0, 'end')
                    self.append_log(f"✅ Added '{w}' to {ln}")

            def rem_w():
                sel = lb.curselection()
                if sel:
                    w = lb.get(sel[0]).strip()
                    c = sqlite3.connect(DB_PATH)
                    c.cursor().execute(
                        "DELETE FROM keywords WHERE word=? AND list_name=?",
                        (w, ln))
                    c.commit()
                    c.close()
                    lb.delete(sel[0])
                    self.append_log(f"🗑️ Removed '{w}' from {ln}")

            tk.Button(af, text="➕ Add", command=add_w,
                bg='#27ae60', fg='white',
                font=('Helvetica', 9, 'bold'),
                relief='flat', padx=8).pack(side='left')
            tk.Button(frame, text="🗑️ Remove Selected", command=rem_w,
                bg='#e74c3c', fg='white',
                font=('Helvetica', 9, 'bold'),
                relief='flat', padx=8, pady=4).pack(pady=5)
            return frame

        t1 = make_tab(nb, 'trigger')
        t2 = make_tab(nb, 'yes')
        t3 = make_tab(nb, 'no')
        nb.add(t1, text='🔍 Trigger Words')
        nb.add(t2, text='✅ Yes Words')
        nb.add(t3, text='❌ No Words')

    def show_stats(self):
        w, c, n, td, p = get_stats()
        win = tk.Toplevel(self.root)
        win.title("📊 Stats")
        win.geometry("300x280")
        win.configure(bg='#1a1a2e')
        win.resizable(False, False)
        tk.Label(win, text="📊 Quiet Reach Stats",
            font=('Helvetica', 14, 'bold'),
            bg='#1a1a2e', fg='white').pack(pady=15)
        stats = [
            ("🔥 Warm Leads", w, '#27ae60'),
            ("❄️ Cold Leads", c, '#e74c3c'),
            ("😐 Neutral", n, '#f39c12'),
            ("📨 Total DMs", td, '#4a90d9'),
            ("⚠️ Pending", p, '#e67e22'),
        ]
        for label, value, color in stats:
            row = tk.Frame(win, bg='#16213e')
            row.pack(fill='x', padx=20, pady=3)
            tk.Label(row, text=label,
                font=('Helvetica', 10),
                bg='#16213e', fg='white',
                width=20, anchor='w').pack(side='left', padx=10, pady=6)
            tk.Label(row, text=str(value),
                font=('Helvetica', 10, 'bold'),
                bg='#16213e', fg=color).pack(side='right', padx=10)
        tk.Button(win, text="Close", command=win.destroy,
            bg='#4a90d9', fg='white',
            font=('Helvetica', 10, 'bold'),
            relief='flat', padx=15, pady=6).pack(pady=15)

    def manage_images(self):
        """Open a window to manage outreach images."""
        import os
        from tkinter import filedialog

        win = tk.Toplevel(self.root)
        win.title("🖼️ Manage Outreach Images")
        win.geometry("500x400")
        win.configure(bg='#1a1a2e')

        tk.Label(
            win, text="🖼️ Outreach Images",
            font=('Helvetica', 14, 'bold'),
            bg='#1a1a2e', fg='white'
        ).pack(pady=10)

        tk.Label(
            win,
            text="These images rotate randomly with each outreach DM",
            font=('Helvetica', 9),
            bg='#1a1a2e', fg='#aaaaaa'
        ).pack()

        # Image list display
        frame = tk.Frame(win, bg='#1a1a2e')
        frame.pack(fill='both', expand=True, padx=15, pady=10)

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side='right', fill='y')

        listbox = tk.Listbox(
            frame, bg='#0d0d1a', fg='white',
            font=('Courier', 10), relief='flat',
            yscrollcommand=scrollbar.set
        )
        listbox.pack(fill='both', expand=True)
        scrollbar.config(command=listbox.yview)

        images_file = 'images.txt'

        def load_images():
            listbox.delete(0, 'end')
            if os.path.exists(images_file):
                with open(images_file, 'r') as f:
                    lines = [l.strip() for l in f.readlines() if l.strip()]
                    for line in lines:
                        listbox.insert('end', f"  {line}")
            else:
                listbox.insert('end', "  No images added yet!")

        load_images()

        def add_image():
            filepath = filedialog.askopenfilename(
                title="Select an image",
                filetypes=[
                    ("Image files", "*.jpg *.jpeg *.png *.gif *.webp"),
                    ("All files", "*.*")
                ]
            )
            if filepath:
                import shutil
                filename = os.path.basename(filepath)
                dest     = os.path.join(os.getcwd(), filename)
                shutil.copy2(filepath, dest)

                with open(images_file, 'a') as f:
                    f.write(filename + '\n')

                load_images()
                self.append_log(f"🖼️ Added image: {filename}")

        def remove_image():
            selected = listbox.curselection()
            if selected:
                image_name = listbox.get(selected[0]).strip()

                if os.path.exists(images_file):
                    with open(images_file, 'r') as f:
                        lines = [l.strip() for l in f.readlines() if l.strip()]
                    lines = [l for l in lines if l != image_name]
                    with open(images_file, 'w') as f:
                        f.write('\n'.join(lines))

                load_images()
                self.append_log(f"🗑️ Removed image: {image_name}")

        btn_row = tk.Frame(win, bg='#1a1a2e')
        btn_row.pack(pady=10)

        tk.Button(
            btn_row, text="➕ Add Image", command=add_image,
            bg='#27ae60', fg='white', font=('Helvetica', 10, 'bold'),
            relief='flat', cursor='hand2', padx=12, pady=6
        ).pack(side='left', padx=5)

        tk.Button(
            btn_row, text="🗑️ Remove Selected", command=remove_image,
            bg='#e74c3c', fg='white', font=('Helvetica', 10, 'bold'),
            relief='flat', cursor='hand2', padx=12, pady=6
        ).pack(side='left', padx=5)

    def reset_warm(self):
        if messagebox.askyesno("Reset", "Wipe Warm List?"):
            c = sqlite3.connect(DB_PATH)
            c.cursor().execute("DELETE FROM users WHERE list_type='warm'")
            c.commit()
            c.close()
            self.append_log("🔄 Warm List wiped!")

    def reset_cold(self):
        if messagebox.askyesno("Reset", "Wipe Cold List?"):
            c = sqlite3.connect(DB_PATH)
            c.cursor().execute("DELETE FROM users WHERE list_type='cold'")
            c.commit()
            c.close()
            self.append_log("🔄 Cold List wiped!")

    def reset_neutral(self):
        if messagebox.askyesno("Reset", "Wipe Neutral List?"):
            c = sqlite3.connect(DB_PATH)
            c.cursor().execute("DELETE FROM users WHERE list_type='neutral'")
            c.commit()
            c.close()
            self.append_log("🔄 Neutral List wiped!")

    def reset_ambiguous(self):
        if messagebox.askyesno("Reset", "Wipe Ambiguous replies?"):
            c = sqlite3.connect(DB_PATH)
            c.cursor().execute("DELETE FROM ambiguous")
            c.commit()
            c.close()
            self.append_log("🔄 Ambiguous wiped!")

    def reset_caps(self):
        if messagebox.askyesno("Reset", "Reset server caps?"):
            c = sqlite3.connect(DB_PATH)
            c.cursor().execute("DELETE FROM server_caps")
            c.commit()
            c.close()
            self.append_log("🔄 Server caps reset!")

    def reset_all(self):
        if messagebox.askyesno("⚠️ WIPE ALL", "Wipe ALL data? This cannot be undone!"):
            if messagebox.askyesno("⚠️ FINAL WARNING", "Are you absolutely sure?"):
                c = sqlite3.connect(DB_PATH)
                cur = c.cursor()
                cur.execute("DELETE FROM users")
                cur.execute("DELETE FROM ambiguous")
                cur.execute("DELETE FROM server_caps")
                c.commit()
                c.close()
                self.append_log("💀 ALL DATA WIPED!")

# ============================================================
# 🚀 LAUNCH
# ============================================================
if __name__ == "__main__":
    setup_database()
    root = tk.Tk()
    root.withdraw()          # hide main window during login
    login_dialog(root)       # always prompt on launch
    root.deiconify()         # show UI after login dialog closes
    app  = QuietReachUI(root)
    root.mainloop()
































































