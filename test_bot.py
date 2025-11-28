import logging
import os
import asyncio
import threading
from flask import Flask
import psycopg2
from psycopg2 import pool
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from ghost_engine import GhostEngine

# --- DUMMY WEB SERVER ---
app_flask = Flask(__name__)
@app_flask.route('/')
def health_check(): return "Bot is Alive!", 200
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host="0.0.0.0", port=port)
# ------------------------

# ENV VARS
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

try:
    DB_POOL = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
except Exception as e:
    print(f"❌ DB Error: {e}")

GHOST = GhostEngine(DB_POOL)

# --- MENUS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    personas = GHOST.get_personas_list()
    kb = []
    for i in range(0, len(personas), 2):
        row = [InlineKeyboardButton(p[1], callback_data=f"ai_{p[0]}") for p in personas[i:i+2]]
        kb.append(row)
    
    await update.message.reply_text(
        "🧪 **AI LAB SETUP**\n\n1️⃣ Select AI Archetype:", 
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id

    # STEP 2: SELECT AI GENDER
    if data.startswith("ai_"):
        context.user_data['temp_ai_key'] = data.split("_", 1)[1]
        
        kb = [
            [InlineKeyboardButton("🤖 AI is Male", callback_data="aigen_Male"), 
             InlineKeyboardButton("🤖 AI is Female", callback_data="aigen_Female")]
        ]
        await q.edit_message_text(
            "2️⃣ **Select AI Gender:**", 
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )
        return

    # STEP 3: SELECT USER GENDER
    if data.startswith("aigen_"):
        context.user_data['temp_ai_gen'] = data.split("_")[1]
        
        kb = [
            [InlineKeyboardButton("👤 I am Male", callback_data="ugen_Male"), 
             InlineKeyboardButton("👤 I am Female", callback_data="ugen_Female")]
        ]
        await q.edit_message_text(
            "3️⃣ **Who are you?** (Your Gender)", 
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )
        return

    # STEP 4: SELECT USER COUNTRY
    if data.startswith("ugen_"):
        context.user_data['temp_u_gen'] = data.split("_")[1]
        
        kb = [
            [InlineKeyboardButton("🇮🇳 India", callback_data="uctry_India"), 
             InlineKeyboardButton("🇺🇸 USA", callback_data="uctry_USA")],
            [InlineKeyboardButton("🇬🇧 UK", callback_data="uctry_UK"), 
             InlineKeyboardButton("🇵🇭 Asia", callback_data="uctry_Asia")]
        ]
        await q.edit_message_text(
            "4️⃣ **Where are you from?**", 
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )
        return

    # STEP 5: START CHAT
    if data.startswith("uctry_"):
        # SAFETY CHECK
        if 'temp_ai_key' not in context.user_data:
            await q.edit_message_text("❌ Session expired. Type /start.")
            return

        u_country = data.split("_")[1]
        ai_key = context.user_data['temp_ai_key']
        ai_gen = context.user_data['temp_ai_gen']
        u_gen = context.user_data['temp_u_gen']
        
        user_ctx = {'gender': u_gen, 'country': u_country}
        
        success = await GHOST.start_chat(uid, ai_key, ai_gen, user_ctx)
        
        clean_key = ai_key.replace("_", " ").title()
        
        if success:
            msg = (
                f"✅ **CONNECTED**\n"
                f"🤖 **AI:** {clean_key} ({ai_gen})\n"
                f"👤 **User:** {u_gen} from {u_country}\n\n"
                f"_Bot is typing slower to mimic human..._"
            )
            await q.edit_message_text(msg, parse_mode='Markdown')
            context.user_data['active'] = True
        else:
            await q.edit_message_text("❌ Error starting AI.")
        return

    # FEEDBACK
    if data.startswith("fb_"):
        rating = int(data.split("_")[1])
        last = context.user_data.get('last_exchange')
        if last:
            u_in, a_out = last
            GHOST.save_feedback(uid, u_in, a_out, rating)
            await q.edit_message_reply_markup(None)
        return

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('active'):
        await update.message.reply_text("⚠️ Run /start to configure the AI first.")
        return

    user_id = update.effective_user.id
    user_text = update.message.text
    
    # 1. Typing action (loops if delay is long)
    await context.bot.send_chat_action(chat_id=user_id, action="typing")
    
    # 2. Get Result
    result = await GHOST.process_message(user_id, user_text)
    
    if not result:
        await update.message.reply_text("❌ Session expired. /start")
        return

    # 3. Handle Special Logic
    if result == "TRIGGER_SKIP":
        await asyncio.sleep(0.5)
        await update.message.reply_text("🚫 **[AI LOGIC]** Partner Disconnected (Skip Trigger).")
        context.user_data['active'] = False
        return

    if result == "TRIGGER_INDIAN_MALE_BEG":
        await asyncio.sleep(1.5)
        await update.message.reply_text("bro any girls id?")
        await asyncio.sleep(2.5)
        await update.message.reply_text("give me")
        await asyncio.sleep(1.5)
        await update.message.reply_text("im single")
        await asyncio.sleep(1.0)
        await update.message.reply_text("🚫 **[AI LOGIC]** Partner Disconnected.")
        context.user_data['active'] = False
        return

    # 4. Handle Text Reply
    if result.get("type") == "text":
        delay = result["delay"]
        
        # Keep sending "typing..." status if delay is long
        if delay > 4:
            await asyncio.sleep(2)
            await context.bot.send_chat_action(chat_id=user_id, action="typing")
            await asyncio.sleep(delay - 2)
        else:
            await asyncio.sleep(delay)
        
        kb = [[InlineKeyboardButton("👍 Good", callback_data="fb_1"), InlineKeyboardButton("👎 Bad", callback_data="fb_-1")]]
        context.user_data['last_exchange'] = (user_text, result["content"])
        
        # Plain text send
        await update.message.reply_text(result["content"], reply_markup=InlineKeyboardMarkup(kb))
    
    elif result.get("type") == "error":
        await update.message.reply_text(result["content"])

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['active'] = False
    await update.message.reply_text("🛑 Chat stopped. /start to restart.")

if __name__ == '__main__':
    if not BOT_TOKEN: print("❌ Error: BOT_TOKEN missing")
    else:
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stop", stop_command))
        app.add_handler(CallbackQueryHandler(button_handler))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat_handler))
        print("🤖 TEST BOT ONLINE")
        app.run_polling()
