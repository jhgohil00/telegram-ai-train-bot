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

# DB CONNECTION POOL
DB_POOL = None
try:
    DB_POOL = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
    print("✅ DB Connected.")
except Exception as e:
    print(f"❌ DB Error: {e}")

# INIT ENGINE
GHOST = GhostEngine(DB_POOL)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Fetch Personas from DB
    personas = GHOST.get_personas_list()
    
    # 2. Build Menu
    keyboard = []
    for key, name in personas:
        keyboard.append([InlineKeyboardButton(name, callback_data=f"sel_{key}")])
    
    await update.message.reply_text(
        "🧪 **AI TRAINING LAB**\n\nSelect a Persona to test:", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    # PERSONA SELECTION
    if q.data.startswith("sel_"):
        persona_key = q.data.split("_", 1)[1]
        user_id = q.from_user.id
        
        # Start AI
        success = await GHOST.start_chat(user_id, persona_key)
        
        if success:
            await q.edit_message_text(f"✅ **Active: {persona_key}**\n\nSay 'Hi' to start.\nType /stop to end.")
            context.user_data['active'] = True
        else:
            await q.edit_message_text("❌ Error loading persona.")
        return

    # FEEDBACK (THUMBS UP/DOWN)
    if q.data.startswith("fb_"):
        # Format: fb_RATING
        rating = int(q.data.split("_")[1])
        last = context.user_data.get('last_exchange')
        
        if last:
            uid = q.from_user.id
            u_in, a_out = last
            GHOST.save_feedback(uid, u_in, a_out, rating)
            
            # Visual Confirmation
            emoji = "✅ Saved" if rating == 1 else "🗑️ Ignored"
            await q.edit_message_reply_markup(None) # Remove buttons
            # await q.message.reply_text(emoji) # Optional: Send text confirm
        return

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('active'):
        await update.message.reply_text("⚠️ Select a persona first: /start")
        return

    user_id = update.effective_user.id
    user_text = update.message.text
    
    # 1. Typing Indicator
    await context.bot.send_chat_action(chat_id=user_id, action="typing")
    
    # 2. Process with AI
    result = await GHOST.process_message(user_id, user_text)
    
    if not result:
        await update.message.reply_text("❌ Session expired. /start")
        return

    # 3. SPECIAL LOGIC HANDLERS
    if result == "TRIGGER_SKIP":
        await asyncio.sleep(0.5)
        await update.message.reply_text("🚫 **[AI LOGIC]** Partner Disconnected (Skip Trigger).")
        context.user_data['active'] = False
        return

    if result == "TRIGGER_INDIAN_MALE_BEG":
        # The Scripted Sequence
        await asyncio.sleep(1)
        await update.message.reply_text("bro do you have any girls id?")
        await context.bot.send_chat_action(chat_id=user_id, action="typing")
        await asyncio.sleep(2)
        await update.message.reply_text("give me")
        await asyncio.sleep(1.5)
        await update.message.reply_text("im single")
        await asyncio.sleep(1)
        await update.message.reply_text("🚫 **[AI LOGIC]** Partner Disconnected.")
        context.user_data['active'] = False
        return

    # 4. NORMAL AI REPLY
    if result.get("type") == "text":
        ai_reply = result["content"]
        delay = result["delay"]
        
        # Simulate Wait
        await asyncio.sleep(delay)
        
        # Send Reply with Rating Buttons
        kb = [
            [InlineKeyboardButton("👍 Good (Save)", callback_data="fb_1"),
             InlineKeyboardButton("👎 Bad", callback_data="fb_-1")]
        ]
        
        # Save context for feedback
        context.user_data['last_exchange'] = (user_text, ai_reply)
        
        await update.message.reply_text(ai_reply, reply_markup=InlineKeyboardMarkup(kb))

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['active'] = False
    await update.message.reply_text("🛑 Chat stopped. /start to restart.")

if __name__ == '__main__':
    if not BOT_TOKEN:
        print("❌ Error: BOT_TOKEN missing")
    else:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stop", stop_command))
        app.add_handler(CallbackQueryHandler(button_handler))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat_handler))
        
        print("🤖 TEST BOT ONLINE")
        app.run_polling()
