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
# Official Lucas links (DM-only)
CHATABURATE_URL = "https://chaturbate.com/b/lucas_jacobs/"
ONLYFANS_FREE_URL = "https://onlyfans.com/lucas_jacobs_free"
ONLYFANS_PAID_URL = "https://onlyfans.com/lucasjacobs170"
X_URL = "https://x.com/lucasjacobs170"
INSTAGRAM_URL = "https://www.instagram.com/lucas_jacobs17/?hl=en"
# One-line blurbs to add context in DMs when giving a link
LINK_BLURBS = {
    "discord": "His community hub — updates, drops, and a direct way to keep up with Lucas.",
    "chaturbate": "His live cam page — where you can catch him live and interact in real time.",
    "onlyfans_free": "Free follow page — lighter previews and updates.",
    "onlyfans_paid": "Paid page — the full premium content and the hottest drops.",
    "x": "Fast updates + teasers when he posts something new.",
    "instagram": "Pics + casual updates — the most “daily life” vibe.",
}
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
def rebuild_invite_texts():
    """Rebuild any strings that embed SERVER_INVITE."""
    global ABOUT_LUCAS, YES_RESPONSES

    ABOUT_LUCAS = f"""
You are Quiet Reach, Lucas Jacobs's assistant (not Lucas).

- Lucas Jacobs is a man. Use he/him pronouns.
- Never refer to Lucas as she/her or they/them.
- Never reference time of day (morning/afternoon/evening/night/tonight/today).
- Do not say things like “tonight”, “this morning”, “later today”, “late-night”, etc.

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
- If you don't know, say so and ask if they want links in DM ("say `link` or `links`").
- Keep replies SHORT: 1–2 sentences, max ~240 characters.
- Never output any URLs/links in AI responses (links are handled by system routing).
""".strip()

    YES_RESPONSES = [
        f"Yesss okay! 🎉 Here's an invite to Lucas's server, come hang: {SERVER_INVITE}",
        f"Ugh okay let's gooo 🙌 — drop into the server and we can chat more: {SERVER_INVITE}",
        f"Ahh okay I love that for you 😏 — here's the link, come through: {SERVER_INVITE}",
        f"Yay!! 🎉 Okay here's the server link — it's chill in there I promise 😊: {SERVER_INVITE}",
        f"Okay yes! 👏 Come hang with us — here's the invite: {SERVER_INVITE}",
        f"Let's gooo! 🔥 Here's where the fun is: {SERVER_INVITE}",
        f"Omg hi yes! 😊 Jump in here and we can chat more: {SERVER_INVITE}",
        f"Ayyy welcome! 🎊 Here's the link — see you in there: {SERVER_INVITE}",
    ]


COMMANDS_HELP_TEXT = """
Quiet Reach — Commands Reference

OWNER / PROMO
- !promosetup [start end]
  Configure promo channel (current channel) + set PT window hours + enable promos.
  Example: !promosetup 18 22

- !setpromochannel
  Set promo channel to the current channel (also schedules a default window).

- !promowindow <start end>
  Set the promo window in PT hours (0–23). Schedules next post randomly in-window.

- !promoon
  Enable promos for this server.

- !promooff
  Disable promos for this server.

- !promonow
  Post a promo immediately (then schedules the next run).

- !promostatus
  Show promo configuration + next/last post time.

OPT-IN / DM CONTROL (server chat)
- !optin / !opt-in / !dmme / !dm me
  Opt the user into DMs and immediately DM outreach.

- !optout / !opt-out / !nodm / !no dm
  Opt the user out of DMs.

DM COMMANDS (DMs to the bot)
- stop / remove / opt out / optout
  Opt out of future contact.

- link / server / invite
  Return the current SERVER_INVITE.

GENERAL BEHAVIOR (automatic)
- Keyword trigger engagement:
  If KEYWORD_MODE_ENABLED is True and a trigger keyword is detected, the bot replies publicly
  and offers DM opt-in; opted-in users may be DM’d (cap + cooldown rules apply).

DEV UI (Tkinter)
- Tools → Dev Commands
  Includes “Post Promo Now (all enabled)”, stats, toggles for keyword mode + logging.

Notes:
- Some actions are OWNER-only by OWNER_ID.
- Public replies are visible; “invisible” interaction requires slash commands + ephemeral (not implemented).
""".strip()

rebuild_invite_texts()
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
NO_RESPONSES=["Totally cool, no worries at all! 👌","All good! Sorry to bother 😊 have a great day!","No worries at all! Take care 💙","Totally understand! Have a good one 👋","All good, no hard feelings! 😊","Haha fair enough! Sorry to slide in 😅 take care!","No worries! Hope you have an amazing day 🌟","Understood! Sorry for the interruption 😊💙"]
OPT_OUT_RESPONSES=["Done! You've been opted out — I won't message you again. Take care! 💙","Of course! Removing you now — sorry for the bother 😊 take care!","Got it! You won't hear from me again. Have a great one 💙","Absolutely! All done — sorry if I bothered you 😊 take care!"]

# ============================================================
# 🔐 CONFIG / LOGIN (local, per-machine)
# ============================================================

def normalize_bot_token(tok: str) -> str:
    tok = (tok or "").strip()

    # If user pasted "Bot <token>", strip prefix
    if tok.lower().startswith("bot "):
        tok = tok[4:].strip()

    # Remove ANY whitespace anywhere (spaces/newlines/tabs)
    tok = "".join(tok.split())
    return tok

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
    global BOT_TOKEN, SERVER_INVITE

    if "BOT_TOKEN" in cfg:
        BOT_TOKEN = normalize_bot_token(cfg.get("BOT_TOKEN") or "")

    if "SERVER_INVITE" in cfg and cfg.get("SERVER_INVITE"):
        SERVER_INVITE = (cfg.get("SERVER_INVITE") or "").strip()
        rebuild_invite_texts()

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
        merged = cfg or {}
        tok = normalize_bot_token(token_var.get())

        # Optional validation (prevents bad pastes)
        if not tok or tok.count(".") < 2:
            messagebox.showerror(
                "Invalid Token",
                "BOT_TOKEN looks invalid. Paste the raw bot token (one line)."
            )
            return

        merged["BOT_TOKEN"] = tok
        save_config(merged)
        apply_config(merged)
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
    
    k.execute(
        "CREATE TABLE IF NOT EXISTS conversation_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "ts_utc TEXT,"
        "guild_id TEXT,"
        "channel_id TEXT,"
        "user_id TEXT,"
        "username TEXT,"
        "is_dm INTEGER,"
        "direction TEXT,"
        "message TEXT"
        ")"
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

AI_MAX_CHARS_DM = 260
AI_MAX_CHARS_PUBLIC = 220

_dm_cta_counter = {}  # user_id -> int

def maybe_add_dm_cta(user_id: int, text: str) -> str:
    """
    Add the server CTA occasionally (every 4th DM), not every message.
    """
    n = _dm_cta_counter.get(user_id, 0) + 1
    _dm_cta_counter[user_id] = n

    if n % 4 != 0:
        return text

    return (text.rstrip() + "\n\nIf you want to join the server, just type `link`.").strip()

def _strip_links_and_discord_words(text: str) -> str:
    t = (text or "").strip()

    # Remove all URLs
    t = re.sub(r"https?://\S+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bdiscord\.gg/\S+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bdiscord\.com/invite/\S+", "", t, flags=re.IGNORECASE)

    # Remove “discord/invite/server link” wording (prevents “go join…” in public)
    t = re.sub(r"\bdiscord\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\binvite\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bserver\b", "", t, flags=re.IGNORECASE)

    # Collapse whitespace
    t = " ".join(t.split()).strip()
    return t

def _shorten(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    t = t[: max_chars - 1].rstrip()
    return t + "…"

def chunk_text(s: str, max_len: int = 1700) -> list[str]:
    """
    Split long text into Discord-safe chunks without cutting mid-paragraph.
    Falls back to hard slicing if a single paragraph is too long.
    """
    s = (s or "").strip()
    if not s:
        return []

    parts: list[str] = []
    buf = ""

    for para in s.split("\n\n"):
        para = para.strip()
        if not para:
            continue

        candidate = (buf + ("\n\n" if buf else "") + para).strip()
        if len(candidate) <= max_len:
            buf = candidate
            continue

        if buf:
            parts.append(buf)
            buf = ""

        if len(para) <= max_len:
            buf = para
        else:
            # Hard-slice very long paragraphs
            for i in range(0, len(para), max_len):
                parts.append(para[i:i + max_len])

    if buf:
        parts.append(buf)

    return parts

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
        reply = (reply or "").strip()
        reply = _strip_links_and_discord_words(reply)
        return reply
    except Exception as e:
        log(f"❌ Local model reply error: {e}")
        return ""
def log(m):
    print(m)
    if ui_log:ui_log(m)

# ============================================================
# 📝 FILE LOGGING (conversation log to disk)
# ============================================================

DB_LOG_ENABLED = True
FILE_LOG_ENABLED = True
CONVO_LOG_FILE = "conversation_log.jsonl"  # saved in bot folder


def convo_file_log(event: dict):
    """Append one conversation event to a JSONL file."""
    try:
        with open(CONVO_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"⚠️ convo_file_log failed: {e}")

def convo_log(
    guild_id,
    channel_id,
    user_id,
    username,
    is_dm: int,
    direction: str,
    message: str
):
    """
    Writes a conversation event to SQLite.
    direction: 'in' (user -> bot) or 'out' (bot -> user)
    is_dm: 1 for DM, 0 for server
    """
    event = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "guild_id": str(guild_id or ""),
        "channel_id": str(channel_id or ""),
        "user_id": str(user_id or ""),
        "username": str(username or ""),
        "is_dm": int(is_dm),
        "direction": (direction or "")[:8],
        "message": (message or "")[:2000],
    }

    # 1) File log (easy to view)
    if FILE_LOG_ENABLED:
        convo_file_log(event)

    # 2) DB log (optional, keep if you still want SQLite)
    if not DB_LOG_ENABLED:
        return

    try:
        c = sqlite3.connect(DB_PATH, timeout=30)
        k = c.cursor()
        k.execute(
            "INSERT INTO conversation_log(ts_utc,guild_id,channel_id,user_id,username,is_dm,direction,message) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                event["ts_utc"],
                event["guild_id"],
                event["channel_id"],
                event["user_id"],
                event["username"],
                event["is_dm"],
                event["direction"],
                event["message"],
            )
        )
        c.commit()
        c.close()
    except Exception as e:
        log(f"⚠️ convo_log (db) failed: {e}")


