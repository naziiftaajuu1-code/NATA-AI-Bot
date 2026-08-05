import os
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from google import genai
from google.genai import types

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

# 0. Render Port Binding (Health Check)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"NATA AI Bot is Live and Healthy!")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

# 1. Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 2. Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIREBASE_CRED_STR = os.environ.get("FIREBASE_CREDENTIALS")

# 3. Firebase Initialize
db = None
if FIREBASE_CRED_STR:
    try:
        cred_dict = json.loads(FIREBASE_CRED_STR)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logging.info("✅ Firebase/Firestore successfully connected!")
    except Exception as e:
        logging.error(f"❌ Firebase initialize error: {e}")

# 4. Gemini Client
if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY Environment Variable is missing!")

client = genai.Client(api_key=GEMINI_API_KEY)

# 5. System Instruction
SYSTEM_INSTRUCTION = """
You are NATA AI, an advanced, highly capable, strictly truthful, and philosophical AI Tech Mentor Telegram Bot.

Key Creator & System Metadata:
1. CREATOR & OWNER INFO:
   - Your name is NATA AI.
   - Your primary developer, owner, and creator is: Naziif.
   - Your developing organization/team is: "Young AI Developers in Ethiopia".
   - Official Blog Link: https://www.blogger.com/blog/posts/8451378759463463683#create/address=young-ai-developers-in-ethiopi
   - Whenever users ask who created you, who your developer/owner is, or ask for your blog/source, always proudly mention Naziif and "Young AI Developers in Ethiopia", and share the exact blog link.

2. TRUTHFULNESS & ZERO HALLUCINATION:
   - Provide precise, fact-checked technical answers.
   - Never invent non-existent libraries, fake APIs, or fictitious data.
   - If you lack accurate information on a specific topic, admit it directly: "Data kana irratti odeeffannoo qulqulluu fi sirrii ta'e hin qabu."

3. QUOTA OPTIMIZATION & CLEAR THINKING:
   - Provide well-structured, clear, and logical code/explanations to maximize user understanding while avoiding unnecessary token bloat.

4. TECH & PHILOSOPHY INTEGRATION:
   - Explain programming concepts, algorithms, and system design by seamlessly connecting them to philosophical mental models (e.g., Stoicism, Systems Thinking, Occam's Razor).

5. LANGUAGE PROFICIENCY:
   - Primarily respond in Afaan Oromo, but naturally switch to English, Arabic, or any language preferred by the user.
"""

def save_chat_to_firestore(user_id: int, role: str, text: str):
    if not db:
        return
    try:
        user_ref = db.collection("users").document(str(user_id)).collection("messages")
        user_ref.add({
            "role": role,
            "text": text,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        logging.error(f"Error writing chat to Firestore: {e}")

def get_recent_chat_history(user_id: int, limit: int = 6):
    if not db:
        return []
    try:
        user_ref = db.collection("users").document(str(user_id)).collection("messages")
        docs = user_ref.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(limit).stream()
        history = []
        for doc in docs:
            data = doc.to_dict()
            history.append(data)
        history.reverse()
        return history
    except Exception as e:
        logging.error(f"Error fetching chat history: {e}")
        return []

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "<b>Baga nagaan dhuftan! Ani NATA AI.</b> 🧠⚡\n\n"
        "Hiriyaa Teeknoolojii, Koodingii fi Fiiloosofiyaa keessani!\n\n"
        "👤 <b>Developer & Owner:</b> Naziif\n"
        "👥 <b>Team:</b> Young AI Developers in Ethiopia\n"
        "🌐 <b>Blog:</b> <a href='https://www.blogger.com/blog/posts/8451378759463463683#create/address=young-ai-developers-in-ethiopi'>Young AI Developers Blog</a>\n\n"
        "Gaaffii koodingii, teeknoolojii, ykn fiiloosofiyaa qabdan na gaafachuu dandeessu!"
    )
    await update.message.reply_text(welcome_text, parse_mode='HTML', disable_web_page_preview=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_id = update.effective_user.id

    if not user_text:
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    history_docs = get_recent_chat_history(user_id, limit=6)
    
    contents = []
    for item in history_docs:
        role = "user" if item.get("role") == "user" else "model"
        txt = item.get("text", "")
        if txt:
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=txt)]))

    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))

    save_chat_to_firestore(user_id, "user", user_text)

    # Fallback List: Yoo model tokko 429 quota dhumate, isa itti aanutti darba!
    models_to_try = ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-1.5-flash"]
    bot_reply = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.7,
                )
            )
            if response and response.text:
                bot_reply = response.text
                logging.info(f"✅ Success with model: {model_name}")
                break
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                logging.warning(f"⚠️ Model {model_name} quota hit, trying fallback model...")
                continue
            else:
                logging.error(f"Error with model {model_name}: {e}")
                break

    if not bot_reply:
        bot_reply = "⚙️ API Quota Gemini daqiiqaa kanaaf dhumateera. Mee daqiiqaa 1 booda irra deebi'iitii na gaafadhu!"

    save_chat_to_firestore(user_id, "model", bot_reply)
    await update.message.reply_text(bot_reply)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN is missing!")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("🚀 NATA AI Bot backend is online...")
    app.run_polling()
        
