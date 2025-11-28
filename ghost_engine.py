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

    def get_personas_list(self):
        """Fetches list of available personas for the menu"""
        conn = self.db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT key_name, display_name FROM ai_personas")
        rows = cur.fetchall()
        cur.close()
        self.db_pool.putconn(conn)
        return rows

    def get_winning_examples(self, persona_key, user_input):
        """Finds past 'Thumbs Up' chats to mimic"""
        conn = self.db_pool.getconn()
        cur = conn.cursor()
        # Find 2 random 'Good' examples for this persona
        cur.execute("""
            SELECT user_input, ai_response FROM ai_training_data 
            WHERE persona_key = %s AND rating = 1 
            ORDER BY RANDOM() LIMIT 2
        """, (persona_key,))
        rows = cur.fetchall()
        cur.close()
        self.db_pool.putconn(conn)
        
        examples = ""
        if rows:
            examples = "\n\n[STYLE REFERENCE - MIMIC THESE EXAMPLES]:\n"
            for r in rows:
                examples += f"User: {r[0]}\nYou: {r[1]}\n"
        return examples

    async def start_chat(self, user_id, persona_key):
        """Initializes a new session"""
        conn = self.db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT system_prompt FROM ai_personas WHERE key_name = %s", (persona_key,))
        row = cur.fetchone()
        cur.close()
        self.db_pool.putconn(conn)
        
        if not row: return False
        
        system_prompt = row[0]
        
        # Initialize Gemini
        model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_prompt)
        chat = model.start_chat(history=[])
        
        AI_SESSIONS[user_id] = {
            'chat': chat,
            'persona': persona_key,
            'step_counter': 0
        }
        return True

    async def process_message(self, user_id, text):
        session = AI_SESSIONS.get(user_id)
        if not session: return None

        persona = session['persona']
        text_lower = text.strip().lower()

        # --- 1. SPECIAL LOGIC TRIGGERS ---
        
        # A. NORTH INDIAN MALE LOGIC (The "M" Trigger)
        if persona == 'north_indian' and text_lower in ['m', 'male']:
            # Scripted sequence for realism
            return "TRIGGER_INDIAN_MALE_BEG"

        # B. INDO LOGIC (The "India" Skip)
        if persona == 'indo_teen' and ('india' in text_lower or 'indian' in text_lower):
            return "TRIGGER_SKIP"

        # --- 2. AI GENERATION ---
        
        # Inject RAG (Past Wins)
        examples = self.get_winning_examples(persona, text)
        full_prompt = f"{text}{examples}"
        
        try:
            # Generate
            response = await session['chat'].send_message_async(full_prompt)
            ai_text = response.text.strip()
            
            # --- 3. LATENCY SIMULATION ---
            # 1s base + 0.05s per character
            wait_time = 1.0 + (len(ai_text) * 0.05)
            # Cap at 5s so it doesn't feel broken
            wait_time = min(wait_time, 5.0)
            
            return {"type": "text", "content": ai_text, "delay": wait_time}
            
        except Exception as e:
            return {"type": "error", "content": "AI Error"}

    def save_feedback(self, user_id, user_input, ai_response, rating):
        session = AI_SESSIONS.get(user_id)
        if not session: return
        
        conn = self.db_pool.getconn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ai_training_data (persona_key, user_input, ai_response, rating)
            VALUES (%s, %s, %s, %s)
        """, (session['persona'], user_input, ai_response, rating))
        conn.commit()
        cur.close()
        self.db_pool.putconn(conn)
