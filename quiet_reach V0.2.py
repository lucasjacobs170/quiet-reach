# 🤫 QUIET REACH v1.2
import discord, tkinter as tk, sqlite3, asyncio, threading, random
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime, date
import os
import requests

BOT_TOKEN=''
OWNER_ID=434809771124719616
SERVER_INVITE='https://discord.gg/yAvVewhD3c'
DB_PATH='quiet_reach.db'
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
ABOUT_LUCAS = f"""
You are a helpful assistant for Lucas Jacobs.

Goal:
- Answer questions about Lucas and his content.
- Be friendly and concise.

Rules:
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

def setup_database():
    c=sqlite3.connect(DB_PATH);k=c.cursor()
    k.execute('CREATE TABLE IF NOT EXISTS users(discord_id TEXT PRIMARY KEY,username TEXT,list_type TEXT DEFAULT "neutral",last_contacted TEXT,opt_out INTEGER DEFAULT 0)')
    k.execute('CREATE TABLE IF NOT EXISTS server_caps(server_id TEXT,date TEXT,dm_count INTEGER DEFAULT 0,PRIMARY KEY(server_id,date))')
    k.execute('CREATE TABLE IF NOT EXISTS keywords(word TEXT PRIMARY KEY,list_name TEXT)')
    k.execute("SELECT COUNT(*)FROM keywords")
    if k.fetchone()[0]==0:
        for w,l in[('thirsty','trigger'),('live','trigger'),('of','trigger'),('cam','trigger'),('preview','trigger'),('link','trigger'),('yes','yes'),('yep','yes'),('sure','yes'),('yeah','yes'),('ok','yes'),('interested','yes'),('tell me more','yes'),('lmk','yes'),('facts','yes'),('no','no'),('nah','no'),('pass','no'),('no thanks','no'),('not interested','no'),('stop','no'),('leave me alone','no'),('nope','no')]:
            k.execute("INSERT INTO keywords VALUES(?,?)",(w,l))
    k.execute('CREATE TABLE IF NOT EXISTS ambiguous(id INTEGER PRIMARY KEY AUTOINCREMENT,discord_id TEXT,username TEXT,message TEXT,timestamp TEXT)')
    c.commit();c.close();print("✅ Database ready!")

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

async def classify_reply_with_ai(user_message: str) -> str:
    # quick keyword fallback first (no model call)
    msg = (user_message or "").lower()
    if any(w in msg for w in get_keywords("yes")):
        return "yes"
    if any(w in msg for w in get_keywords("no")):
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

User message:
\"\"\"{user_message}\"\"\"

Write the best possible reply now.
"""
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, lambda: ollama_generate(prompt))
        return (reply or "").strip()
    except Exception as e:
        log(f"❌ Local model reply error: {e}")
        return ""

        log(f"🤖 Local model unexpected response: {result} — defaulting to ambiguous")
        return "ambiguous"
    except Exception as e:
        log(f"❌ Local model error: {e} — falling back to keyword matching")
        return None

def log(m):
    print(m)
    if ui_log:ui_log(m)
async def handle_dm_reply(message):
    user_id = message.author.id
    username = str(message.author)
    content = message.content.strip()
    content_lower = content.lower().strip()

    # Opt-out
    if content_lower in ["stop", "remove", "opt out", "optout"]:
        upsert_user(user_id, username, "neutral", opt_out=1)
        await message.channel.send(random.choice(OPT_OUT_RESPONSES))
        log(f"🛑 {username} opted out")
        return

    # First try AI classification
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

    # Otherwise: AI answers their question
    reply = await generate_ai_reply(content)
    if not reply:
        reply = f"I’m not sure, but here’s the Discord invite: {SERVER_INVITE}"

    await message.channel.send(reply)
    log(f"🤖 AI replied to {username}")
