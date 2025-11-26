# ai_trainer.py
import json
import re
from collections import Counter

from db import get_connection


def train_behavior_model(output_path: str = "behavior_model.json"):
    conn = get_connection()
    cur = conn.cursor()

    # Only user messages (sender = 'user')
    cur.execute(
        "SELECT text FROM messages WHERE sender = 'user'"
    )
    rows = cur.fetchall()
    conn.close()

    texts = [r[0] for r in rows if r[0]]

    # Basic stats
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF]+",
        flags=re.UNICODE,
    )

    words_counter = Counter()
    emoji_counter = Counter()

    for t in texts:
        # emojis
        emojis = emoji_pattern.findall(t)
        for e in emojis:
            emoji_counter[e] += 1

        # words (rough)
        cleaned = emoji_pattern.sub(" ", t)
        tokens = re.findall(r"[A-Za-z]+", cleaned.lower())
        words_counter.update(tokens)

    # slang candidates = words that are short & frequent
    slang_candidates = [
        w
        for w, c in words_counter.items()
        if c >= 5 and (len(w) <= 4 or w in ["ngl", "lmao", "fr", "idk", "wyd", "hru"])
    ]

    top_emojis = [e for e, _ in emoji_counter.most_common(10)]
    behavior = {
        "slang": slang_candidates,
        "top_emojis": top_emojis,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(behavior, f, ensure_ascii=False, indent=2)

    print(f"✅ behavior_model.json updated with {len(slang_candidates)} slang & {len(top_emojis)} emojis.")


if __name__ == "__main__":
    train_behavior_model()