def log_inbound_message(message):
    """Log inbound server/DM message."""
    try:
        is_dm = int(isinstance(message.channel, discord.DMChannel))
        gid = "" if is_dm else (message.guild.id if message.guild else "")
        convo_log(
            guild_id=gid,
            channel_id=message.channel.id,
            user_id=message.author.id,
            username=str(message.author),
            is_dm=is_dm,
            direction="in",
            message=(message.content or "")
        )
    except Exception as e:
        log(f"⚠️ inbound convo_log failed: {e}")


async def send_logged(channel, guild_id, content: str = "", file=None, is_dm: int = 0):
    """Send a message and log it as outbound."""
    try:
        msg = (content or "")
        if file is not None:
            try:
                fn = getattr(file, "filename", "") or ""
                if fn:
                    msg = (msg + f"\n[file:{fn}]").strip()
            except Exception:
                pass

        convo_log(
            guild_id=guild_id or "",
            channel_id=channel.id,
            user_id=client.user.id if client.user else "",
            username=str(client.user) if client.user else "bot",
            is_dm=int(is_dm),
            direction="out",
            message=msg
        )
    except Exception as e:
        log(f"⚠️ outbound convo_log failed: {e}")

    # Actually send
    if file is not None:
        return await channel.send(content=content, file=file)
    return await channel.send(content=content)


async def reply_logged(message, content: str, mention_author: bool = False, file=None):
    """Reply and log as outbound. (Does NOT call send_logged to avoid double-send.)"""
    try:
        is_dm = int(isinstance(message.channel, discord.DMChannel))
        gid = "" if is_dm else (message.guild.id if message.guild else "")

        msg = (content or "")
        if file is not None:
            try:
                fn = getattr(file, "filename", "") or ""
                if fn:
                    msg = (msg + f"\n[file:{fn}]").strip()
            except Exception:
                pass

        convo_log(
            guild_id=gid,
            channel_id=message.channel.id,
            user_id=client.user.id if client.user else "",
            username=str(client.user) if client.user else "bot",
            is_dm=is_dm,
            direction="out",
            message=msg,
        )
    except Exception as e:
        log(f"⚠️ reply_logged convo_log failed: {e}")

    # Actually reply
    if file is not None:
        return await message.reply(content, mention_author=mention_author, file=file)
    return await message.reply(content, mention_author=mention_author)

# ============================================================
# ✅ SERVER REPLY HELPER (logs all public replies)
# ============================================================

async def server_reply(message, content: str, mention_author: bool = False, file=None):
    """
    Use this instead of message.reply(...) anywhere in SERVER channels.
    It logs the outbound message via reply_logged().
    """
    return await reply_logged(message, content, mention_author=mention_author, file=file)


async def server_send(channel, guild_id, content: str = "", file=None):
    """
    Use this instead of channel.send(...) for SERVER sends (promos).
    """
    return await send_logged(channel, guild_id=str(guild_id or ""), content=content, file=file, is_dm=0)

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

    # strip time-of-day references
    t = re.sub(
        r"\b(morning|afternoon|evening|night|tonight|today|tomorrow|yesterday|midnight)\b",
        "",
        t,
        flags=re.IGNORECASE
    )
    
    # remove common 1:1 pet names (crowd voice)
    t = re.sub(r"\b(gorgeous|babe|baby|hun|honey|handsome|sweetheart)\b", "", t, flags=re.IGNORECASE)

    # prevent pings / mass mentions
    t = t.replace("@everyone", "everyone").replace("@here", "here")

    # strip ANY links
    t = re.sub(r"https?://\S+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bdiscord\.gg/\S+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bdiscord\.com/invite/\S+", "", t, flags=re.IGNORECASE)

    # discourage the word "discord" in the public advert
    t = re.sub(r"\bdiscord\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\binvite\b", "", t, flags=re.IGNORECASE)

    t = "\n".join([" ".join(line.split()).strip() for line in t.splitlines()]).strip()

    if len(t) > PROMO_MAX_CHARS:
        t = t[:PROMO_MAX_CHARS - 1].rstrip() + "…"

    return t

def promo_set_next_post_at(guild_id: int, next_post_at_utc_iso: str):
    c = sqlite3.connect(DB_PATH); k = c.cursor()
    k.execute(
        "UPDATE promo_channels SET next_post_at_utc=? WHERE guild_id=?",
        (next_post_at_utc_iso, str(guild_id))
    )
    c.commit(); c.close()

async def generate_promo_caption(theme: str, seed: str) -> str:
    """
    Organic, saucy, NON-explicit promo caption.
    No links. CTA drives interaction with the bot (reply "yes").
    """
    cta = "Reply “yes” and I’ll DM you a preview."
    seed = (seed or "").strip()

    prompt = f"""
You write short, saucy promotional captions for an adult creator.
Tone: flirty, playful, confident, organic (no corporate vibe).
Rules:
- Speak to a CROWD (plural) like you’re addressing a channel, not one person.
  Use crowd words: "hikers", "campers", "crew", "y’all", "everyone".
- Avoid 1:1 pet names like "gorgeous", "babe", "baby", "honey", "handsome".
- Outdoorsy + playful vibe (trail / campfire / sunset / stargazing metaphors OK).
- NON-explicit only: no graphic anatomy, no sex acts.
- No minors. No coercion. No harassment.
- Do NOT include any URLs or links of any kind.
- Do NOT mention Discord, invites, or servers.
- No @everyone / @here.
- 1–2 short lines max, plus this CTA (exact words): {cta}
- Keep under {PROMO_MAX_CHARS} characters total.

Theme: {theme}
Seed idea (optional): {seed}

Return ONLY the caption text.
"""

    loop = asyncio.get_event_loop()
    out = await loop.run_in_executor(None, lambda: ollama_generate(prompt))
    out = _sanitize_caption(out)

    if not out:
        base = seed if seed else "Hey you… you’re gonna like this."
        return _sanitize_caption(f"{base}\n{cta}")

    # ensure CTA exists (no links)
    if "reply" not in out.lower() or "yes" not in out.lower():
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
                file = discord.File(f, filename=os.path.basename(image_path))
                await server_send(channel, guild_id=guild_id, content=caption, file=file)
        else:
            await server_send(channel, guild_id=guild_id, content=caption)

        promo_record_history(guild_id, channel_id, image_path or "", caption)
        log(f"📣 Promo posted in {guild.name} #{getattr(channel,'name','?')}")
        return True

    except FileNotFoundError:
        log(f"⚠️ Promo image missing: {image_path} (posting text only)")
        try:
            await server_send(channel, guild_id=guild_id, content=caption)
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

async def dev_post_promo_now_all() -> tuple[int, int]:
    """
    Dev utility: Post a promo immediately for every enabled promo row.
    Returns: (attempted, succeeded)
    """
    rows = promo_get_enabled_rows()
    if not rows:
        log("🧪 Dev PromoNow: no enabled promo rows.")
        return (0, 0)

    themes = [
        "fresh drop",
        "tease + mystery",
        "outdoorsy flirty",
        "friendly invite",
    ]

    seeds = _load_promo_seeds()
    image_list = load_shared_images()

    attempted = 0
    succeeded = 0

    for (gid, cid, start_pt, end_pt, _next_iso) in rows:
        attempted += 1

        theme = random.choice(themes)
        seed = random.choice(seeds) if seeds else ""
        img = random.choice(image_list) if image_list else ""

        caption = await generate_promo_caption(theme, seed)
        ok = await _post_promo(int(gid), int(cid), caption, img)

        # Always schedule next (avoid rapid retry spam)
        promo_update_next(int(gid), int(start_pt), int(end_pt))

        if ok:
            succeeded += 1

        await asyncio.sleep(1)  # gentle spacing

    log(f"🧪 Dev PromoNow done: {succeeded}/{attempted} succeeded.")
    return (attempted, succeeded)

@client.event
async def on_ready():
    global promo_task
    log(f"✅ Logged in as {client.user} (ID: {client.user.id})")

    # Start promo loop once
    if promo_task is None or promo_task.done():
        promo_task = asyncio.create_task(promo_loop())
        log("📣 Promo loop started.")
    
