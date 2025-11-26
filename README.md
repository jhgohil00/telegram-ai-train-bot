# Ghostmode AI Training Bot

A private Telegram bot to chat with an AI "stranger" and log all messages for training.

## Features

- `/addinterest` – set:
  - your gender (Male/Female/Other)
  - AI gender (Male/Female/Other)
  - shared interests (comma-separated)
- `/start` – start chatting with the AI
- `/stop` – end current chat
- AI uses Groq LLM (e.g. `mixtral-8x7b-32768`)
- All chats stored in `ai_train.db`
- `ai_trainer.py` builds `behavior_model.json` from your logs so AI style becomes closer to you.

## Local Setup

```bash
python -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="your_bot_token_here"
export GROQ_API_KEY="your_groq_key_here"
export GROQ_MODEL_NAME="mixtral-8x7b-32768"

python main.py