@client.event
async def on_ready():log(f"🚀 Quiet Reach is alive! Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author==client.user:return
    if isinstance(message.channel,discord.DMChannel):await handle_dm_reply(message);return
    content=message.content.lower();tw=get_keywords('trigger')
    if any(w in content for w in tw):
        log(f"🔍 Keyword match from {message.author} in {message.guild.name}")
        if check_server_cap(message.guild.id):log(f"🚫 Skipped — daily cap for {message.guild.name}");return
        u=get_user(message.author.id)
        if u and u[4]==1:log(f"🚫 Skipped — {message.author} opted out");return
        if user_on_cooldown(message.author.id):log(f"🚫 Skipped — {message.author} on cooldown");return
        await send_outreach_dm(message.author,message.guild.id)


async def send_outreach_dm(user, sid):
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
# 🖥️ TKINTER DESKTOP UI
# ============================================================

class QuietReachUI:

    def __init__(self, root):
        self.root        = root
        self.bot_thread  = None
        self.bot_running = False
        self.loop        = None

        self.root.title("🤫 Quiet Reach — Control Panel")
        self.root.geometry("950x700")
        self.root.configure(bg='#1a1a2e')
        self.root.resizable(True, True)

        self.build_ui()

        global ui_log
        ui_log = self.append_log

    def build_ui(self):

            # HEADER
            header_frame = tk.Frame(self.root, bg='#1a1a2e')
            header_frame.pack(fill='x', padx=20, pady=(15, 5))

            tk.Label(
                header_frame, text="🤫 Quiet Reach",
                font=('Helvetica', 24, 'bold'),
                bg='#1a1a2e', fg='white'
            ).pack(side='left')

            self.status_label = tk.Label(
                header_frame, text="⚫ Offline",
                font=('Helvetica', 12),
                bg='#1a1a2e', fg='#aaaaaa'
            )
            self.status_label.pack(side='right', padx=10)

            # DIVIDER
            tk.Frame(self.root, bg='#4a90d9', height=2).pack(
                fill='x', padx=20, pady=5
            )

            # MAIN AREA
            main_frame = tk.Frame(self.root, bg='#1a1a2e')
            main_frame.pack(fill='both', expand=True, padx=20, pady=10)

            # ---- LEFT SIDE: SCROLLABLE BUTTON PANEL ----
            # Wrap buttons in a canvas so they scroll if window is small
            btn_canvas = tk.Canvas(main_frame, bg='#1a1a2e',
                                   width=220, highlightthickness=0)
            btn_scrollbar = ttk.Scrollbar(main_frame, orient='vertical',
                                          command=btn_canvas.yview)
            btn_scroll_frame = tk.Frame(btn_canvas, bg='#1a1a2e')

            btn_scroll_frame.bind(
                '<Configure>',
                lambda e: btn_canvas.configure(
                    scrollregion=btn_canvas.bbox('all')
                )
            )
            btn_canvas.create_window((0, 0), window=btn_scroll_frame, anchor='nw')
            btn_canvas.configure(yscrollcommand=btn_scrollbar.set)
            btn_canvas.pack(side='left', fill='y', padx=(0, 5))
            btn_scrollbar.pack(side='left', fill='y', padx=(0, 10))

            # Button factory helper
            def make_button(parent, text, command, color='#4a90d9', fg='white'):
                btn = tk.Button(
                    parent, text=text, command=command,
                    bg=color, fg=fg,
                    font=('Helvetica', 10, 'bold'),
                    relief='flat', cursor='hand2',
                    padx=10, pady=8, width=20,
                    activebackground='#357abd',
                    activeforeground='white'
                )
                btn.pack(pady=3, padx=5)
                btn.bind('<Enter>', lambda e, b=btn: b.config(bg='#357abd'))
                btn.bind('<Leave>', lambda e, b=btn, c=color: b.config(bg=c))
                return btn

            def section_label(text, color='#4a90d9'):
                tk.Label(
                    btn_scroll_frame, text=text,
                    font=('Helvetica', 10, 'bold'),
                    bg='#1a1a2e', fg=color
                ).pack(pady=(10, 3))
                tk.Frame(
                    btn_scroll_frame, bg=color, height=1
                ).pack(fill='x', padx=5, pady=(0, 5))

            # BOT CONTROLS
            section_label("⚙️ Bot Controls")
            self.start_btn = make_button(
                btn_scroll_frame, "▶  Start Bot", self.start_bot, '#27ae60'
            )
            self.stop_btn = make_button(
                btn_scroll_frame, "⏹  Stop Bot", self.stop_bot, '#e74c3c'
            )
            self.stop_btn.config(state='disabled')

            # LISTS
            section_label("📋 View Lists")
            make_button(btn_scroll_frame, "🔥  Warm List",
                        lambda: self.view_list('warm'))
            make_button(btn_scroll_frame, "❄️  Cold List",
                        lambda: self.view_list('cold'))
            make_button(btn_scroll_frame, "😐  Neutral List",
                        lambda: self.view_list('neutral'))

            # TOOLS
            section_label("🛠️ Tools")
            make_button(btn_scroll_frame, "🔍  Review Ambiguous",
                        self.review_ambiguous)
            make_button(btn_scroll_frame, "✏️  Edit Keywords",
                        self.edit_keywords)
            make_button(btn_scroll_frame, "📊  Stats",
                        self.show_stats)

            # RESET TOOLS
            section_label("🔄 Reset Tools", '#e74c3c')
            make_button(btn_scroll_frame, "🔄  Reset Warm",
                        self.reset_warm, '#c0392b')
            make_button(btn_scroll_frame, "🔄  Reset Cold",
                        self.reset_cold, '#c0392b')
            make_button(btn_scroll_frame, "🔄  Reset Neutral",
                        self.reset_neutral, '#c0392b')
            make_button(btn_scroll_frame, "🔄  Reset Ambiguous",
                        self.reset_ambiguous, '#c0392b')
            make_button(btn_scroll_frame, "🔄  Reset Server Caps",
                        self.reset_caps, '#c0392b')
            make_button(btn_scroll_frame, "💀  WIPE ALL DATA",
                        self.reset_all, '#7b241c')

            # ---- RIGHT SIDE: LOG AREA ----
            log_frame = tk.Frame(main_frame, bg='#1a1a2e')
            log_frame.pack(side='right', fill='both', expand=True)

            tk.Label(
                log_frame, text="📡 Live Log",
                font=('Helvetica', 11, 'bold'),
                bg='#1a1a2e', fg='#4a90d9'
            ).pack(anchor='w', pady=(0, 5))

            self.log_area = scrolledtext.ScrolledText(
                log_frame,
                bg='#0d0d1a', fg='#00ff88',
                font=('Courier', 10),
                relief='flat', state='disabled',
                wrap='word', padx=10, pady=10
            )
            self.log_area.pack(fill='both', expand=True)

            # FOOTER
            tk.Label(
                self.root,
                text="Running on discord.py  |  Made with 💙  |  Quiet Reach v1.2",
                font=('Helvetica', 8),
                bg='#1a1a2e', fg='#555577'
            ).pack(pady=(5, 10))
    def build_ui(self):

        # HEADER
        header_frame = tk.Frame(self.root, bg='#1a1a2e')
        header_frame.pack(fill='x', padx=20, pady=(15, 5))

        tk.Label(
            header_frame, text="🤫 Quiet Reach",
            font=('Helvetica', 24, 'bold'),
            bg='#1a1a2e', fg='white'
        ).pack(side='left')

        self.status_label = tk.Label(
            header_frame, text="⚫ Offline",
            font=('Helvetica', 12),
            bg='#1a1a2e', fg='#aaaaaa'
        )
        self.status_label.pack(side='right', padx=10)

        # DIVIDER
        tk.Frame(self.root, bg='#4a90d9', height=2).pack(
            fill='x', padx=20, pady=5
        )

        # MAIN AREA
        main_frame = tk.Frame(self.root, bg='#1a1a2e')
        main_frame.pack(fill='both', expand=True, padx=20, pady=10)

        # ---- LEFT SIDE: SCROLLABLE BUTTON PANEL ----
        # Wrap buttons in a canvas so they scroll if window is small
        btn_canvas    = tk.Canvas(main_frame, bg='#1a1a2e',
                                  width=220, highlightthickness=0)
        btn_scrollbar = ttk.Scrollbar(main_frame, orient='vertical',
                                      command=btn_canvas.yview)
        btn_scroll_frame = tk.Frame(btn_canvas, bg='#1a1a2e')

        btn_scroll_frame.bind(
            '<Configure>',
            lambda e: btn_canvas.configure(
                scrollregion=btn_canvas.bbox('all')
            )
        )
        btn_canvas.create_window((0, 0), window=btn_scroll_frame, anchor='nw')
        btn_canvas.configure(yscrollcommand=btn_scrollbar.set)
        btn_canvas.pack(side='left', fill='y', padx=(0, 5))
        btn_scrollbar.pack(side='left', fill='y', padx=(0, 10))

        # Button factory helper
        def make_button(parent, text, command, color='#4a90d9', fg='white'):
            btn = tk.Button(
                parent, text=text, command=command,
                bg=color, fg=fg,
                font=('Helvetica', 10, 'bold'),
                relief='flat', cursor='hand2',
                padx=10, pady=8, width=20,
                activebackground='#357abd',
                activeforeground='white'
            )
            btn.pack(pady=3, padx=5)
            btn.bind('<Enter>', lambda e, b=btn: b.config(bg='#357abd'))
            btn.bind('<Leave>', lambda e, b=btn, c=color: b.config(bg=c))
            return btn

        def section_label(text, color='#4a90d9'):
            tk.Label(
                btn_scroll_frame, text=text,
                font=('Helvetica', 10, 'bold'),
                bg='#1a1a2e', fg=color
            ).pack(pady=(10, 3))
            tk.Frame(
                btn_scroll_frame, bg=color, height=1
            ).pack(fill='x', padx=5, pady=(0, 5))

        # BOT CONTROLS
        section_label("⚙️ Bot Controls")
        self.start_btn = make_button(
            btn_scroll_frame, "▶  Start Bot", self.start_bot, '#27ae60'
        )
        self.stop_btn = make_button(
            btn_scroll_frame, "⏹  Stop Bot", self.stop_bot, '#e74c3c'
        )
        self.stop_btn.config(state='disabled')

        # LISTS
        section_label("📋 View Lists")
        make_button(btn_scroll_frame, "🔥  Warm List",
                    lambda: self.view_list('warm'))
        make_button(btn_scroll_frame, "❄️  Cold List",
                    lambda: self.view_list('cold'))
        make_button(btn_scroll_frame, "😐  Neutral List",
                    lambda: self.view_list('neutral'))

        # TOOLS
        section_label("🛠️ Tools")
        make_button(btn_scroll_frame, "🔍  Review Ambiguous",
                    self.review_ambiguous)
        make_button(btn_scroll_frame, "✏️  Edit Keywords",
                    self.edit_keywords)
        make_button(btn_scroll_frame, "📊  Stats",
                    self.show_stats)
        make_button(btn_scroll_frame, "🖼️  Manage Images",
                    self.manage_images)


        # RESET TOOLS
        section_label("🔄 Reset Tools", '#e74c3c')
        make_button(btn_scroll_frame, "🔄  Reset Warm",
                    self.reset_warm,      '#c0392b')
        make_button(btn_scroll_frame, "🔄  Reset Cold",
                    self.reset_cold,      '#c0392b')
        make_button(btn_scroll_frame, "🔄  Reset Neutral",
                    self.reset_neutral,   '#c0392b')
        make_button(btn_scroll_frame, "🔄  Reset Ambiguous",
                    self.reset_ambiguous, '#c0392b')
        make_button(btn_scroll_frame, "🔄  Reset Server Caps",
                    self.reset_caps,      '#c0392b')
        make_button(btn_scroll_frame, "💀  WIPE ALL DATA",
                    self.reset_all,       '#7b241c')

        # ---- RIGHT SIDE: LOG AREA ----
        log_frame = tk.Frame(main_frame, bg='#1a1a2e')
        log_frame.pack(side='right', fill='both', expand=True)

        tk.Label(
            log_frame, text="📡 Live Log",
            font=('Helvetica', 11, 'bold'),
            bg='#1a1a2e', fg='#4a90d9'
        ).pack(anchor='w', pady=(0, 5))

        self.log_area = scrolledtext.ScrolledText(
            log_frame,
            bg='#0d0d1a', fg='#00ff88',
            font=('Courier', 10),
            relief='flat', state='disabled',
            wrap='word', padx=10, pady=10
        )
        self.log_area.pack(fill='both', expand=True)

        # FOOTER
        tk.Label(
            self.root,
            text="Running on discord.py  |  Made with 💙  |  Quiet Reach v1.2",
            font=('Helvetica', 8),
            bg='#1a1a2e', fg='#555577'
        ).pack(pady=(5, 10))

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
        if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
            messagebox.showerror("Token Missing!",
                "Replace YOUR_BOT_TOKEN_HERE with your bot token!")
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

        # Load current images from file
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
            """Open file browser to pick an image."""
            filepath = filedialog.askopenfilename(
                title="Select an image",
                filetypes=[
                    ("Image files", "*.jpg *.jpeg *.png *.gif *.webp"),
                    ("All files", "*.*")
                ]
            )
            if filepath:
                # Copy image to project folder for portability
                import shutil
                filename = os.path.basename(filepath)
                dest     = os.path.join(os.getcwd(), filename)
                shutil.copy2(filepath, dest)

                # Save to images.txt
                with open(images_file, 'a') as f:
                    f.write(filename + '\n')

                load_images()
                self.append_log(f"🖼️ Added image: {filename}")

        def remove_image():
            """Remove selected image from the list."""
            selected = listbox.curselection()
            if selected:
                image_name = listbox.get(selected[0]).strip()

                # Read all lines, remove selected
                if os.path.exists(images_file):
                    with open(images_file, 'r') as f:
                        lines = [l.strip() for l in f.readlines() if l.strip()]
                    lines = [l for l in lines if l != image_name]
                    with open(images_file, 'w') as f:
                        f.write('\n'.join(lines))

                load_images()
                self.append_log(f"🗑️ Removed image: {image_name}")

        # Buttons
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
        if messagebox.askyesno("⚠️ WIPE ALL",
                "Wipe ALL data? This cannot be undone!"):
            if messagebox.askyesno("⚠️ FINAL WARNING",
                    "Are you absolutely sure?"):
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
    app  = QuietReachUI(root)
    root.mainloop()






























