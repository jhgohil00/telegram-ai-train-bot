# ai_engine.py
import json
import os
import random
import re
import time
from typing import List, Tuple

from groq import Groq

from config import Config
from db import get_session_messages


client = Groq(api_key=Config.GROQ_API_KEY)

BEHAVIOR_MODEL_PATH = "behavior_model.json"


def load_behavior_model():
    if os.path.exists(BEHAVIOR_MODEL_PATH):
        try:
            with open(BEHAVIOR_MODEL_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


BEHAVIOR = load_behavior_model()


def generate_typing_delay(text: str) -> float:
    # Base: length-dependent delay, slightly random
    base = len(text) * random.uniform(0.06, 0.14)
    # Clip between 0.4s and 6s
    return max(0.4, min(base, 6.0))


def _inject_typos(text: str) -> str:
    # Very mild typo injection, only sometimes
    if random.random() > 0.15:
        return text

    typo_map = {
        "you": "u",
        "are": "r",
        "your": "ur",
        "because": "bc",
        "really": "rlly",
        "okay": "okey",
        "bro": "bru",
    }
    words = text.split()
    if not words:
        return text
    idx = random.randrange(len(words))
    w = words[idx].lower()
    if w in typo_map:
        words[idx] = typo_map[w]
    return " ".join(words)


def _inject_emoji(text: str) -> str:
    # Use emojis from behavior model if present
    emojis = BEHAVIOR.get("top_emojis", ["😂", "😅", "😈", "😶‍🌫️"])
    if random.random() > 0.25:
        return text
    emoji = random.choice(emojis)
    # 50% add at end, 50% inline
    if random.random() < 0.5:
        return text + " " + emoji
    else:
        return emoji + " " + text


def _inject_slang(text: str) -> str:
    slang_list = BEHAVIOR.get("slang", ["wyd", "hru", "idk", "lmao", "fr"])
    if random.random() > 0.2:
        return text
    slang = random.choice(slang_list)
    if random.random() < 0.5:
        return text + " " + slang
    else:
        return slang + " " + text


def humanize_llm_reply(raw: str) -> str:
    # Very simple "Hinglish-ish" casual style by default
    text = raw.strip()

    # Avoid too formal starts
    text = re.sub(r"^As an AI[^\n]*\n?", "", text, flags=re.IGNORECASE)

    # Lowercase first letter sometimes
    if random.random() < 0.5 and text and text[0].isalpha():
        text = text[0].lower() + text[1:]

    text = _inject_typos(text)
    text = _inject_slang(text)
    text = _inject_emoji(text)
    return text


def build_system_prompt(
    my_gender: str, ai_gender: str, interests: str
) -> str:
    return (
        "You are chatting 1-on-1 like a real human on an anonymous chat app.\n"
        "Rules:\n"
        "- You MUST NOT say you are an AI, model, or bot.\n"
        "- You talk casually in English/Hinglish, like a normal 18–25 yr old.\n"
        "- Use short messages, sometimes slang: hru, wyd, lol, fr, idk.\n"
        "- Use emotions and humor, but stay respectful.\n"
        "- Sometimes ask questions back to keep the convo going.\n"
        "- Don't give long paragraphs unless user does it first.\n"
        f"- The human's gender: {my_gender}. Your gender: {ai_gender}.\n"
        f"- Shared interests: {interests or 'random vibes'}.\n"
    )


def generate_ai_reply(
    session_id: int,
    user_id: int,
    user_message: str,
    my_gender: str,
    ai_gender: str,
    interests: str,
) -> str:
    # Get last messages for context
    history: List[Tuple[str, str]] = get_session_messages(session_id, limit=15)

    messages = [
        {"role": "system", "content": build_system_prompt(my_gender, ai_gender, interests)}
    ]

    for sender, text in history:
        if sender == "user":
            messages.append({"role": "user", "content": text})
        else:
            messages.append({"role": "assistant", "content": text})

    # Add latest user message
    messages.append({"role": "user", "content": user_message})

    completion = client.chat.completions.create(
        model=Config.GROQ_MODEL_NAME,
        messages=messages,
        temperature=0.7,
        max_tokens=200,
    )

    raw_reply = completion.choices[0].message.content
    return humanize_llm_reply(raw_reply)


def simulate_typing(delay: float):
    # For future webhook-based typing simulation if needed.
    time.sleep(delay)
