import logging
import os
import asyncio
import random
import psycopg2
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# ==============================================================================
# ⚙️ CONFIGURATION (Get these from Render Env Vars)
# ==============================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN") 
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

LOG_FILE = "chat_logs.txt"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Initialize AI
try:
    client = Groq(api_key=GROQ_API_KEY)
except:
    print("⚠️ GROQ_API_KEY missing or invalid.")

PERSONAS = {
    "Male": "You are a bored 20-year-old guy. You use short sentences. You like gaming and gym. You are slightly toxic but funny.",
    "Female": "You are a 19-year-old girl. You use lowercase and 'lol' a lot. You are suspicious of creeps. You like music and travel.",
    "Hidden": "You are a random stranger on Omegle. Mysterious, sarcastic, unpredictable."
}

# ==============================================================================
# 📂 DATA ENGINE (The "Brain")
# ==============================================================================
# Default "Starter" data so the bot works immediately without a file
DEFAULT_SAMPLES = [
    "- u from?", "- skip", "- hi", "- m or f?", "- im bored lol", 
    "- snap?", "- nah", "- wyd", "- cool", "- same", "- lol really?",
    "- i hate school", "- where u from", "- hm", "- yea"
]
ALL_CHATS = []

def load_chat_logs():
    """Loads data if file exists, otherwise uses defaults."""
    global ALL_CHATS
    ALL_CHATS = list(DEFAULT_SAMPLES) # Start with defaults
    
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if len(line.strip()) > 3]
                if lines:
                    ALL_CHATS.extend(lines) # Add file data to defaults
                    print(f"✅ Loaded {len(lines)} lines from file.")
        except Exception as e:
            print(f"⚠️ Error loading file: {e}")
    else:
        print("ℹ️ No chat_logs.txt found. Using starter data.")

def get_random_samples(count=10):
    """Picks random lines to teach the AI the current 'vibe'."""
    return "\n".join(random.sample(ALL_CHATS, min(count, len(ALL_CHATS))))

# ==============================================================================
# 💾 DATABASE (The "Memory")
# ==============================================================================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Sandbox Users (Your settings)
        c.execute('''CREATE TABLE IF NOT EXISTS sandbox_users 
                     (user_id BIGINT PRIMARY KEY, 
                      my_gender TEXT DEFAULT 'Hidden', 
                      ai_gender TEXT DEFAULT 'Hidden', 
                      interests TEXT DEFAULT 'Random',
                      is_chatting INTEGER DEFAULT 0)''')
        
        # Training Logs (Saves EVERY chat for future training)
        c.execute('''CREATE TABLE IF NOT EXISTS training_logs 
                     (id SERIAL PRIMARY KEY, 
                      user_input TEXT, 
                      ai_response TEXT, 
                      timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()
        print("✅ Database Connected & Ready.")
    except Exception as e:
        print(f"❌ DB Error: {e}")

def get_user(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM sandbox_users WHERE user_id=%s", (user_id,))
    u = c.fetchone()
    if not u:
        c.execute("INSERT INTO sandbox_users (user_id) VALUES (%s)", (user_id,))
        conn.commit()
        u = (user_id, 'Hidden', 'Hidden', 'Random', 0)
    conn.close()
    return u

def update_user(user_id, col, val):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE sandbox_users SET {col}=%s WHERE user_id=%s", (val, user_id))
    conn.commit()
    conn.close()

def log_chat(user_text, ai_text):
    """Saves the conversation to the database."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO training_logs (user_input, ai_response) VALUES (%s, %s)", (user_text, ai_text))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Log Error: {e}")

# ==============================================================================
# 🧠 AI GENERATION
# ==============================================================================
async def get_ai_reply(history, ai_gender, interests):
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

    messages = [{"role": "system", "content": system_prompt}] + history[-6:]

    try:
        completion = client.chat.completions.create(
            messages=messages, model="llama3-8b-8192", temperature=1.0, max_tokens=50
        )
        return completion.choices[0].message.content.lower().replace('"', '').strip()
    except: return "lag lol"

# ==============================================================================
# 🎮 BOT HANDLERS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_chat_logs() 
    init_db()
    kb = [[KeyboardButton("⚙️ Configure AI"), KeyboardButton("🚀 Start Chat")]]
    await update.message.reply_text("🤖 **TRAINING BOT ONLINE**\n\nI am ready to chat and learn.\nClick Start to begin.", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True), parse_mode='Markdown')

async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id, "is_chatting", 1)
    user = get_user(user_id)
    
    msg = f"⚡ **CONNECTED**\n\n👤 You: {user[1]}\n🤖 AI: {user[2]}\n🏷️ Topic: {user[3]}\n\nSay Hi! 👇"
    context.user_data['history'] = []
    await update.message.reply_text(msg, parse_mode='Markdown')

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id, "is_chatting", 0)
    context.user_data['history'] = []
    await update.message.reply_text("🛑 Chat ended.", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🚀 Start Chat"), KeyboardButton("⚙️ Configure AI")]], resize_keyboard=True))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if text == "🚀 Start Chat": await start_chat(update, context); return
    if text == "🛑 Stop Chat": await stop_chat(update, context); return
    if text == "⚙️ Configure AI": await configure_menu(update, context); return
    
    user = get_user(user_id)
    if user[4] == 0: await update.message.reply_text("⚠️ Click '🚀 Start Chat' first."); return

    # Update history & generate reply
    history = context.user_data.get('history', [])
    history.append({"role": "user", "content": text})
    
    await context.bot.send_chat_action(chat_id=user_id, action="typing")
    ai_reply = await get_ai_reply(history, user[2], user[3])
    
    # SAVE TO DB 💎
    log_chat(text, ai_reply)
    
    # Simulate typing delay
    delay = min((len(ai_reply) * 0.1), 3.0) + random.uniform(0.5, 1.0)
    await asyncio.sleep(delay)
    await update.message.reply_text(ai_reply)
    
    history.append({"role": "assistant", "content": ai_reply})
    context.user_data['history'] = history

async def configure_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("👤 My Gender", callback_data="set_my"), InlineKeyboardButton("🤖 AI Gender", callback_data="set_ai")],
          [InlineKeyboardButton("🏷️ Interests", callback_data="set_int")]]
    await update.message.reply_text("⚙️ **Settings:**", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id
    
    if data in ["set_my", "set_ai"]:
        t = "my" if "my" in data else "ai"
        kb = [[InlineKeyboardButton("Male", callback_data=f"save_{t}_Male"), InlineKeyboardButton("Female", callback_data=f"save_{t}_Female")]]
        await q.edit_message_text(f"Select {t} gender:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("save_"):
        parts = data.split("_"); update_user(uid, f"{parts[1]}_gender", parts[2])
        await q.edit_message_text(f"✅ Saved: {parts[2]}")
    elif data == "set_int":
        await q.edit_message_text("👇 Type interests now:"); context.user_data['awaiting_int'] = True

async def handle_int_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_int'):
        update_user(update.effective_user.id, "interests", update.message.text)
        context.user_data['awaiting_int'] = False
        await update.message.reply_text("✅ Interests set.", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🚀 Start Chat")]]))
        return
    await handle_message(update, context)

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT, handle_int_input))
    print("🤖 TRAINER BOT LIVE")
    app.run_polling()