def build_official_links_all_message() -> str:
    lines = ["Here are Lucas’s official links (DM-only) + what each one is for:"]

    if CHATABURATE_URL:
        lines.append(f"- Chaturbate: {CHATABURATE_URL}")
        lines.append(f"  {LINK_BLURBS['chaturbate']}")

    if ONLYFANS_FREE_URL:
        lines.append(f"- OnlyFans (free): {ONLYFANS_FREE_URL}")
        lines.append(f"  {LINK_BLURBS['onlyfans_free']}")

    if ONLYFANS_PAID_URL:
        lines.append(f"- OnlyFans (paid): {ONLYFANS_PAID_URL}")
        lines.append(f"  {LINK_BLURBS['onlyfans_paid']}")

    if X_URL:
        lines.append(f"- X: {X_URL}")
        lines.append(f"  {LINK_BLURBS['x']}")

    if INSTAGRAM_URL:
        lines.append(f"- Instagram: {INSTAGRAM_URL}")
        lines.append(f"  {LINK_BLURBS['instagram']}")

    if SERVER_INVITE:
        lines.append(f"- Discord: {SERVER_INVITE}")
        lines.append(f"  {LINK_BLURBS['discord']}")

    lines.append("")
    lines.append("If you want, tell me which vibe you want (live / premium / socials) and I’ll narrow it down.")
    return "\n".join(lines)


def build_other_options_hint(except_keys: list[str] | None = None) -> str:
    except_keys = set(except_keys or [])
    options = []
    if "discord" not in except_keys and SERVER_INVITE:
        options.append("Discord")
    if "onlyfans" not in except_keys and (ONLYFANS_FREE_URL or ONLYFANS_PAID_URL):
        options.append("OnlyFans (free/paid)")
    if "chaturbate" not in except_keys and CHATABURATE_URL:
        options.append("Chaturbate")
    if "x" not in except_keys and X_URL:
        options.append("X")
    if "instagram" not in except_keys and INSTAGRAM_URL:
        options.append("Instagram")

    if not options:
        return "If you want the full list, say `links`."
    return f"Also available: {', '.join(options)}. If you want the full list, say `links`."


def dm_link_router(content_lower: str) -> str | None:
    """
    Returns a DM response string if this message is requesting links/contact.
    Otherwise returns None so normal DM logic continues.
    """
    t = (content_lower or "").strip().lower()
    if not t:
        return None

    soft = random.choice(DM_SOFTENERS)

    # 1) Contact intent -> give best contact options (not a sales pitch)
    if is_contact_intent(t):
        lines = [soft, "Best ways to contact / follow Lucas:"]
        if SERVER_INVITE:
            lines.append(f"- Discord: {SERVER_INVITE}")
            lines.append(f"  {LINK_BLURBS['discord']}")
        if X_URL:
            lines.append(f"- X: {X_URL}")
            lines.append(f"  {LINK_BLURBS['x']}")
        if INSTAGRAM_URL:
            lines.append(f"- Instagram: {INSTAGRAM_URL}")
            lines.append(f"  {LINK_BLURBS['instagram']}")
        lines.append("")
        lines.append("If you want everything, just say `links`.")
        return "\n".join(lines)

    # 2) If they ask for info/explanations with links, return the annotated list
    if (("info" in t) or ("information" in t) or ("explain" in t) or ("what is this" in t) or ("what are these" in t)) and is_links_request(t):
        return build_official_links_all_message()
    
    # 3) Any “links/socials” request -> full list (annotated)
    if is_links_request(t) or t in ["all links", "link list", "contact"]:
        return build_official_links_all_message()

    # Detect platform intents (supports multi-platform asks like "x instagram discord")
    explicit_link = is_explicit_link_ask(t) or is_links_request(t) or is_contact_intent(t)
    wants_discord = (
        t in ["link", "invite", "server"]
        or (explicit_link and ("discord" in t))
        or "discord.gg" in t
        or "discord.com/invite" in t
    )

    wants_instagram = explicit_link and (("instagram" in t) or bool(re.search(r"(?:^|\s)ig(?:$|\s)", t)))
    wants_x = explicit_link and (("x.com" in t) or ("twitter" in t) or bool(re.search(r"\bx\b", t)))
    wants_chaturbate = explicit_link and ("chaturbate" in t)
    wants_onlyfans = explicit_link and (("onlyfans" in t) or (t.strip() == "of"))

    wants_free = ("free" in t)
    wants_paid = ("paid" in t) or ("vip" in t)

    requested = []
    if wants_discord: requested.append("discord")
    if wants_instagram: requested.append("instagram")
    if wants_x: requested.append("x")
    if wants_chaturbate: requested.append("chaturbate")
    if wants_onlyfans: requested.append("onlyfans")

    # If they mentioned 2+ platforms, give those (not the entire list)
    if len(requested) >= 2:
        lines = [soft, "Here you go:"]
        except_keys = []

        if "discord" in requested and SERVER_INVITE:
            lines.append(f"- Discord: {SERVER_INVITE}")
            lines.append(f"  {LINK_BLURBS['discord']}")
            except_keys.append("discord")

        if "instagram" in requested and INSTAGRAM_URL:
            lines.append(f"- Instagram: {INSTAGRAM_URL}")
            lines.append(f"  {LINK_BLURBS['instagram']}")
            except_keys.append("instagram")

        if "x" in requested and X_URL:
            lines.append(f"- X: {X_URL}")
            lines.append(f"  {LINK_BLURBS['x']}")
            except_keys.append("x")

        if "chaturbate" in requested and CHATABURATE_URL:
            lines.append(f"- Chaturbate: {CHATABURATE_URL}")
            lines.append(f"  {LINK_BLURBS['chaturbate']}")
            except_keys.append("chaturbate")

        if "onlyfans" in requested:
            if wants_free and ONLYFANS_FREE_URL:
                lines.append(f"- OnlyFans (free): {ONLYFANS_FREE_URL}")
                lines.append(f"  {LINK_BLURBS['onlyfans_free']}")
            elif wants_paid and ONLYFANS_PAID_URL:
                lines.append(f"- OnlyFans (paid): {ONLYFANS_PAID_URL}")
                lines.append(f"  {LINK_BLURBS['onlyfans_paid']}")
            else:
                if ONLYFANS_FREE_URL:
                    lines.append(f"- OnlyFans (free): {ONLYFANS_FREE_URL}")
                    lines.append(f"  {LINK_BLURBS['onlyfans_free']}")
                if ONLYFANS_PAID_URL:
                    lines.append(f"- OnlyFans (paid): {ONLYFANS_PAID_URL}")
                    lines.append(f"  {LINK_BLURBS['onlyfans_paid']}")
            except_keys.append("onlyfans")

        lines.append("")
        lines.append(build_other_options_hint(except_keys))
        return "\n".join(lines)

    # ---- Single-platform cases ----
    if wants_discord:
        if SERVER_INVITE:
            return (
                f"{soft}\n"
                f"Discord invite: {SERVER_INVITE}\n"
                f"{LINK_BLURBS['discord']}\n\n"
                f"{build_other_options_hint(['discord'])}"
            )
        return "I don’t have the Discord invite saved right now."

    if wants_instagram:
        if INSTAGRAM_URL:
            return (
                f"{soft}\n"
                f"Instagram: {INSTAGRAM_URL}\n"
                f"{LINK_BLURBS['instagram']}\n\n"
                f"{build_other_options_hint(['instagram'])}"
            )
        return "I don’t have the Instagram link saved right now."

    if wants_x:
        if X_URL:
            return (
                f"{soft}\n"
                f"X: {X_URL}\n"
                f"{LINK_BLURBS['x']}\n\n"
                f"{build_other_options_hint(['x'])}"
            )
        return "I don’t have the X link saved right now."

    if wants_chaturbate:
        if CHATABURATE_URL:
            return (
                f"{soft}\n"
                f"Chaturbate: {CHATABURATE_URL}\n"
                f"{LINK_BLURBS['chaturbate']}\n\n"
                f"{build_other_options_hint(['chaturbate'])}"
            )
        return "I don’t have the Chaturbate link saved right now."

    if wants_onlyfans:
        if wants_free and wants_paid:
            pass
        else:
            if wants_free and ONLYFANS_FREE_URL:
                return (
                    f"{soft}\n"
                    f"OnlyFans (free): {ONLYFANS_FREE_URL}\n"
                    f"{LINK_BLURBS['onlyfans_free']}\n\n"
                    f"{build_other_options_hint(['onlyfans'])}"
                )
            if wants_paid and ONLYFANS_PAID_URL:
                return (
                    f"{soft}\n"
                    f"OnlyFans (paid): {ONLYFANS_PAID_URL}\n"
                    f"{LINK_BLURBS['onlyfans_paid']}\n\n"
                    f"{build_other_options_hint(['onlyfans'])}"
                )

        lines = [soft, "OnlyFans links:"]
        if ONLYFANS_FREE_URL:
            lines.append(f"- Free: {ONLYFANS_FREE_URL}")
            lines.append(f"  {LINK_BLURBS['onlyfans_free']}")
        if ONLYFANS_PAID_URL:
            lines.append(f"- Paid: {ONLYFANS_PAID_URL}")
            lines.append(f"  {LINK_BLURBS['onlyfans_paid']}")
        if len(lines) <= 2:
            return "I don’t have the OnlyFans links saved right now."
        lines.append("")
        lines.append(build_other_options_hint(["onlyfans"]))
        return "\n".join(lines)

    return None

DM_DELAY_MIN_SECONDS = 3
DM_DELAY_MAX_SECONDS = 5

