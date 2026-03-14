# 🤫 QUIET REACH v1.2
import discord, tkinter as tk, sqlite3, asyncio, threading, random, os, json
from tkinter import ttk, scrolledtext, messagebox
import tkinter.font as tkfont
from datetime import datetime, date, timedelta
import requests

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

# Public engagement pacing
PUBLIC_TOUCH_COOLDOWN_SECONDS = 60 * 30   # 30 minutes per user
NUDGE_AFTER_TOUCHES = 2                   # after N touches, start nudging opt-in

def load_kb() -> str:
    try:
        with open(KB_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

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

    c.commit()
    c.close()
    print("✅ Database ready!")

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

        # Load images
        import os
        if os.path.exists('images.txt'):
            with open('images.txt', 'r') as f:
                image_list = [l.strip() for l in f.readlines() if l.strip()]
        else:
            image_list = ['preview.jpg']
        ip = random.choice(image_list) if image_list else None

        try:
            with open(ip, 'rb') as f:
                await dm.send(content=opener, file=discord.File(f, filename=ip))
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
































































