import os
import discord
import sqlite3
from datetime import datetime
import google.generativeai as genai

DB_PATH = "quiet_reach.db"

# Read secrets from environment variables (so you DON'T put keys in GitHub)
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

SERVER_INVITE = os.environ.get("SERVER_INVITE", "https://discord.gg/yAvVewhD3c")

# Only links you allow the bot to share (prevents made-up links)
LINKS = {
    "discord": SERVER_INVITE,
}

CREATOR_PROFILE = """
You are the assistant for Lucas Jacobs.
Your job is to answer questions about Lucas and his content.

Rules:
- Be respectful, friendly, and concise.
- Do NOT invent links. Only use links provided in Allowed links.
- If you don't know something, say so and offer the Discord link.
"""

def db():
    return sqlite3.connect(DB_PATH)

def setup_database():
    c = db()
    k = c.cursor()

    # Logs every DM message for history
    k.execute("""
    CREATE TABLE IF NOT EXISTS dm_messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT,
        role TEXT,
        content TEXT,
        timestamp TEXT
    )
    """)

    # Your “repository of responses”
    k.execute("""
    CREATE TABLE IF NOT EXISTS qa_repository(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT,
        answer TEXT,
        created_at TEXT,
        approved INTEGER DEFAULT 0,
        used_count INTEGER DEFAULT 0,
        last_used TEXT
    )
    """)

    c.commit()
    c.close()

def log_dm_message(discord_id: int, role: str, content: str):
    c = db()
    k = c.cursor()
    k.execute(
        "INSERT INTO dm_messages(discord_id, role, content, timestamp) VALUES(?,?,?,?)",
        (str(discord_id), role, content, datetime.now().isoformat(timespec="seconds"))
    )
    c.commit()
    c.close()

def find_approved_answer(user_question: str):
    q = user_question.lower().strip()
    if len(q) < 6:
        return None

    c = db()
    k = c.cursor()
    k.execute("""
        SELECT id, question, answer
        FROM qa_repository
        WHERE approved = 1 AND lower(question) LIKE ?
        ORDER BY used_count DESC
        LIMIT 1
    """, (f"%{q[:20]}%",))
    row = k.fetchone()
    c.close()
    return row  # (id, question, answer) or None

def save_qa_candidate(question: str, answer: str):
    c = db()
    k = c.cursor()
    k.execute("""
        INSERT INTO qa_repository(question, answer, created_at, approved)
        VALUES(?,?,?,0)
    """, (question, answer, datetime.now().isoformat(timespec="seconds")))
    c.commit()
    qa_id = k.lastrowid
    c.close()
    return qa_id

def mark_used(qa_id: int):
    c = db()
    k = c.cursor()
    k.execute("""
        UPDATE qa_repository
        SET used_count = used_count + 1,
            last_used = ?
        WHERE id = ?
    """, (datetime.now().isoformat(timespec="seconds"), qa_id))
    c.commit()
    c.close()

def list_pending(limit=10):
    c = db()
    k = c.cursor()
    k.execute("""
        SELECT id, question
        FROM qa_repository
        WHERE approved = 0
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = k.fetchall()
    c.close()
    return rows

def approve_qa(qa_id: int):
    c = db()
    k = c.cursor()
    k.execute("UPDATE qa_repository SET approved = 1 WHERE id = ?", (qa_id,))
    c.commit()
    c.close()

# Gemini setup
def init_gemini():
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel("gemini-pro")

async def generate_answer(model, question: str) -> str:
    allowed_links_text = "\n".join([f"- {k}: {v}" for k, v in LINKS.items()])

    prompt = f"""
{CREATOR_PROFILE}

Allowed links (ONLY these):
{allowed_links_text}

User question:
"{question}"

Write a helpful reply. If you mention a link, only use the Allowed links exactly.
Keep it short.
"""
    result = model.generate_content(prompt)
    return (result.text or "").strip()

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    # Only respond to DMs (safe + simple)
    if not isinstance(message.channel, discord.DMChannel):
        return

    user_id = message.author.id
    text = message.content.strip()
    log_dm_message(user_id, "user", text)

    # Owner commands
    if user_id == OWNER_ID:
        lower = text.lower().strip()

        if lower == "!pending":
            rows = list_pending(limit=10)
            if not rows:
                await message.channel.send("No pending Q/A items.")
                return
            msg = "**Pending Q/A (unapproved):**\n" + "\n".join([f"- ID {r[0]}: {r[1][:80]}" for r in rows])
            await message.channel.send(msg)
            return

        if lower.startswith("!approve "):
            try:
                qa_id = int(lower.split()[1])
                approve_qa(qa_id)
                await message.channel.send(f"Approved Q/A ID {qa_id}.")
            except:
                await message.channel.send("Usage: !approve 123")
            return

        await message.channel.send("Owner commands: `!pending` , `!approve <id>`")
        return

    # Reuse approved answers first
    existing = find_approved_answer(text)
    if existing:
        qa_id, _, answer = existing
        mark_used(qa_id)
        await message.channel.send(answer)
        log_dm_message(user_id, "bot", answer)
        return

    # Otherwise generate + save as pending
    try:
        model = init_gemini()
        answer = await generate_answer(model, text)
    except Exception:
        answer = "Sorry—I'm having trouble answering right now. Try again in a bit."
        await message.channel.send(answer)
        log_dm_message(user_id, "bot", answer)
        return

    qa_id = save_qa_candidate(text, answer)

    await message.channel.send(answer)
    log_dm_message(user_id, "bot", answer)

    # Notify owner
    try:
        owner = await client.fetch_user(OWNER_ID)
        await owner.send(f"🧠 New Q/A saved as pending (ID {qa_id}). Use `!pending` to review.")
    except:
        pass

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("Missing DISCORD_BOT_TOKEN env var.")
    if not GEMINI_API_KEY:
        raise RuntimeError("Missing GEMINI_API_KEY env var.")
    if OWNER_ID == 0:
        raise RuntimeError("Missing OWNER_ID env var.")

    setup_database()
    client.run(DISCORD_BOT_TOKEN)