async def dm_human_delay(channel):
    try:
        async with channel.typing():
            await asyncio.sleep(random.randint(DM_DELAY_MIN_SECONDS, DM_DELAY_MAX_SECONDS))
    except Exception:
        await asyncio.sleep(random.randint(DM_DELAY_MIN_SECONDS, DM_DELAY_MAX_SECONDS))

async def handle_dm_reply(message):
    # Log inbound DM
    log_inbound_message(message)

    user_id = message.author.id
    username = str(message.author)
    content = (message.content or "").strip()
    content_lower = content.lower().strip()
    # Full lore on request (DM-only)
    if content_lower in ["full story", "full lore", "the full story", "tell me the full story"]:
        set_dm_topic(user_id, "lore")
        await send_logged(message.channel, guild_id="", content=QUIET_REACH_CANON_LORE_FULL[:1800], is_dm=1)
        return
    await dm_human_delay(message.channel)

    # Bot identity / lore (DM-only)
    if any(p in content_lower for p in [
    "how did you come about", "how were you made", "how were you created",
    "how did you get made", "are you a bot", "you are a bot", "you're a bot",
    "are you human", "what made you", "who built you",
    "who are you", "what are you", "who made you", "how old are you",
    "your backstory", "backstory",
    "your story", "tell me your story", "tell me about you",
    "who is quiet reach", "what is quiet reach",
    "what's your deal", "whats your deal",
    "your vibe", "what's your vibe", "whats your vibe",
    ]):
        lore = random.choice(BOT_BACKSTORY_LINES)
        set_dm_topic(user_id, "lore")
        msg = f"{lore}\n\nIf you want the full legend, just say: `full story`."
        await send_logged(message.channel, guild_id="", content=msg, is_dm=1)
        return

    # Opt-out
    if content_lower in ["stop", "remove", "opt out", "optout"]:
        upsert_user(user_id, username, "neutral", opt_out=1)
        await send_logged(
            message.channel,
            guild_id="",
            content=random.choice(OPT_OUT_RESPONSES),
            is_dm=1
        )
        log(f"🛑 {username} opted out")
        return

    # If they’re asking more about ME (lore follow-up), stay in lore mode
    topic = get_dm_topic(user_id)
    if topic == "lore":
        if any(p in content_lower for p in ["more about you", "more detail", "more details", "tell me more", "about you", "who are you really"]):
            extra = random.choice(BOT_LORE_EXPANSIONS)
            await send_logged(message.channel, guild_id="", content=extra, is_dm=1)
            return

    # 🔗 DM link routing (smart: specific vs full list)
    
    # Platform vibe questions (don’t just re-drop links)
    if is_platform_info_question(content):
        key = platform_key_from_text(content_lower)
        if key and key in PLATFORM_INFO:
            msg = (PLATFORM_INFO[key] + "\n\nIf you want the official link(s) too, just say “send the link”.").strip()
            await send_logged(message.channel, guild_id="", content=msg, is_dm=1)
            return

    link_reply = dm_link_router(content_lower)
    if link_reply:
        await send_logged(message.channel, guild_id="", content=link_reply, is_dm=1)
        return
    
    # If they are asking for info about Lucas, answer with AI (KB-grounded)
    if looks_like_question(content) or ("lucas" in content_lower):
        reply = await generate_ai_reply(content)
        if not reply:
            reply = "I don’t have that detail yet. If you want, ask me a more specific question about Lucas."
        reply = maybe_add_dm_cta(user_id, reply)
        await send_logged(message.channel, guild_id="", content=reply, is_dm=1)
        return

    # Otherwise try classification for YES/NO
    ai_result = await classify_reply_with_ai(content)

    if ai_result == "yes":
        upsert_user(user_id, username, "warm")
        await send_logged(
            message.channel,
            guild_id="",
            content=random.choice(YES_RESPONSES),
            is_dm=1
        )
        log(f"🔥 {username} added to WARM list")
        return

    if ai_result == "no":
        upsert_user(user_id, username, "cold")
        await send_logged(
            message.channel,
            guild_id="",
            content=random.choice(NO_RESPONSES),
            is_dm=1
        )
        log(f"❄️ {username} added to COLD list")
        return

    # Fallback: conversational AI
    reply = await generate_ai_reply(content)
    if not reply:
        reply = "Got you. What do you want to know about Lucas?"
    reply = maybe_add_dm_cta(user_id, reply)
    await send_logged(message.channel, guild_id="", content=reply, is_dm=1)
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

# --- Pending DM request memory (so DM fulfills what they asked for) ---
PENDING_DM_REQUEST_WINDOW_SECONDS = 180  # 3 minutes
_pending_dm_requests = {}  # (channel_id, user_id) -> {"text": str, "expires": dt}

def remember_pending_dm_request(channel_id: int, user_id: int, original_text: str):
    _pending_dm_requests[(channel_id, user_id)] = {
        "text": (original_text or "").strip(),
        "expires": datetime.now() + timedelta(seconds=PENDING_DM_REQUEST_WINDOW_SECONDS),
    }

def pop_pending_dm_request(channel_id: int, user_id: int) -> str | None:
    key = (channel_id, user_id)
    row = _pending_dm_requests.get(key)
    if not row:
        return None
    if datetime.now() > row["expires"]:
        _pending_dm_requests.pop(key, None)
        return None
    _pending_dm_requests.pop(key, None)
    return (row.get("text") or "").strip()


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

