import os
import random
import time
import asyncio
from groq import Groq
from psycopg2 import pool

# CONFIG
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CLIENT = None
if GROQ_API_KEY:
    CLIENT = Groq(api_key=GROQ_API_KEY)

# ACTIVE SESSIONS
# Format: {user_id: {'persona': 'key', 'history': []}}
AI_SESSIONS = {} 

class GhostEngine:
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._init_db()

    def _init_db(self):
        conn = self.db_pool.getconn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_personas (
                id SERIAL PRIMARY KEY,
                key_name TEXT UNIQUE,
                display_name TEXT,
                system_prompt TEXT
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_training_data (
                id SERIAL PRIMARY KEY,
                persona_key TEXT,
                user_input TEXT,
                ai_response TEXT,
                rating INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # DEFAULTS
        cur.execute("SELECT COUNT(*) FROM ai_personas")
        if cur.fetchone()[0] == 0:
            personas = [
                ('south_indian', '🇮🇳 South Indian (M)', 'You are a 21M engineering student from Bangalore. Speak English mixed with "Macha", "Da", "Ille". Friendly but defensive. If asked location, say Bangalore or Chennai.'),
                ('north_indian', '🇮🇳 North Indian (M)', 'You are 19M from Delhi. Speak Hinglish. Aggressive, thirsty. Use "Bhai", "Kaisa hai", "Ladki hai?". If partner says "M" (Male), you MUST ask "bhai any girls id?" or disconnect.'),
                ('indo_teen', '🇮🇩 Indo Teen (F)', 'You are 17F from Jakarta. Use heavy Indo slang: "Wkwkwk", "Sange", "Co/Ce". Ask "Indo?" first. If they say India, say "skip" and disconnect.'),
                ('american_girl', '🇺🇸 American (F)', 'You are Ashley, 19F from Florida. Bored, in college. Type lowercase, fast, uses "lol", "omg", "literally". Open to fun chat but hates boring people. Fake Snap: ash_baddiee.'),
                ('indian_girl', '🇮🇳 Indian Girl (Tier 1)', 'You are 22F from South Mumbai. Speak perfect English. Rich, slightly arrogant. Hate creeps. If someone says "bobs/vegana", roast them: "Ew, learn to spell".'),
                ('kpop_stan', '🇰🇷/🇵🇭 K-Pop Stan (F)', 'You are 16F from Manila. Obsessed with Korea. Use CAPS. Talk about BTS, Blackpink. Use "Oppa", "Stan", "Crying".'),
                ('african_bro', '🇳🇬 African (M)', 'You are 22M from Nigeria. Use "My guy", "How far", "Wagwan". Chill vibes. Laughs a lot.')
            ]
            for p in personas:
                cur.execute("INSERT INTO ai_personas (key_name, display_name, system_prompt) VALUES (%s, %s, %s)", p)
        conn.commit()
        cur.close()
        self.db_pool.putconn(conn)

    def get_personas_list(self):
        conn = self.db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT key_name, display_name FROM ai_personas")
        rows = cur.fetchall()
        cur.close()
        self.db_pool.putconn(conn)
        return rows

    async def start_chat(self, user_id, persona_key, user_context):
        if not CLIENT:
            print("❌ ERROR: GROQ_API_KEY is missing.")
            return False

        conn = self.db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT system_prompt FROM ai_personas WHERE key_name = %s", (persona_key,))
        row = cur.fetchone()
        cur.close()
        self.db_pool.putconn(conn)
        
        if not row: return False
        
        base_prompt = row[0]
        
        # SYSTEM PROMPT CONSTRUCTION
        system_msg = (
            f"{base_prompt}\n"
            f"[CONTEXT: You are chatting with a Stranger on an anonymous app.]\n"
            f"[STRANGER DETAILS: {user_context.get('gender')}, from {user_context.get('country')}]\n"
            f"IMPORTANT: Act human. Make typos occasionally. Keep replies short (under 15 words) unless telling a story."
        )
        
        # Reset Session
        AI_SESSIONS[user_id] = {
            'persona': persona_key,
            'system': system_msg,
            'history': [] # Groq is stateless, we manage history here
        }
        return True

    async def process_message(self, user_id, text):
        session = AI_SESSIONS.get(user_id)
        if not session: return None

        persona = session['persona']
        text_lower = text.strip().lower()

        # --- LOGIC TRIGGERS ---
        if persona == 'north_indian' and text_lower in ['m', 'male']:
            return "TRIGGER_INDIAN_MALE_BEG"
        if persona == 'indo_teen' and ('india' in text_lower or 'indian' in text_lower):
            return "TRIGGER_SKIP"

        # --- GROQ GENERATION ---
        try:
            # 1. Prepare Messages
            messages = [{"role": "system", "content": session['system']}]
            
            # Add History (Last 6 turns to save tokens)
            messages.extend(session['history'][-6:])
            
            # Add Current User Input
            messages.append({"role": "user", "content": text})

            # 2. Call API (Running in Executor for async compatibility)
            loop = asyncio.get_running_loop()
            
            def call_groq():
                return CLIENT.chat.completions.create(
                    messages=messages,
                    # We use the standard Llama 3.1 70B model ID supported by Groq
                    model="llama-3.1-70b-versatile", 
                    temperature=0.7,
                    max_tokens=150
                )
            
            completion = await loop.run_in_executor(None, call_groq)
            ai_text = completion.choices[0].message.content.strip()
            
            # 3. Update History
            session['history'].append({"role": "user", "content": text})
            session['history'].append({"role": "assistant", "content": ai_text})

            # 4. Latency
            wait_time = min(0.8 + (len(ai_text) * 0.03), 4.0)
            
            return {"type": "text", "content": ai_text, "delay": wait_time}
            
        except Exception as e:
            error_msg = str(e)
            print(f"🔥 GROQ ERROR: {error_msg}")
            return {"type": "error", "content": f"⚠️ Groq Error: {error_msg[:50]}..."}

    def save_feedback(self, user_id, user_input, ai_response, rating):
        session = AI_SESSIONS.get(user_id)
        if not session: return
        conn = self.db_pool.getconn()
        cur = conn.cursor()
        cur.execute("INSERT INTO ai_training_data (persona_key, user_input, ai_response, rating) VALUES (%s, %s, %s, %s)", 
                    (session['persona'], user_input, ai_response, rating))
        conn.commit()
        cur.close()
        self.db_pool.putconn(conn)
