import logging
import os
import asyncio
import random
import psycopg2
from psycopg2 import pool
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# ==============================================================================
# ⚙️ CONFIGURATION
# ==============================================================================
# These are loaded from your Render Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN") 
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# File config
LOG_FILE = "chat_logs.txt"

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize AI Client
if not GROQ_API_KEY:
    logger.error("❌ CRITICAL: GROQ_API_KEY is missing! Bot will just say 'lag lol'.")
    client = None
else:
    client = Groq(api_key=GROQ_API_KEY)

# Personas
PERSONAS = {
    "Male": "You are a bored 20-year-old guy. You use short sentences. You like gaming and gym. You are slightly toxic but funny.",
    "Female": "You are a 19-year-old girl. You use lowercase and 'lol' a lot. You are suspicious of creeps. You like music and travel.",
    "Hidden": "You are a random stranger on Omegle. Mysterious, sarcastic, unpredictable."
}

# ==============================================================================
# 📂 DATA ENGINE
# ==============================================================================
DEFAULT_SAMPLES = [
    "- u from?", "- skip", "- hi", "- m or f?", "- im bored lol", 
    "- snap?", "- nah", "- wyd", "- cool", "- same", "- lol really?",
    "- i hate school", "- where u from", "- hm", "- yea"
]
ALL_CHATS = []

def load_chat_logs():
    """Loads chat logs safely."""
    global ALL_CHATS
    ALL_CHATS = list(DEFAULT_SAMPLES)
    
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if len(line.strip()) > 3]
                if lines:
                    ALL_CHATS.extend(lines)
                    logger.info(f"✅ Loaded {len(lines)} lines from file.")
        except Exception as e:
            logger.error(f"⚠️ Error loading file: {e}")
    else:
        logger.info("ℹ️ No chat_logs.txt found. Using default samples.")

def get_random_samples(count=10):
    return "\n".join(random.sample(ALL_CHATS, min(count, len(ALL_CHATS))))

# ==============================================================================
# 💾 DATABASE (ROBUST CONNECTION HANDLING)
# ==============================================================================
# We define the connection getter inside functions to avoid "Stale Connection" errors.

