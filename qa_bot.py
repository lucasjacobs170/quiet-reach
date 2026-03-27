# Multi-platform Bot Code

import discord
from discord.ext import commands
import telebot
import logging
import sqlite3

# Set up logging
logging.basicConfig(level=logging.INFO, filename='bot.log', format='%(asctime)s %(levelname)s:%(message)s')

# Database setup
conn = sqlite3.connect('qa_log.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS incidents (id INTEGER PRIMARY KEY, platform TEXT, message TEXT, hostility_detected BOOLEAN)''')
conn.commit()

HOSTILITY_KEYWORDS = ["offensive_keyword1", "offensive_keyword2"]

# Function to check for hostility
def is_hostile(message):
    for keyword in HOSTILITY_KEYWORDS:
        if keyword in message:
            return True
    return False

# Discord bot setup
discord_bot = commands.Bot(command_prefix='!')

discord_channel_id = 'your_discord_channel_id'  # Replace with actual channel ID

def notify_owner(message):
    # Notify the owner in Discord
    discord_bot.get_channel(discord_channel_id).send(f'Owner notification: {message}')

@discord_bot.event
async def on_ready():
    logging.info(f'Discord bot logged in as {discord_bot.user}')
    print(f'{discord_bot.user} has connected to Discord!')

@discord_bot.event
async def on_message(message):
    if message.author == discord_bot.user:
        return

    if is_hostile(message.content):
        logging.warning(f'Hostility detected in Discord message: {message.content}')
        c.execute("INSERT INTO incidents (platform, message, hostility_detected) VALUES (?, ?, ?)", ('Discord', message.content, True))
        conn.commit()
        await notify_owner(message.content)
        await message.channel.send('Your message has been flagged. Please adhere to community guidelines.')
        return

    # Handle QA processing here (ensure you define how to process Q&A)
    # Example response
    await message.channel.send('This is a response to your question.')

# Telegram bot setup
telegram_bot = telebot.TeleBot('your_telegram_bot_token')

@telegram_bot.message_handler(func=lambda message: True)
def handle_telegram_message(message):
    if is_hostile(message.text):
        logging.warning(f'Hostility detected in Telegram message: {message.text}')
        c.execute("INSERT INTO incidents (platform, message, hostility_detected) VALUES (?, ?, ?)", ('Telegram', message.text, True))
        conn.commit()
        notify_owner(message.text)
        telegram_bot.reply_to(message, 'Your message has been flagged. Please adhere to community guidelines.')
        return

    # Handle QA processing here
    # Example response
    telegram_bot.reply_to(message, 'This is a response to your question.')

# Start both bots
if __name__ == '__main__':
    discord_bot.run('your_discord_bot_token')
    telegram_bot.polling()