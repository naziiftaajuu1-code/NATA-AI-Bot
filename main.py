import os
import json
import logging
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

# Firebase Admin SDK Libraries
import firebase_admin
from firebase_admin import credentials, firestore

# Console Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 1. Environment Variables / Secrets Dubbisuu
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIREBASE_CRED_STR = os.environ.get("FIREBASE_CREDENTIALS")

# 2. Firebase / Firestore Initialize Gochuu
db = None
if FIREBASE_CRED_STR:
    try:
        cred_dict = json.loads(FIREBASE_CRED_STR)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logging.info("✅ Firebase/Firestore nagaadhaan wal-hiddameera!")
    except Exception as e:
        logging.error(f"❌ Dogoggora Firebase initialize gochuu irra jiru: {e}")
else:
    logging.warning("⚠️ FIREBASE_CREDENTIALS secret keessatti hin kaawwamne. Storage malee hojjeta.")

# 3. Gemini Client (SDK Ammayyaa) Initialize Gochuu
if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY Environment Variable keessa hin jiru!")

client = genai.Client(api_key=GEMINI_API_KEY)

# 4. System Instruction (NATA AI Persona & System Metadata Guutuu)
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

def select_gemini_model(user_query: str) -> str:
    """
    Quota API bilisaa akka hin dhumneef model sirrii dynamikiidhaan filata:
    - gemini-2.0-flash-lite: Gaaffiiwwan gabaaboo fi salphaa ta'aniif (Fast & Token Saver).
    - gemini-2.0-flash: Koodingii, debug, fiilloosofii fi gaaffiiwwan gadi fageenya qabaniif.
    """
    query = user_query.lower()
    keywords = [
        "koodii", "code", "debug", "error", "explain", "ibsi", "build", 
        "ijaar", "philosophy", "fiiloosofii", "python", "script", "algorithm"
    ]
    
    if len(user_query) > 100 or any(kw in query for kw in keywords):
        logging.info("Selected Model: gemini-2.0-flash (Deep Reasoning)")
        return "gemini-2.0-flash"
    else:
        logging.info("Selected Model: gemini-2.0-flash-lite (Fast & Quota Efficient)")
        return "gemini-2.0-flash-lite"

def save_chat_to_firestore(user_id: int, role: str, text: str):
    """Ergaa user fi bot Firestore keessatti kuffisa."""
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
    """Haasaa dhiyoo godhame Firestore irraa dubbisa."""
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
    """Command /start yeroo tuqamu deebii kennamu."""
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
    """Ergaa user dubbisee Gemini AI'f erga."""
    user_text = update.message.text
    user_id = update.effective_user.id

    if not user_text:
        return

    # Telegram status 'typing...'
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # 1. Chat history Firestore irraa fudhachuu
    history_docs = get_recent_chat_history(user_id, limit=6)
    
    # 2. Context Gemini API'f qopheessuu
    contents = []
    for item in history_docs:
        role = "user" if item.get("role") == "user" else "model"
        txt = item.get("text", "")
        if txt:
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=txt)]))

    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))

    # User message kuffisuu
    save_chat_to_firestore(user_id, "user", user_text)

    # 3. Model dynamic ta'e filachuu
    chosen_model = select_gemini_model(user_text)

    try:
        response = client.models.generate_content(
            model=chosen_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7,
            )
        )

        bot_reply = response.text if response.text else "NATA AI: Deebii uumuu hin dandeenye, mee irra deebiadhu."

        # Bot response kuffisuu
        save_chat_to_firestore(user_id, "model", bot_reply)

        # User'f erguu
        await update.message.reply_text(bot_reply)

    except Exception as e:
        logging.error(f"Error calling Gemini API: {e}")
        await update.message.reply_text("⚙️ Dogoggorri teeknikaa uumameera. Mee xiqqoo turtanii irra deebi'aatii try godhaa.")

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN Environment Variable keessa hin jiru!")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("🚀 NATA AI Bot backend nagaadhaan ka'eera...")
    app.run_polling()
