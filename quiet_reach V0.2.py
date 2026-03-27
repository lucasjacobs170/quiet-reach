import ollama
import sqlite3
import telegram

# Initialize the database connection
connection = sqlite3.connect('hostility_detection.db')
cursor = connection.cursor()

# Create a table for recording incidents
cursor.execute('''CREATE TABLE IF NOT EXISTS incidents (id INTEGER PRIMARY KEY, timestamp TEXT, message TEXT)''')

# Function to log incidents in the database
def log_incident(message):
    timestamp = str(datetime.datetime.utcnow())
    cursor.execute('''INSERT INTO incidents (timestamp, message) VALUES (?, ?)''', (timestamp, message))
    connection.commit()

# Telegram bot configuration
TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN'
bot = telegram.Bot(token=TOKEN)

# Handler for messages received by the bot
def handle_message(update, context):
    message = update.message.text
    # Perform hostility detection
    if detect_hostility(message):
        update.message.reply_text('Hostility detected!')
        log_incident(message)
    else:
        update.message.reply_text('No hostility detected.')

# Function to detect hostility
def detect_hostility(message):
    # Placeholder for real hostility detection logic
    return 'hostile' in message.lower()

# Set up the Telegram handler
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
updater = Updater(TOKEN, use_context=True)
updater.dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

# Start the bot
updater.start_polling()
updater.idle()