import logging
import os
import asyncio
import psycopg2
from psycopg2 import pool
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from ghost_engine import GhostEngine

# ENV VARS
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# DB CONNECT
try:
    DB_POOL = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
except Exception as e:
    print(f"❌ DB Error: {e}")

# INIT ENGINE (This will now auto-create tables)
GHOST = GhostEngine(DB_POOL)

# --- MENUS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # STEP 1: Select AI Persona
    personas = GHOST.get_personas_list()
    kb = []
    # Create rows of 2 buttons
    for i in range(0, len(personas), 2):
        row = [InlineKeyboardButton(p[1], callback_data=f"ai_{p[0]}") for p in personas[i:i+2]]
        kb.append(row)
    
    await update.message.reply_text(
        "🧪 **AI LAB SETUP**\n\n1️⃣ Choose the AI Persona:", 
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id

    # STEP 2: SAVE AI & ASK USER GENDER
    if data.startswith("ai_"):
        context.user_data['temp_ai'] = data.split("_", 1)[1]
        
        kb = [
            [InlineKeyboardButton("👨 Male", callback_data="ugen_Male"), 
             InlineKeyboardButton("👩 Female", callback_data="ugen_Female")]
        ]
        await q.edit_message_text(
            "2️⃣ **Who are you pretending to be?** (Gender)", 
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )
        return

    # STEP 3: SAVE GENDER & ASK COUNTRY
    if data.startswith("ugen_"):
        context.user_data['temp_gen'] = data.split("_")[1]
        
        kb = [
            [InlineKeyboardButton("🇮🇳 India", callback_data="uctry_India"), 
             InlineKeyboardButton("🇺🇸 USA", callback_data="uctry_USA")],
            [InlineKeyboardButton("🇬🇧 UK", callback_data="uctry_UK"), 
             InlineKeyboardButton("🇵🇭 Phil/Asia", callback_data="uctry_Asia")]
        ]
        await q.edit_message_text(
            "3️⃣ **Where are you from?**", 
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
        )
        return

    # STEP 4: START CHAT
    if data.startswith("uctry_"):
        country = data.split("_")[1]
        ai_key = context.user_data['temp_ai']
        u_gen = context.user_data['temp_gen']
        
        # Prepare context for AI
        user_ctx = {'gender': u_gen, 'country': country}
        
        success = await GHOST.start_chat(uid, ai_key, user_ctx)
        
        if success:
            info = f"🤖 **AI:** {ai_key}\n👤 **You:** {u_gen}, {country}"
            await q.edit_message_text(f"✅ **CONNECTED**\n{info}\n\nSay 'Hi' to start!", parse_mode='Markdown')
            context.user_data['active'] = True
        else:
            await q.edit_message_text("❌ Error starting AI.")
        return

    # FEEDBACK HANDLER
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
    
    await context.bot.send_chat_action(chat_id=user_id, action="typing")
    result = await GHOST.process_message(user_id, user_text)
    
    if not result:
        await update.message.reply_text("❌ Session expired. /start")
        return

    # LOGIC TRIGGERS
    if result == "TRIGGER_SKIP":
        await asyncio.sleep(0.5)
        await update.message.reply_text("🚫 **[AI LOGIC]** Partner Disconnected (Skip Trigger).")
        context.user_data['active'] = False
        return

    if result == "TRIGGER_INDIAN_MALE_BEG":
        await asyncio.sleep(1)
        await update.message.reply_text("bro any girls id?")
        await context.bot.send_chat_action(chat_id=user_id, action="typing")
        await asyncio.sleep(2)
        await update.message.reply_text("give me")
        await asyncio.sleep(1)
        await update.message.reply_text("🚫 **[AI LOGIC]** Partner Disconnected.")
        context.user_data['active'] = False
        return

    # NORMAL REPLY
    if result.get("type") == "text":
        await asyncio.sleep(result["delay"])
        
        kb = [[InlineKeyboardButton("👍 Good", callback_data="fb_1"), InlineKeyboardButton("👎 Bad", callback_data="fb_-1")]]
        context.user_data['last_exchange'] = (user_text, result["content"])
        
        await update.message.reply_text(result["content"], reply_markup=InlineKeyboardMarkup(kb))

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['active'] = False
    await update.message.reply_text("🛑 Chat stopped. /start to restart.")

if __name__ == '__main__':
    if not BOT_TOKEN: print("❌ Error: BOT_TOKEN missing")
    else:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stop", stop_command))
        app.add_handler(CallbackQueryHandler(button_handler))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat_handler))
        print("🤖 TEST BOT ONLINE")
        app.run_polling()
