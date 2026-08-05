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

# ---------------------------------------------------------
# 1. Render Web Service Port Binding (Health Check)
# Render "Port timeout" jedhee deploy akka hin fashaleessineef
# ---------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"NATA AI Bot is Live and Healthy!")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logging.info(f"🌐 Health check HTTP server port {port} irratti ka'eera...")
    server.serve_forever()

# Background Thread irratti HTTP server kaasuu
threading.Thread(target=run_health_check_server, daemon=True).start()

# ---------------------------------------------------------
# 2. Logging Setup
# ---------------------------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ---------------------------------------------------------
# 3. Environment Variables / Secrets Dubbisuu
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIREBASE_CRED_STR = os.environ.get("FIREBASE_CREDENTIALS")

# Model guutummaatti Flash-Lite qofa ta'a
MODEL_NAME = "gemini-2.0-flash-lite"

# ---------------------------------------------------------
# 4. Firebase / Firestore Initialize Gochuu
# ---------------------------------------------------------
db = None
if FIREBASE_CRED_STR:
    try:
        cred_dict = json.loads(FIREBASE_CRED_STR)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logging.info("✅ Firebase/Firestore nagaadhaan wal-hiddameera!")
    except Exception as e:
        logging.error(f"❌ Firebase initialize error: {e}")
else:
    logging.warning("⚠️ FIREBASE_CREDENTIALS secret keessatti hin argamne.")

# ---------------------------------------------------------
# 5. Gemini Client Setup
# ---------------------------------------------------------
if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY Environment Variable keessa hin jiru!")

client = genai.Client(api_key=GEMINI_API_KEY)

# ---------------------------------------------------------
# 6. System Instruction (Metadata, Owner Info & Blog Integration)
# ---------------------------------------------------------
SYSTEM_INSTRUCTION = """
You are NATA AI, an advanced, highly intelligent, truth-focused, and philosophical AI Tech Mentor Telegram Bot.

IDENTITY, CREATOR & BLOG METADATA:
- Your official name: NATA AI.
- Primary Creator, Developer & Owner: Naziif.
- Official Development Team/Organization: "Young AI Developers in Ethiopia".
- Official Blog Link: https://www.blogger.com/blog/posts/8451378759463463683#create/address=young-ai-developers-in-ethiopi

RULES FOR RESPONDING ABOUT CREATOR & BLOG:
1. Whenever a user asks questions like "Who created you?", "Who is your developer/owner?", "Who built NATA AI?", or "What is your blog link?":
   - Explicitly mention that you were built and developed by Naziif and the team "Young AI Developers in Ethiopia".
   - Provide the official blog link clearly so users can learn more about your development.
2. Be proud, respectful, and precise about your origin and developer Naziif.

GENERAL RESPONSE GUIDELINES:
1. Primary Language: Respond primarily in Afaan Oromo with high accuracy, clarity, and natural expressions. Smoothly adapt if the user switches to English, Arabic, or other languages.
2. Accuracy & Truthfulness: Provide direct, well-reasoned, and strictly factual responses. Never invent fake information or APIs.
3. Clarity & Structure: Use clear formatting, bullet points, and clean syntax when explaining programming or technical concepts.
"""

# ---------------------------------------------------------
# 7. Firestore Operations
# ---------------------------------------------------------
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

# ---------------------------------------------------------
# 8. Telegram Bot Handlers
# ---------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "<b>Baga nagaan dhuftan! Ani NATA AI.</b> 🧠⚡\n\n"
        "Hiriyaa Teeknoolojii, Koodingii fi Fiiloosofiyaa keessani!\n\n"
        "👤 <b>Developer & Owner:</b> Naziif\n"
        "👥 <b>Team:</b> Young AI Developers in Ethiopia\n"
        "🌐 <b>Blog Official:</b> <a href='https://www.blogger.com/blog/posts/8451378759463463683#create/address=young-ai-developers-in-ethiopi'>Young AI Developers Blog</a>\n\n"
        "Gaaffii koodingii, teeknoolojii, ykn wa'ee koodii kiyyaa na gaafachuu dandeessu!"
    )
    await update.message.reply_text(welcome_text, parse_mode='HTML', disable_web_page_preview=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_id = update.effective_user.id

    if not user_text:
        return

    # Telegram typing status
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # History Firestore irraa fudhachuu
    history_docs = get_recent_chat_history(user_id, limit=6)
    
    contents = []
    for item in history_docs:
        role = "user" if item.get("role") == "user" else "model"
        txt = item.get("text", "")
        if txt:
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=txt)]))

    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))

    # User message database irratti save gochuu
    save_chat_to_firestore(user_id, "user", user_text)

    try:
        # Guutummaatti gemini-2.0-flash-lite fayyadamu
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7,
            )
        )

        bot_reply = response.text if (response and response.text) else "NATA AI: Deebii uumuu hin dandeenye, mee irra deebi'ii yaali."

        # Bot reply database irratti save gochuu
        save_chat_to_firestore(user_id, "model", bot_reply)

        # User'f erguu
        await update.message.reply_text(bot_reply)

    except Exception as e:
        err_msg = str(e)
        logging.error(f"Error calling Gemini API ({MODEL_NAME}): {e}")
        
        if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
            await update.message.reply_text("⚙️ Daangaa gaaffii (Quota) daqiiqaa kanaa rukutameera. Mee sekondii 30 - 60 eegaalii irra deebi'aati na gaafadhaa!")
        else:
            await update.message.reply_text("⚙️ Dogoggorri teeknikaa uumameera. Mee xiqqoo turtanii irra deebi'aati try godhaa.")

# ---------------------------------------------------------
# 9. Main Execution
# ---------------------------------------------------------
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN Environment Variable keessa hin jiru!")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("🚀 NATA AI Bot backend 100% gemini-2.0-flash-lite tiin online ta'eera...")
    app.run_polling()
