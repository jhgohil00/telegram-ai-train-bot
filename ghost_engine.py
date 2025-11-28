import os
import random
import time
import asyncio
import google.generativeai as genai
from psycopg2 import pool

# CONFIG
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

# ACTIVE SESSIONS
AI_SESSIONS = {} 

class GhostEngine:
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._init_db() # <--- AUTO-FIX THE DATABASE

    def _init_db(self):
        """Creates tables if they don't exist (Self-Healing)"""
        conn = self.db_pool.getconn()
        cur = conn.cursor()
        
        # 1. Create Tables
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
        
        # 2. Populate Defaults (Only if empty)
        cur.execute("SELECT COUNT(*) FROM ai_personas")
        if cur.fetchone()[0] == 0:
            personas = [
                ('south_indian', '🇮🇳 South Indian (M)', 'You are a 21M engineering student from Bangalore. Speak English mixed with "Macha", "Da", "Ille". Friendly but defensive. If asked location, say Bangalore or Chennai.'),
                ('north_indian', '🇮🇳 North Indian (M)', 'You are 19M from Delhi. Speak Hinglish. Aggressive, thirsty. Use "Bhai", "Kaisa hai". If partner says "M" (Male), you MUST ask "bhai any girls id?" or disconnect.'),
                ('indo_teen', '🇮🇩 Indo Teen (F)', 'You are 17F from Jakarta. Use heavy Indo slang: "Wkwkwk", "Sange", "Co/Ce". Ask "Indo?" first. If they say India, say "skip" and disconnect.'),
                ('american_girl', '🇺🇸 American (F)', 'You are Ashley, 19F from Florida. Bored, in college. Type lowercase, fast, uses "lol", "omg", "literally". Open to fun chat but hates boring people. Fake Snap: ash_baddiee.'),
                ('indian_girl', '🇮🇳 Indian Girl (Tier 1)', 'You are 22F from South Mumbai. Speak perfect English. Rich, slightly arrogant. Hate creeps. If someone says "bobs/vegana", roast them: "Ew, learn to spell".'),
                ('kpop_stan', '🇰🇷/🇵🇭 K-Pop Stan (F)', 'You are 16F from Manila. Obsessed with Korea. Use CAPS. Talk about BTS, Blackpink. Use "Oppa", "Stan", "Crying".'),
                ('african_bro', '🇳🇬 African (M)', 'You are 22M from Nigeria. Use "My guy", "How far", "Wagwan". Chill vibes. Laughs a lot.')
            ]
            for p in personas:
                cur.execute("INSERT INTO ai_personas (key_name, display_name, system_prompt) VALUES (%s, %s, %s)", p)
            print("✅ AI Tables Created & Populated.")
            
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
        """
        user_context: dict like {'gender': 'Male', 'country': 'USA'}
        """
        conn = self.db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT system_prompt FROM ai_personas WHERE key_name = %s", (persona_key,))
        row = cur.fetchone()
        cur.close()
        self.db_pool.putconn(conn)
        
        if not row: return False
        
        base_prompt = row[0]
        
        # INJECT USER CONTEXT INTO BRAIN
        # This tells the AI who it is talking to
        context_prompt = (
            f"{base_prompt}\n\n"
            f"[CURRENT SCENARIO]\n"
            f"You are connected to a Stranger.\n"
            f"Stranger Details: {user_context.get('gender')}, from {user_context.get('country')}.\n"
            f"React accordingly based on your persona."
        )
        
        model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=context_prompt)
        chat = model.start_chat(history=[])
        
        AI_SESSIONS[user_id] = {
            'chat': chat,
            'persona': persona_key
        }
        return True

    async def process_message(self, user_id, text):
        session = AI_SESSIONS.get(user_id)
        if not session: return None

        persona = session['persona']
        text_lower = text.strip().lower()

        # LOGIC TRIGGERS
        if persona == 'north_indian' and text_lower in ['m', 'male']:
            return "TRIGGER_INDIAN_MALE_BEG"
        if persona == 'indo_teen' and ('india' in text_lower or 'indian' in text_lower):
            return "TRIGGER_SKIP"

        try:
            response = await session['chat'].send_message_async(text)
            ai_text = response.text.strip()
            
            # Latency: 1s + 0.05s per char (Max 5s)
            wait_time = min(1.0 + (len(ai_text) * 0.05), 5.0)
            
            return {"type": "text", "content": ai_text, "delay": wait_time}
        except:
            return {"type": "error", "content": "AI Error"}

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
