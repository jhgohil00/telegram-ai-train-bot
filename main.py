# main.py
import asyncio
import logging

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from config import Config
from db import (
    init_db,
    upsert_profile,
    get_profile,
    create_session,
    end_session,
    log_message,
)
from ai_engine import generate_ai_reply, generate_typing_delay

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states for /addinterest
ASK_MY_GENDER, ASK_AI_GENDER, ASK_INTERESTS = range(3)


def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [["/start", "/stop"], ["/addinterest", "/help"]],
        resize_keyboard=True,
    )


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    profile = get_profile(user_id)
    if not profile:
        await update.message.reply_text(
            "First set your genders & interests using /addinterest 😊",
            reply_markup=main_menu_keyboard(),
        )
        return

    my_gender, ai_gender, interests = profile

    if context.user_data.get("in_chat"):
        await update.message.reply_text(
            "You are already in chat with the AI.", reply_markup=main_menu_keyboard()
        )
        return

    # Create new session
    session_id = create_session(user_id, my_gender, ai_gender, interests)
    context.user_data["in_chat"] = True
    context.user_data["session_id"] = session_id
    context.user_data["my_gender"] = my_gender
    context.user_data["ai_gender"] = ai_gender
    context.user_data["interests"] = interests

    await update.message.reply_text(
        "👻 Ghost Mode ON.\n\nYou are now chatting with the AI as if it was a real stranger.",
        reply_markup=main_menu_keyboard(),
    )

    # AI can start the convo
    opening = "hey, what's up? :)"
    log_message(session_id, "ai", opening)
    delay = generate_typing_delay(opening)
    await asyncio.sleep(delay)
    await update.message.reply_text(opening)


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("in_chat"):
        await update.message.reply_text(
            "You are not in a chat right now.", reply_markup=main_menu_keyboard()
        )
        return

    session_id = context.user_data.get("session_id")
    if session_id:
        end_session(session_id)

    context.user_data["in_chat"] = False
    context.user_data["session_id"] = None

    await update.message.reply_text(
        "👻 Ghost chat ended.\nUse /start to start again.",
        reply_markup=main_menu_keyboard(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🧪 *Ghost Training Bot*\n\n"
        "/addinterest - Set your gender, AI gender & shared interests\n"
        "/start - Start chatting with your AI stranger\n"
        "/stop - Stop current chat\n"
        "/help - Show this help\n\n"
        "This bot is only for *training* your AI. Every message is logged so the AI can "
        "learn your style later."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu_keyboard())


# /addinterest flow


async def addinterest_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    keyboard = [["Male", "Female", "Other"]]
    await update.message.reply_text(
        "1️⃣ Choose *your* gender:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
        parse_mode="Markdown",
    )
    return ASK_MY_GENDER


async def ask_ai_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if text not in ["Male", "Female", "Other"]:
        await update.message.reply_text("Please choose from the buttons.")
        return ASK_MY_GENDER

    context.user_data["my_gender_tmp"] = text

    keyboard = [["Male", "Female", "Other"]]
    await update.message.reply_text(
        "2️⃣ Choose AI's gender:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
        parse_mode="Markdown",
    )
    return ASK_AI_GENDER


async def ask_interests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if text not in ["Male", "Female", "Other"]:
        await update.message.reply_text("Please choose from the buttons.")
        return ASK_AI_GENDER

    context.user_data["ai_gender_tmp"] = text

    await update.message.reply_text(
        "3️⃣ Now type shared interests (comma separated)\n\n"
        "Example: `music, movies, gaming, flirting, kdrama, travel`",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_INTERESTS


async def finish_addinterest(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    interests = (update.message.text or "").strip()
    user_id = update.effective_user.id

    my_gender = context.user_data.get("my_gender_tmp", "Hidden")
    ai_gender = context.user_data.get("ai_gender_tmp", "Hidden")

    upsert_profile(user_id, my_gender, ai_gender, interests)

    await update.message.reply_text(
        f"✅ Profile saved.\n\nYou: *{my_gender}*\nAI: *{ai_gender}*\nInterests: *{interests}*",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

    # clear temp
    context.user_data.pop("my_gender_tmp", None)
    context.user_data.pop("ai_gender_tmp", None)

    return ConversationHandler.END


async def cancel_addinterest(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.message.reply_text(
        "Cancelled.", reply_markup=main_menu_keyboard()
    )
    context.user_data.pop("my_gender_tmp", None)
    context.user_data.pop("ai_gender_tmp", None)
    return ConversationHandler.END


# Chat handler


async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    if not context.user_data.get("in_chat"):
        # ignore or politely nudge
        await update.message.reply_text(
            "Use /start to begin chatting with the AI.", reply_markup=main_menu_keyboard()
        )
        return

    user_id = update.effective_user.id
    session_id = context.user_data.get("session_id")
    my_gender = context.user_data.get("my_gender", "Hidden")
    ai_gender = context.user_data.get("ai_gender", "Hidden")
    interests = context.user_data.get("interests", "")

    text = update.message.text.strip()

    # Log user message
    log_message(session_id, "user", text)

    # Generate AI reply
    ai_reply = generate_ai_reply(
        session_id=session_id,
        user_id=user_id,
        user_message=text,
        my_gender=my_gender,
        ai_gender=ai_gender,
        interests=interests,
    )

    # Simulate human typing delay
    delay = generate_typing_delay(ai_reply)
    await asyncio.sleep(delay)

    # Log and send AI reply
    log_message(session_id, "ai", ai_reply)
    await update.message.reply_text(ai_reply)


async def unknown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Unknown command. Use /help.", reply_markup=main_menu_keyboard()
    )


def main():
    Config.validate()
    init_db()

    app = ApplicationBuilder().token(Config.TELEGRAM_BOT_TOKEN).build()

    # Conversation for /addinterest
    conv = ConversationHandler(
        entry_points=[CommandHandler("addinterest", addinterest_start)],
        states={
            ASK_MY_GENDER: [MessageHandler(filters.TEXT & (~filters.COMMAND), ask_ai_gender)],
            ASK_AI_GENDER: [MessageHandler(filters.TEXT & (~filters.COMMAND), ask_interests)],
            ASK_INTERESTS: [MessageHandler(filters.TEXT & (~filters.COMMAND), finish_addinterest)],
        },
        fallbacks=[CommandHandler("cancel", cancel_addinterest)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    # Chat handler (fallback for any text)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), chat_handler))

    # Unknown command handler
    app.add_handler(MessageHandler(filters.COMMAND, unknown_cmd))

    app.run_polling()


if __name__ == "__main__":
    main()