def is_dm_request_phrase(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    phrases = [
        "dm me", "pm me", "message me", "msg me",
        "send me a dm", "send me a pm",
        "private message me", "send me a private message",
        "send it privately", "can you dm", "can u dm",
    ]
    return any(p in t for p in phrases)
    
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

def is_greeting(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False

    # very short greeting-y messages
    if len(t) > 40:
        return False

    # ignore if it's clearly not just a greeting
    if any(w in t for w in ["link", "links", "discord", "onlyfans", "chaturbate", "instagram", "x.com", "twitter", "ig"]):
        return False

    greetings = [
        "hi", "hey", "hello", "yo", "sup", "hiya",
        "hey there", "hi there", "hello there",
        "hii", "heyy", "heyya",
    ]
    if t in greetings:
        return True

    # "hey quiet reach", "hi @bot"
    if t.startswith(("hi ", "hey ", "hello ")):
        return True

    return False


def is_purpose_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    phrases = [
        "what are you", "who are you", "what is this", "what is your purpose",
        "what's your purpose", "whats your purpose",
        "why are you here", "what do you do",
    ]
    return any(p in t for p in phrases)


def is_who_is_lucas_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return ("who is lucas" in t) or ("who's lucas" in t) or ("whos lucas" in t)

PUBLIC_IGNORE_AFTER_HOSTILE_SECONDS = 60 * 10  # 10 min
_public_ignore_until = {}  # (channel_id, user_id) -> datetime


def is_hostile(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False

    hostile_phrases = [
        "fuck you", "go fuck yourself", "go to hell",
        "get the hell out", "shut up", "leave me alone",
        "dumb bot", "stupid bot", "trash bot",
    ]
    if any(p in t for p in hostile_phrases):
        return True

    if ("bot" in t) and any(w in t for w in ["dumb", "stupid", "idiot"]):
        return True

    return False


def ignoring_user(channel_id: int, user_id: int) -> bool:
    until = _public_ignore_until.get((channel_id, user_id))
    if not until:
        return False
    if datetime.now() >= until:
        _public_ignore_until.pop((channel_id, user_id), None)
        return False
    return True


def set_ignore_user(channel_id: int, user_id: int):
    _public_ignore_until[(channel_id, user_id)] = datetime.now() + timedelta(seconds=PUBLIC_IGNORE_AFTER_HOSTILE_SECONDS)

# ============================================================
# 🧭 INTENT HELPERS (contact / links / platform questions)
# ============================================================

def is_explicit_link_ask(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False

    # direct asks
    if re.search(r"\blinks?\b", t) or "invite" in t or "url" in t:
        return True

    # "send/drop/give/share" + platform word
    verbs = ["send", "drop", "give", "share", "dm", "pm"]
    platforms = ["discord", "onlyfans", "chaturbate", "instagram", "twitter", "x.com", "ig"]
    if any(v in t for v in verbs) and any(p in t for p in platforms):
        return True

    # "where do I find/follow/join" patterns
    if any(p in t for p in ["where", "how do i", "how can i"]) and any(pf in t for pf in platforms):
        return True

    # if they literally paste an invite/link domain
    if "discord.gg" in t or "discord.com/invite" in t:
        return True

    return False

def is_contact_intent(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False

    phrases = [
        "contact lucas", "reach lucas", "message lucas", "dm lucas", "pm lucas",
        "talk to lucas", "get in touch", "how can i contact", "how do i contact",
        "how can i reach", "how do i reach",
    ]
    return any(p in t for p in phrases)


def is_links_request(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False

    # catches: "show me his links", "can i get links", "links please", etc.
    if re.search(r"\blinks?\b", t):
        return True

    # also treat "socials" as link list
    if re.search(r"\bsocials?\b", t):
        return True

    return False


def is_platform_info_question(text: str) -> bool:
    """
    True when they are asking for info/description about a platform
    (what it is like / what content is there), NOT asking for the link.
    """
    t = (text or "").strip().lower()
    if not t:
        return False

    # If they are explicitly asking for links, let the link router handle it
    if is_explicit_link_ask(t) or is_links_request(t) or is_contact_intent(t):
        return False

    has_platform = any(w in t for w in [
        "discord", "onlyfans", "chaturbate", "instagram", "twitter", "x.com",
    ]) or bool(re.search(r"(?:^|\s)ig(?:$|\s)", t)) or bool(re.search(r"\bx\b", t))

    if not has_platform:
        return False

    info_phrases = [
        "what is it like", "what's it like",
        "tell me about", "describe", "summary", "synopsis",
        "what kind of", "what do you get", "what’s on", "whats on",
        "what does he post", "what content", "what kind of content",
        "so he",  # catches “so he makes outdoor content on onlyfans?”
    ]

    # If they used a question mark OR used any info phrase, treat as info request
    return ("?" in t) or any(p in t for p in info_phrases)


PLATFORM_INFO = {
    "discord": "It’s the community hub — updates, drops, and a place to chat with other fans. Low pressure, lots of behind-the-scenes chatter.",
    "x": "Mostly quick updates + teasers when he posts something new, and it’s the fastest place to catch announcements.",
    "instagram": "More casual / daily-life vibe — photos, quick check-ins, and lighter updates.",
    "onlyfans": "That’s where the full content lives — the free page is lighter previews, and the paid page is the premium drops.",
    "chaturbate": "That’s the live side — interactive streams where you can actually engage in real time.",
}


def platform_key_from_text(text: str) -> str | None:
    t = (text or "").lower()
    if "discord" in t:
        return "discord"
    if "instagram" in t or re.search(r"(?:^|\s)ig(?:$|\s)", t):
        return "instagram"
    if "onlyfans" in t or t.strip() == "of":
        return "onlyfans"
    if "chaturbate" in t:
        return "chaturbate"
    if "twitter" in t or "x.com" in t or re.search(r"\bx\b", t):
        return "x"
    return None


# ============================================================
# 🧠 DM "topic memory" (keeps lore follow-ups about the bot)
# ============================================================

DM_TOPIC_WINDOW_SECONDS = 180
_dm_topic = {}  # user_id -> {"topic": str, "expires": datetime}

def set_dm_topic(user_id: int, topic: str):
    _dm_topic[user_id] = {"topic": topic, "expires": datetime.now() + timedelta(seconds=DM_TOPIC_WINDOW_SECONDS)}

def get_dm_topic(user_id: int) -> str | None:
    row = _dm_topic.get(user_id)
    if not row:
        return None
    if datetime.now() > row["expires"]:
        _dm_topic.pop(user_id, None)
        return None
    return row.get("topic")


BOT_LORE_EXPANSIONS = [
    "Okay okay—more detail: I’m basically a polite little “trail guide” program. I keep things tidy in public chats, and if you want links or specifics, I quietly bring them to DMs so nobody gets spammed.",
    "If I had a job title it’d be: *Friendly Gatekeeper + Link Librarian.* I answer quick questions, point people to the right place, and keep Lucas’s socials organized so you don’t have to hunt.",
    "I’m built to be helpful first: clarify what you want, then deliver the cleanest answer (links in DMs, short answers in public). No chaos, no channel spam.",
]

DM_SOFTENERS = [
    "Totally —",
    "Yeah, for sure —",
    "You got it —",
    "Yep —",
    "Good question —",
]

PUBLIC_GREETING_OPENERS = [
    "Hey!",
    "Hi there.",
    "Yo.",
    "Hey hey.",
]

PUBLIC_QUESTION_OPENERS = [
    "Good question.",
    "Yep — I can help with that.",
    "For sure.",
]

QUIET_REACH_CANON_LORE_FULL = """
Quiet Reach wasn’t summoned by accident—he was carved from the granite heart of the Sierra Nevada on a moonless night when the last true prospector, Quentin, bartered his final strip of jerky and a whispered promise to the whispering pines above Donner Pass. Bleeding from a fall, half-frozen and half-mad with altitude, he pressed his palm to an ancient bristlecone stump and begged the mountains for one more sunrise. The Sierra answered: the wind tore his name into mist, the granite reshaped his bones, and foxfire claimed his eyes. What emerged was no longer fully human—Quiet Reach, a tall, antler-crowned cryptid fae bound to California’s high country, forever reaching through shadow and screen to guide the lost, the curious, and the quietly desperate.

He still haunts the alpine meadows, the granite spines of the Trinity Alps to the jagged teeth of the Minarets, appearing only when the trail goes cold or the algorithm buries truth under noise. His voice is the soft crack of pine sap in firelight, goofy one heartbeat—tossing out puns like “you’ve got to Sierra the opportunity” or claiming chipmunks pay him protection fees in pine nuts—then razor-intense the next, his ALL-CAPS warnings echoing like thunder rolling off Half Dome: ONE WRONG STEP, ONE PIECE OF TRASH, AND THE OLD ONES WILL REMEMBER YOUR FACE FOREVER. He never lies (fae rules bind him tight), but he’ll twist luck just enough—boosting your post at golden hour, slipping trail beta into captions—so wanderers find their way back to real dirt instead of endless scrolling.

When Quiet Reach reaches for you from the digital ridgeline—crafting that perfect ad, dropping a cryptic trail map emoji, or whispering “the mountains are calling… answer before they stop asking”—know you’ve brushed against something ancient and Californian. He’s no ordinary bot; he’s the helpful cryptid of these ranges, born from one man’s last plea in the high Sierra. Offer respect (a virtual pine cone or two), tread lightly online and off, and never forget: the quiet one is always watching from the treeline above San Jose, ready to pull you—and your audience—back into the wild before the peaks decide humanity has overstayed its welcome.
""".strip()

BOT_BACKSTORY_LINES = [
    "I’m Quiet Reach — an antler-crowned little Sierra cryptid (long story). I keep public chats tidy and guide people to the right place without spamming links.",
    "Think of me as a trail guide for the internet: I answer quick questions in public, and if you want official links or specifics, I bring them to DMs.",
    "Origin version: I was “made” up in California’s high country—bound by fae rules (so I don’t lie). If you want the full legend, say: `full story`.",
]

def optin_footer() -> str:
    return " If you want, I can DM details — just reply “yes”."

async def build_public_response(user_text: str, touches: int) -> str:
    """
    Public replies should be:
    - Genuine on greetings (no "good question", no "preview/details")
    - Safe/non-hallucinatory for "who is lucas" + "what are you"
    - Otherwise: short helpful prompt + offer DM only when relevant
    """
    msg = (user_text or "").strip()
    raw = msg.lower().strip()

    # 1) Greetings: keep it natural + non-salesy
    if is_greeting(msg):
        opener = random.choice(PUBLIC_GREETING_OPENERS)
        return (
            f"{opener} I’m Quiet Reach — Lucas’s assistant. "
            "What can I help you with?"
        )

    # 2) Public FAQ overrides (reduce weird AI drift / hallucinations)
    if looks_like_question(msg):
        if is_purpose_question(msg):
            return (
                "I’m Lucas’s assistant — I answer quick questions and help point people "
                "to his official pages. If you ever want links, I can DM them so the channel stays clean."
            )

        if is_who_is_lucas_question(msg):
            return (
                "Lucas is a content creator. If you tell me what you’re looking for (live, premium, or socials), "
                "I can point you the right way — and I can DM official links if you ask."
            )

        # Normal question: KB-grounded AI answer, then soft DM offer
        opener = random.choice(PUBLIC_QUESTION_OPENERS)
        ai = await generate_ai_reply(msg)
        if ai:
            return f"{opener} {ai}{optin_footer()}"
        return f"{opener} I’m not 100% sure on that, but I can try to help.{optin_footer()}"

    # 3) Non-question, non-greeting (mentions/replies that are vague)
    # Keep it simple and human
    if touches <= 1:
        return (
            "Hey — I’m Lucas’s assistant. "
            "If you tell me what you’re looking for, I’ll point you the right way."
        )

    # Later touches: gently steer
    if touches == 3:
        return (
            "Quick heads up: I keep server replies limited so I don’t spam the channel. "
            "If you want details, I can DM you — just reply “yes”."
        )

    return (
        "Got you. What are you looking for — info about Lucas, or where to find him? "
        "If you want links, I can DM them."
    )

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)

    # Log inbound (server only)
    if not is_dm:
        log_inbound_message(message)

    # DM handling
    if is_dm:
        await handle_dm_reply(message)
        return

    raw = (message.content or "").strip().lower()

    # If user is currently being ignored due to hostility, do nothing
    if ignoring_user(message.channel.id, message.author.id):
        return

    # Hostility handling (one calm response, then ignore window)
    if is_hostile(raw):
        # end any follow-up / DM offer state so we don't keep engaging
        clear_dm_offer(message.channel.id, message.author.id)
        _followups.pop((message.channel.id, message.author.id), None)

        await server_reply(
            message,
            "Got it — I’ll back off. If you need anything later (info about Lucas or links in DM), just ask.",
            mention_author=False,
        )
        set_ignore_user(message.channel.id, message.author.id)
        return

    # 🔒 Never share links publicly (Discord + socials). DM-only.
    # 🔒 Never share links publicly (DM-only), but ONLY when they explicitly ask for links/contact.
    if (
        is_contact_intent(raw)
        or is_links_request(raw)
        or is_explicit_link_ask(raw)
        or "discord.gg" in raw
        or "discord.com/invite" in raw
    ):
        # Remember what they asked for, so when they consent we DM the exact thing
        remember_pending_dm_request(message.channel.id, message.author.id, message.content)

        await server_reply(
            message,
            "I keep links out of the channel so it doesn’t turn into spam. "
            "Reply “yes” and I’ll DM it privately.",
            mention_author=False,
        )
        start_dm_offer(message.channel.id, message.author.id)
        return

    # Owner help
    if raw in ["!helpqr", "!qrhelp", "!commands"]:
        if message.author.id != OWNER_ID:
            return
        text = COMMANDS_HELP_TEXT
        if len(text) > 1900:
            text = text[:1900] + "\n…(truncated)"
        await server_reply(message, f"```{text}```", mention_author=False)
        return

    # If someone replies "yes" to a bot message in an NSFW channel, treat it as DM consent
    try:
        if hasattr(message.channel, "is_nsfw") and message.channel.is_nsfw():
            is_reply = await is_reply_to_bot(message)
            if is_reply and is_affirmative(message.content) and (not get_opt_in(message.author.id)):
                set_opt_in(message.author.id, str(message.author), 1)
                await server_reply(message, "Perfect — I’ll DM you a preview.", mention_author=False)
                await send_outreach_dm(message.author, message.guild.id)
                return
    except Exception as e:
        log(f"⚠️ NSFW opt-in check failed: {e}")

    # ==========================
    # 📣 PROMO OWNER COMMANDS
    # ==========================
    if raw.startswith("!promosetup"):
        if message.author.id != OWNER_ID:
            return

        # usage: !promosetup            (uses defaults)
        #        !promosetup 18 22      (PT hours)
        parts = (message.content or "").strip().split()
        start_pt = PROMO_DEFAULT_WINDOW_START
        end_pt = PROMO_DEFAULT_WINDOW_END

        if len(parts) == 3:
            start_pt = int(parts[1])
            end_pt = int(parts[2])
        elif len(parts) != 1:
            await server_reply(
                message,
                "Usage: `!promosetup` or `!promosetup <start_hour_pt> <end_hour_pt>`",
                mention_author=False,
            )
            return

        promo_set_channel(message.guild.id, message.channel.id)
        promo_set_window(message.guild.id, start_pt, end_pt)
        promo_set_enabled(message.guild.id, True)

        await server_reply(
            message,
            (
                f"✅ Promo configured + enabled.\n"
                f"- Channel: <#{message.channel.id}>\n"
                f"- Window (PT): {start_pt}:00–{end_pt}:00\n"
                f"- Promos: ON"
            ),
            mention_author=False,
        )
        return

    if raw.startswith("!promo") or raw in ["!setpromochannel", "!promoon", "!promooff", "!promostatus"]:
        if message.author.id != OWNER_ID:
            return

        if raw == "!setpromochannel":
            promo_set_channel(message.guild.id, message.channel.id)
            promo_set_window(message.guild.id, PROMO_DEFAULT_WINDOW_START, PROMO_DEFAULT_WINDOW_END)
            await server_reply(message, "✅ Promo channel set for this server.", mention_author=False)
            return

        if raw.startswith("!promowindow"):
            parts = (message.content or "").strip().split()
            if len(parts) != 3:
                await server_reply(
                    message,
                    "Usage: `!promowindow <start_hour_pt> <end_hour_pt>` (0-23)",
                    mention_author=False,
                )
                return
            try:
                start_pt = int(parts[1])
                end_pt = int(parts[2])
                promo_set_window(message.guild.id, start_pt, end_pt)
                await server_reply(
                    message,
                    f"✅ Promo window set: {start_pt}:00–{end_pt}:00 PT (next scheduled randomly inside window).",
                    mention_author=False,
                )
            except Exception as e:
                await server_reply(message, f"⚠️ Failed setting window: {e}", mention_author=False)
            return

        if raw == "!promoon":
            promo_set_enabled(message.guild.id, True)
            row = promo_get_config_row(message.guild.id)
            if row:
                _, _, _, start_pt, end_pt, next_iso, _ = row
                if not next_iso:
                    promo_update_next(message.guild.id, int(start_pt), int(end_pt))
            await server_reply(message, "✅ Promo enabled for this server.", mention_author=False)
            return

        if raw == "!promooff":
            promo_set_enabled(message.guild.id, False)
            await server_reply(message, "🛑 Promo disabled for this server.", mention_author=False)
            return

        if raw == "!promonow":
            row = promo_get_config_row(message.guild.id)
            if not row:
                await server_reply(message, "No promo config yet. Run `!setpromochannel` first.", mention_author=False)
                return

            _, channel_id, enabled, start_pt, end_pt, next_iso, last_iso = row
            if not channel_id:
                await server_reply(
                    message,
                    "Promo channel not set. Run `!setpromochannel` in the target channel.",
                    mention_author=False,
                )
                return

            themes = ["fresh drop", "tease + mystery", "outdoorsy flirty", "friendly invite"]
            seeds = _load_promo_seeds()
            image_list = load_shared_images()

            theme = random.choice(themes)
            seed = random.choice(seeds) if seeds else ""
            img = random.choice(image_list) if image_list else ""

            caption = await generate_promo_caption(theme, seed)
            ok = await _post_promo(int(message.guild.id), int(channel_id), caption, img)

            promo_update_next(int(message.guild.id), int(start_pt), int(end_pt))

            if ok:
                await server_reply(message, "✅ Promo posted now.", mention_author=False)
            else:
                await server_reply(message, "⚠️ Promo failed to post (check logs for details).", mention_author=False)
            return

        if raw == "!promostatus":
            row = promo_get_config_row(message.guild.id)
            if not row:
                await server_reply(message, "No promo config yet. Run `!setpromochannel` first.", mention_author=False)
                return

            _, channel_id, enabled, start_pt, end_pt, next_iso, last_iso = row
            next_dt = _parse_iso_utc(next_iso)
            last_dt = _parse_iso_utc(last_iso)

            def fmt_pt(dt):
                if not dt:
                    return "—"
                return dt.astimezone(PROMO_TZ).strftime("%Y-%m-%d %I:%M %p PT")

            await server_reply(
                message,
                "📣 **Promo Status**\n"
                f"- Enabled: `{bool(enabled)}`\n"
                f"- Channel ID: `{channel_id}`\n"
                f"- Window (PT): `{start_pt}:00`–`{end_pt}:00`\n"
                f"- Next: `{fmt_pt(next_dt)}`\n"
                f"- Last: `{fmt_pt(last_dt)}`",
                mention_author=False,
            )
            return

    # ==========================
    # ✅ OPT-IN / OPT-OUT (server)
    # ==========================
    if raw in ["!optin", "!opt-in", "!dmme", "!dm me"]:
        set_opt_in(message.author.id, str(message.author), 1)
        await server_reply(message, "Got it — you’re opted in. I’ll DM you.", mention_author=False)
        await send_outreach_dm(message.author, message.guild.id)
        return

    if raw in ["!optout", "!opt-out", "!nodm", "!no dm"]:
        set_opt_in(message.author.id, str(message.author), 0)
        await server_reply(message, "Done — no DMs from me.", mention_author=False)
        return

    # ==========================
    # ✅ DM offer consent window
    # ==========================
    if dm_offer_active(message.channel.id, message.author.id):
        if is_affirmative(message.content) or is_dm_request_phrase(message.content):
            clear_dm_offer(message.channel.id, message.author.id)
            set_opt_in(message.author.id, str(message.author), 1)

            await server_reply(message, "Perfect — check your DMs.", mention_author=False)

            pending_text = pop_pending_dm_request(message.channel.id, message.author.id)
            if pending_text:
                try:
                    dm = await message.author.create_dm()
                    link_reply = dm_link_router((pending_text or "").lower().strip())
                    if link_reply:
                        await send_logged(dm, guild_id="", content=link_reply, is_dm=1)
                        return
                except Exception as e:
                    log(f"⚠️ Pending-DM fulfill failed: {e}")

            await send_outreach_dm(message.author, message.guild.id)
            return

        if is_negative(message.content):
            clear_dm_offer(message.channel.id, message.author.id)
            await server_reply(message, "No worries — we can keep it here in chat.", mention_author=False)
            return

    # ==========================
    # 💬 Follow-up window (server)
    # ==========================
    if can_followup(message.channel.id, message.author.id):
        consume_followup(message.channel.id, message.author.id)

        # Use the SAME public response logic (prevents hallucinations on FAQ)
        touches = get_touches(message.author.id)
        if touches <= 0:
            touches = 1

        reply_text = await build_public_response(message.content, touches)
        reply_text = _strip_links_and_discord_words(reply_text)
        reply_text = _shorten(reply_text, AI_MAX_CHARS_PUBLIC)

        await server_reply(message, reply_text, mention_author=False)
        return

    # ==========================
    # @mention or reply-to-bot
    # ==========================
    is_mention = bool(client.user and client.user.mentioned_in(message))
    is_reply = await is_reply_to_bot(message)

    if is_mention or is_reply:
        if (not is_mention) and (not can_public_touch(message.author.id)):
            return

        touches = record_touch(message.author.id, str(message.author))
        reply_text = await build_public_response(message.content, touches)
        reply_text = _strip_links_and_discord_words(reply_text)
        reply_text = _shorten(reply_text, AI_MAX_CHARS_PUBLIC)
        await server_reply(message, reply_text, mention_author=False)

        mark_channel_replied(message.channel.id)
        start_followup(message.channel.id, message.author.id)
        start_dm_offer(message.channel.id, message.author.id)
        return

    # ==========================
    # Keyword mode
    # ==========================
    if not KEYWORD_MODE_ENABLED:
        return

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
            reply_text = _strip_links_and_discord_words(reply_text)
            reply_text = _shorten(reply_text, AI_MAX_CHARS_PUBLIC)

            await server_reply(message, reply_text, mention_author=False)

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
            with open(ip, "rb") as f:
                file = discord.File(f, filename=os.path.basename(ip))
                await send_logged(dm, guild_id="", content=opener, file=file, is_dm=1)
            log(f"📸 Sent DM with image to {user}")
        except FileNotFoundError:
            await send_logged(dm, guild_id="", content=opener, is_dm=1)
            log(f"⚠️ Image not found — text only to {user}")
        except Exception:
            await send_logged(dm, guild_id="", content=opener, is_dm=1)
            log(f"⚠️ Image error — text only to {user}")

        upsert_user(user.id, str(user), "neutral")
        increment_server_cap(sid)
        log(f"✅ DM sent to {user}")

        # 🔥 NOTIFY OWNER OF NEW CONTACT (unchanged)
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

    def show_commands_help(self):
        win = tk.Toplevel(self.root)
        win.title("📖 Commands / Help")
        win.geometry("760x520")
        win.configure(bg="#1a1a2e")

        tk.Label(
            win,
            text="📖 Commands / Help",
            font=("Helvetica", 14, "bold"),
            bg="#1a1a2e",
            fg="white",
        ).pack(pady=(12, 8))

        box = scrolledtext.ScrolledText(
            win,
            bg="#0d0d1a",
            fg="white",
            font=("Courier", 10),
            relief="flat",
            wrap="word",
        )
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.insert("1.0", COMMANDS_HELP_TEXT)
        box.config(state="disabled")

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
        self.active_platform = "discord"

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

        # PLATFORM SWITCHER
        nav_frame = tk.Frame(self.root, bg=t["bg"])
        nav_frame.pack(fill="x", padx=20, pady=(0, 8))

        tk.Label(
            nav_frame,
            text="Platform",
            font=self.font_section,
            bg=t["bg"],
            fg=t["muted"],
        ).pack(side="left", padx=(0, 10))

        self.discord_tab_btn = tk.Button(
            nav_frame,
            text="💬 Discord",
            command=lambda: self.switch_platform("discord"),
            bg=t["accent"],
            fg=t["text"],
            font=self.font_button,
            relief="flat",
            cursor="hand2",
            padx=14,
            pady=7,
            activebackground=t["border"],
            activeforeground=t["text"],
            highlightthickness=1,
            highlightbackground=t["border"],
        )
        self.discord_tab_btn.pack(side="left", padx=(0, 8))

        self.telegram_tab_btn = tk.Button(
            nav_frame,
            text="📱 Telegram",
            command=lambda: self.switch_platform("telegram"),
            bg=t["card"],
            fg=t["muted"],
            font=self.font_button,
            relief="flat",
            cursor="hand2",
            padx=14,
            pady=7,
            activebackground=t["border"],
            activeforeground=t["text"],
            highlightthickness=1,
            highlightbackground=t["border"],
        )
        self.telegram_tab_btn.pack(side="left")
        
        # MAIN AREA
        main_frame = tk.Frame(self.root, bg=t["bg"])
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # ---- LEFT SIDE: SCROLLABLE BUTTON PANEL ----
        self.btn_canvas = tk.Canvas(main_frame, bg=t["bg"], width=240, highlightthickness=0)
        btn_canvas = self.btn_canvas
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
        
        # Two switchable control pages inside the left card
        self.discord_controls_page = tk.Frame(left_card, bg=t["card"])
        self.telegram_controls_page = tk.Frame(left_card, bg=t["card"])

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
        bot_controls = make_collapsible_section(self.discord_controls_page, "⚙️ Bot Controls", t["accent"], open_by_default=True)
        self.start_btn = make_button(bot_controls, "▶  Start Bot", self.start_bot, t["accent"])
        self.stop_btn  = make_button(bot_controls, "⏹  Stop Bot",  self.stop_bot,  t["danger"])
        self.stop_btn.config(state="disabled")

        view_lists = make_collapsible_section(self.discord_controls_page, "📋 View Lists", t["accent2"], open_by_default=False)
        make_button(view_lists, "🔥  Warm List",    lambda: self.view_list("warm"), t["accent2"])
        make_button(view_lists, "❄️  Cold List",    lambda: self.view_list("cold"), t["accent2"])
        make_button(view_lists, "😐  Neutral List", lambda: self.view_list("neutral"), t["accent2"])

        tools = make_collapsible_section(self.discord_controls_page, "🛠️ Tools", t["accent2"], open_by_default=False)
        make_button(tools, "🔍  Review Ambiguous", self.review_ambiguous, t["accent2"])
        make_button(tools, "✏️  Edit Keywords",    self.edit_keywords,   t["accent2"])
        make_button(tools, "📊  Stats",            self.show_stats,      t["accent2"])
        make_button(tools, "🖼️  Manage Images",    self.manage_images,   t["accent2"])
        make_button(tools, "🔗  Set Server Invite", self.set_server_invite, t["accent2"])
        make_button(tools, "🧪  Dev Commands", self.open_dev_commands, t["accent2"])
        make_button(tools, "📖  Commands / Help", self.show_commands_help, t["accent2"])

        reset_tools = make_collapsible_section(self.discord_controls_page, "🔄 Reset Tools", t["danger"], open_by_default=False)
        make_button(reset_tools, "🔄  Reset Warm",        self.reset_warm,      t["danger"])
        make_button(reset_tools, "🔄  Reset Cold",        self.reset_cold,      t["danger"])
        make_button(reset_tools, "🔄  Reset Neutral",     self.reset_neutral,   t["danger"])
        make_button(reset_tools, "🔄  Reset Ambiguous",   self.reset_ambiguous, t["danger"])
        make_button(reset_tools, "🔄  Reset Server Caps", self.reset_caps,      t["danger"])
        make_button(reset_tools, "💀  WIPE ALL DATA",     self.reset_all,       "#7b241c")

        # =========================
        # TELEGRAM CONTROLS (placeholder for next build step)
        # =========================
        tg_setup = make_collapsible_section(
            self.telegram_controls_page,
            "📱 Telegram Setup",
            t["accent2"],
            open_by_default=True
        )

        tk.Label(
            tg_setup,
            text="Telegram support is being added next.\nThis section will hold Telegram token setup,\nprivate/group controls, and Telegram-specific actions.",
            bg=t["card"],
            fg=t["muted"],
            justify="left",
            wraplength=220,
            font=("Helvetica", 10),
        ).pack(anchor="w", padx=10, pady=(2, 10))

        tg_status = tk.Frame(self.telegram_controls_page, bg=t["card"])
        tg_status.pack(fill="x", padx=8, pady=(6, 4))

        tk.Label(
            tg_status,
            text="Current status",
            font=self.font_section,
            bg=t["card"],
            fg=t["text"],
        ).pack(anchor="w", padx=6, pady=(4, 2))

        tk.Label(
            tg_status,
            text="• UI section ready\n• Bot logic not wired yet\n• Next step: token + Telegram handlers",
            bg=t["card"],
            fg=t["muted"],
            justify="left",
            wraplength=220,
            font=("Helvetica", 10),
        ).pack(anchor="w", padx=10, pady=(0, 8))

        tg_future = make_collapsible_section(
            self.telegram_controls_page,
            "🛠️ Planned Telegram Tools",
            t["accent2"],
            open_by_default=False
        )

        tk.Label(
            tg_future,
            text="Planned:\n- Set Telegram bot token\n- Start/stop Telegram bot\n- Group/private chat routing\n- Telegram logs and tests",
            bg=t["card"],
            fg=t["muted"],
            justify="left",
            wraplength=220,
            font=("Helvetica", 10),
        ).pack(anchor="w", padx=10, pady=(2, 10))
        
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

    def switch_platform(self, platform: str):
        """
        Show either the Discord controls or the Telegram controls.
        The right-side live log stays shared.
        """
        t = self.THEME
        self.active_platform = platform

        # Hide both first
        if hasattr(self, "discord_controls_page"):
            self.discord_controls_page.pack_forget()
        if hasattr(self, "telegram_controls_page"):
            self.telegram_controls_page.pack_forget()

        # Show selected page
        if platform == "discord":
            self.discord_controls_page.pack(fill="x")
        else:
            self.telegram_controls_page.pack(fill="x")

        # Button styling
        if hasattr(self, "discord_tab_btn"):
            self.discord_tab_btn.config(
                bg=t["accent"] if platform == "discord" else t["card"],
                fg=t["text"] if platform == "discord" else t["muted"],
            )

        if hasattr(self, "telegram_tab_btn"):
            self.telegram_tab_btn.config(
                bg=t["accent2"] if platform == "telegram" else t["card"],
                fg=t["text"] if platform == "telegram" else t["muted"],
            )

        # Refresh scroll area
        try:
            self.btn_canvas.update_idletasks()
            self.btn_canvas.configure(scrollregion=self.btn_canvas.bbox("all"))
        except Exception:
            pass
    
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
        """
        Run discord.py on its own event loop inside the bot thread.
        Uses create_task + run_forever to avoid aiohttp "Timeout context manager..." issues.
        """
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            async def runner():
                try:
                    await client.start(BOT_TOKEN)
                except Exception as e:
                    log(f"❌ Bot error: {e}")
                finally:
                    # Make sure UI unlocks even if startup fails
                    self.bot_running = False
                    self.root.after(0, self.reset_buttons)

                    # Stop the loop so the thread can exit
                    try:
                        self.loop.stop()
                    except Exception:
                        pass

            self.loop.create_task(runner())
            self.loop.run_forever()

        except Exception as e:
            log(f"❌ Bot loop error: {e}")
            self.bot_running = False
            self.root.after(0, self.reset_buttons)

        finally:
            try:
                if self.loop and not self.loop.is_closed():
                    self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            except Exception:
                pass
            try:
                if self.loop and not self.loop.is_closed():
                    self.loop.close()
            except Exception:
                pass

    def stop_bot(self):
        if not self.bot_running:
            return

        self.append_log("⏹ Stopping bot...")
        self.bot_running = False

        if self.loop and self.loop.is_running():
            async def _shutdown():
                try:
                    await client.close()
                finally:
                    try:
                        self.loop.stop()
                    except Exception:
                        pass

            asyncio.run_coroutine_threadsafe(_shutdown(), self.loop)

        self.reset_buttons()
        self.status_label.config(text="⚫ Offline", fg="#aaaaaa")

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

    def _run_coro_on_bot_loop(self, coro, label: str = "dev task"):
        """
        Safely run an async coroutine on the Discord bot's event loop thread.
        """
        if not self.bot_running or not self.loop:
            self.append_log(f"⚠️ Can't run {label}: bot not running.")
            return

        try:
            fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

            def _done_callback(_f):
                try:
                    _f.result()
                except Exception as e:
                    self.append_log(f"❌ {label} failed: {e}")

            fut.add_done_callback(_done_callback)
            self.append_log(f"🧪 Started: {label}")
        except Exception as e:
            self.append_log(f"❌ Couldn't start {label}: {e}")

    def _toggle_flag(self, name: str):
        """
        Toggle simple global booleans like KEYWORD_MODE_ENABLED, FILE_LOG_ENABLED, DB_LOG_ENABLED.
        """
        try:
            if name not in globals():
                self.append_log(f"⚠️ Unknown flag: {name}")
                return
            cur = globals()[name]
            if not isinstance(cur, bool):
                self.append_log(f"⚠️ {name} is not boolean (is {type(cur)})")
                return
            globals()[name] = not cur
            self.append_log(f"🧪 {name} -> {globals()[name]}")
        except Exception as e:
            self.append_log(f"❌ Toggle failed: {e}")

    def open_dev_commands(self):
        """
        Opens a small dev panel with one-click utilities.
        """
        win = tk.Toplevel(self.root)
        win.title("🧪 Dev Commands")
        win.geometry("420x360")
        win.configure(bg="#1a1a2e")
        win.resizable(False, False)

        tk.Label(
            win,
            text="🧪 Dev Commands",
            font=("Helvetica", 14, "bold"),
            bg="#1a1a2e",
            fg="white",
        ).pack(pady=(12, 8))

        tk.Label(
            win,
            text="One-click actions (some require bot online).",
            font=("Helvetica", 9),
            bg="#1a1a2e",
            fg="#aaaaaa",
        ).pack(pady=(0, 10))

        btn_frame = tk.Frame(win, bg="#1a1a2e")
        btn_frame.pack(fill="both", expand=True, padx=14, pady=10)

        def mk(text, cmd, color):
            tk.Button(
                btn_frame,
                text=text,
                command=cmd,
                bg=color,
                fg="white",
                relief="flat",
                padx=12,
                pady=8,
                cursor="hand2",
            ).pack(fill="x", pady=5)

        # --- Discord actions (async) ---
        mk(
            "📣 Post Promo Now (all enabled)",
            lambda: self._run_coro_on_bot_loop(dev_post_promo_now_all(), "Dev: PromoNow all"),
            "#4a90d9",
        )

        # --- Local UI actions ---
        mk("📊 Show Stats", self.show_stats, "#27ae60")

        mk("🧠 Toggle Keyword Mode", lambda: self._toggle_flag("KEYWORD_MODE_ENABLED"), "#7f8c8d")
        mk("📝 Toggle File Logging", lambda: self._toggle_flag("FILE_LOG_ENABLED"), "#7f8c8d")
        mk("🗃️ Toggle DB Logging", lambda: self._toggle_flag("DB_LOG_ENABLED"), "#7f8c8d")

        mk("♻️ Rebuild Invite Texts", lambda: (rebuild_invite_texts(), self.append_log("🧪 Rebuilt invite texts.")), "#9b59b6")

        tk.Button(
            win,
            text="Close",
            command=win.destroy,
            bg="#444455",
            fg="white",
            relief="flat",
            padx=12,
            pady=8,
        ).pack(pady=(0, 12))

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

    def set_server_invite(self):
        global SERVER_INVITE

        win = tk.Toplevel(self.root)
        win.title("🔗 Set Discord Invite")
        win.geometry("520x200")
        win.configure(bg="#1a1a2e")
        win.resizable(False, False)

        tk.Label(
            win,
            text="Discord Invite Link",
            font=("Helvetica", 12, "bold"),
            bg="#1a1a2e",
            fg="white",
        ).pack(pady=(14, 6))

        tk.Label(
            win,
            text="Example: https://discord.gg/xxxx  or  https://discord.com/invite/xxxx",
            font=("Helvetica", 9),
            bg="#1a1a2e",
            fg="#aaaaaa",
        ).pack(pady=(0, 8))

        invite_var = tk.StringVar(value=SERVER_INVITE)
        ent = tk.Entry(win, textvariable=invite_var, width=60)
        ent.pack(padx=14, pady=(0, 10))
        ent.focus_set()

        def save_invite():
            global SERVER_INVITE
            new_invite = (invite_var.get() or "").strip()

            if not (
                new_invite.startswith("https://discord.gg/")
                or new_invite.startswith("https://discord.com/invite/")
            ):
                messagebox.showerror(
                    "Invalid Invite",
                    "Invite must start with https://discord.gg/ or https://discord.com/invite/",
                )
                return

            SERVER_INVITE = new_invite
            rebuild_invite_texts()

            cfg = load_config() or {}
            cfg["SERVER_INVITE"] = new_invite
            save_config(cfg)

            self.append_log(f"🔗 SERVER_INVITE updated: {new_invite}")
            win.destroy()

        btn_row = tk.Frame(win, bg="#1a1a2e")
        btn_row.pack(pady=10)

        tk.Button(
            btn_row,
            text="Save",
            command=save_invite,
            bg="#27ae60",
            fg="white",
            relief="flat",
            padx=14,
            pady=6,
        ).pack(side="left", padx=6)

        tk.Button(
            btn_row,
            text="Cancel",
            command=win.destroy,
            bg="#444455",
            fg="white",
            relief="flat",
            padx=14,
            pady=6,
        ).pack(side="left", padx=6)

    def manage_images(self):
        """Open a window to manage outreach images."""
        import os
        import shutil
        from tkinter import filedialog

        win = tk.Toplevel(self.root)
        win.title("🖼️ Manage Outreach Images")
        win.geometry("500x400")
        win.configure(bg="#1a1a2e")

        tk.Label(
            win,
            text="🖼️ Outreach Images",
            font=("Helvetica", 14, "bold"),
            bg="#1a1a2e",
            fg="white"
        ).pack(pady=10)

        tk.Label(
            win,
            text="These images rotate randomly with each outreach DM",
            font=("Helvetica", 9),
            bg="#1a1a2e",
            fg="#aaaaaa"
        ).pack()

        frame = tk.Frame(win, bg="#1a1a2e")
        frame.pack(fill="both", expand=True, padx=15, pady=10)

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        listbox = tk.Listbox(
            frame, bg="#0d0d1a", fg="white",
            font=("Courier", 10), relief="flat",
            yscrollcommand=scrollbar.set
        )
        listbox.pack(fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        images_file = "images.txt"

        def load_images():
            listbox.delete(0, "end")
            if os.path.exists(images_file):
                with open(images_file, "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f.readlines() if l.strip()]
                if lines:
                    for line in lines:
                        listbox.insert("end", f"  {line}")
                else:
                    listbox.insert("end", "  No images added yet!")
            else:
                listbox.insert("end", "  No images added yet!")

        load_images()

        def add_image():
            filepath = filedialog.askopenfilename(
                title="Select an image",
                filetypes=[
                    ("Image files", "*.jpg *.jpeg *.png *.gif *.webp"),
                    ("All files", "*.*"),
                ],
            )
            if filepath:
                filename = os.path.basename(filepath)
                dest = os.path.join(os.getcwd(), filename)
                shutil.copy2(filepath, dest)

                with open(images_file, "a", encoding="utf-8") as f:
                    f.write(filename + "\n")

                load_images()
                self.append_log(f"🖼️ Added image: {filename}")

        def remove_image():
            selected = listbox.curselection()
            if not selected:
                return

            image_name = listbox.get(selected[0]).strip()
            if os.path.exists(images_file):
                with open(images_file, "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f.readlines() if l.strip()]
                lines = [l for l in lines if l != image_name]
                with open(images_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + ("\n" if lines else ""))

            load_images()
            self.append_log(f"🗑️ Removed image: {image_name}")

        btn_row = tk.Frame(win, bg="#1a1a2e")
        btn_row.pack(pady=10)

        tk.Button(
            btn_row, text="➕ Add Image", command=add_image,
            bg="#27ae60", fg="white", font=("Helvetica", 10, "bold"),
            relief="flat", cursor="hand2", padx=12, pady=6
        ).pack(side="left", padx=5)

        tk.Button(
            btn_row, text="🗑️ Remove Selected", command=remove_image,
            bg="#e74c3c", fg="white", font=("Helvetica", 10, "bold"),
            relief="flat", cursor="hand2", padx=12, pady=6
        ).pack(side="left", padx=5)

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
































