def get_db_connection():
    """Creates a fresh connection to the database."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"❌ DB Connection Failed: {e}")
        return None

def init_db():
    """Creates tables if they don't exist."""
    conn = get_db_connection()
    if not conn: return
    
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS sandbox_users 
                     (user_id BIGINT PRIMARY KEY, 
                      my_gender TEXT DEFAULT 'Hidden', 
                      ai_gender TEXT DEFAULT 'Hidden', 
                      interests TEXT DEFAULT 'Random',
                      is_chatting INTEGER DEFAULT 0)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS training_logs 
                     (id SERIAL PRIMARY KEY, 
                      user_input TEXT, 
                      ai_response TEXT, 
                      timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        logger.info("✅ Database Tables Ready.")
    except Exception as e:
        logger.error(f"❌ Init DB Error: {e}")
    finally:
        conn.close()

def get_user(user_id):
    conn = get_db_connection()
    if not conn: return (user_id, 'Hidden', 'Hidden', 'Random', 0)
    
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM sandbox_users WHERE user_id=%s", (user_id,))
        u = c.fetchone()
        if not u:
            c.execute("INSERT INTO sandbox_users (user_id) VALUES (%s)", (user_id,))
            conn.commit()
            u = (user_id, 'Hidden', 'Hidden', 'Random', 0)
        return u
    except Exception as e:
        logger.error(f"Get User Error: {e}")
        return (user_id, 'Hidden', 'Hidden', 'Random', 0) # Fallback
    finally:
        conn.close()

def update_user(user_id, col, val):
    conn = get_db_connection()
    if not conn: return
    try:
        c = conn.cursor()
        # We whitelist columns to prevent injection since table names can't be parameterized
        if col not in ['my_gender', 'ai_gender', 'interests', 'is_chatting']:
            return
        
        query = f"UPDATE sandbox_users SET {col}=%s WHERE user_id=%s"
        c.execute(query, (val, user_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Update User Error: {e}")
    finally:
        conn.close()

def log_chat(user_text, ai_text):
    conn = get_db_connection()
    if not conn: return
    try:
        c = conn.cursor()
        c.execute("INSERT INTO training_logs (user_input, ai_response) VALUES (%s, %s)", (user_text, ai_text))
        conn.commit()
    except Exception as e:
        logger.error(f"Log Chat Error: {e}")
    finally:
        conn.close()

# ==============================================================================
# 🧠 AI ENGINE (The Brain)
# ==============================================================================
async def get_ai_reply(history, ai_gender, interests):
    if not client:
        return "Config Error: Groq Key Missing."

    base_persona = PERSONAS.get(ai_gender, PERSONAS["Hidden"])
    dynamic_examples = get_random_samples(10) 
    
    system_prompt = f"""
    {base_persona}
    Your interests are: {interests}.
    
    INSTRUCTIONS:
    1. You are a REAL user on a chat app. Not an AI.
    2. Speak exactly like the examples below (lowercase, slang, short).
    3. Ignore grammar. Be casual.
    
    MIMIC THIS STYLE:
    {dynamic_examples}
    """

    # Format history for Llama 3
    messages = [{"role": "system", "content": system_prompt}] + history[-6:]

    try:
        completion = client.chat.completions.create(
            messages=messages, 
            model="llama3-8b-8192", 
            temperature=1.0, 
            max_tokens=60
        )
        return completion.choices[0].message.content.lower().replace('"', '').strip()
    except Exception as e:
        logger.error(f"❌ AI Error: {e}")
        return "lag lol"

# ==============================================================================
# 🎮 BOT LOGIC
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Load data on start just in case
    load_chat_logs()
    init_db()
    
    kb = [[KeyboardButton("⚙️ Configure AI"), KeyboardButton("🚀 Start Chat")]]
    await update.message.reply_text(
        "🤖 **AI TRAINER ONLINE**\n\nReady to chat. Click Start.", 
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True), 
        parse_mode='Markdown'
    )

async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id, "is_chatting", 1)
    
    user = get_user(user_id) # (id, my, ai, int, chat)
    
    msg = f"⚡ **CONNECTED**\n\n👤 You: {user[1]}\n🤖 AI: {user[2]}\n🏷️ Topic: {user[3]}\n\nSay Hi! 👇"
    
    # Clear local history
    context.user_data['history'] = []
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id, "is_chatting", 0)
    context.user_data['history'] = []
    
    kb = [[KeyboardButton("🚀 Start Chat"), KeyboardButton("⚙️ Configure AI")]]
    await update.message.reply_text("🛑 Chat Stopped.", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Menu Triggers
    if text == "🚀 Start Chat": await start_chat(update, context); return
    if text == "🛑 Stop Chat": await stop_chat(update, context); return
    if text == "⚙️ Configure AI": await configure_menu(update, context); return
    
    # Check Status
    user = get_user(user_id)
    if user[4] == 0: # Not chatting
        await update.message.reply_text("⚠️ Click '🚀 Start Chat' first."); return

    # --- AI PROCESS ---
    history = context.user_data.get('history', [])
    history.append({"role": "user", "content": text})
    
    await context.bot.send_chat_action(chat_id=user_id, action="typing")
    
    # Get Reply
    ai_reply = await get_ai_reply(history, user[2], user[3])
    
    # Log it
    log_chat(text, ai_reply)
    
    # Delay & Send
    delay = min((len(ai_reply) * 0.1), 3.0) + random.uniform(0.5, 1.5)
    await asyncio.sleep(delay)
    
    await update.message.reply_text(ai_reply)
    
    history.append({"role": "assistant", "content": ai_reply})
    context.user_data['history'] = history

# ==============================================================================
# ⚙️ SETTINGS MENU
# ==============================================================================
async def configure_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("👤 My Gender", callback_data="set_my"), InlineKeyboardButton("🤖 AI Gender", callback_data="set_ai")],
        [InlineKeyboardButton("🏷️ Interests", callback_data="set_int")]
    ]
    await update.message.reply_text("⚙️ **Settings:**", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id
    await q.answer()
    
    if data in ["set_my", "set_ai"]:
        t = "my" if "my" in data else "ai"
        kb = [[InlineKeyboardButton("Male", callback_data=f"save_{t}_Male"), InlineKeyboardButton("Female", callback_data=f"save_{t}_Female")]]
        await q.edit_message_text(f"Select {t} gender:", reply_markup=InlineKeyboardMarkup(kb))
        
    elif data.startswith("save_"):
        parts = data.split("_")
        target = parts[1] # my or ai
        val = parts[2]    # Male or Female
        update_user(uid, f"{target}_gender", val)
        await q.edit_message_text(f"✅ Saved: {val}")
        
    elif data == "set_int":
        await q.edit_message_text("👇 Type your interests now:")
        context.user_data['awaiting_int'] = True

async def handle_int_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Intercepts text if we are waiting for interests
    if context.user_data.get('awaiting_int'):
        update_user(update.effective_user.id, "interests", update.message.text)
        context.user_data['awaiting_int'] = False
        await update.message.reply_text("✅ Interests saved.", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🚀 Start Chat")]]))
        return
        
    # Otherwise, handle as normal chat
    await handle_message(update, context)

# ==============================================================================
# 🚀 STARTUP
# ==============================================================================
if __name__ == '__main__':
    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN missing in Render Environment Variables.")
    else:
        # Load Data
        load_chat_logs()
        
        # App Builder
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # Handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(button_handler))
        app.add_handler(MessageHandler(filters.TEXT, handle_int_input))
        
        print("🤖 TRAINER BOT LIVE (Press Ctrl+C to stop)")
        app.run_polling()
```

### Instructions for You
1.  **Replace:** Paste this over your existing code in `train_bot.py` (or `main.py` if you renamed it).
2.  **Commit & Push:** Send it to GitHub.
3.  **Verify Render:** Check the Render logs. If you see `✅ Database Tables Ready`, you are good to go.
4.  **Check Keys:** Ensure `GROQ_API_KEY` and `DATABASE_URL` are correct in Render settings.

This code opens and closes the database connection cleanly every single time, so the "SSL connection closed" error will disappear.
