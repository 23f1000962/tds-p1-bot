import json
import os
import base64
import requests
from datetime import datetime
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AIPIPE_TOKEN = os.environ.get("AIPIPE_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") #One can find the token using -> Github setting -> Developer -> fine-grain -> select particular repo -> access of "content" (read & write)
GITHUB_OWNER = os.environ.get("GITHUB_OWNER")
GITHUB_REPO = os.environ.get("GITHUB_REPO")

LOG_URL = "https://raw.githubusercontent.com/23f1000962/tds-p1-bot/refs/heads/main/run.jsonl"
LOG_FILE = "run.jsonl"

# Fail fast if critical tokens are missing
if not TELEGRAM_BOT_TOKEN or not AIPIPE_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or AIPIPE_TOKEN in environment variables")

client = OpenAI(base_url="https://aipipe.org/openai/v1", api_key=AIPIPE_TOKEN)

conversation_history = {}

def log_query(question, answer):
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "question": question,
        "answer": answer
    }

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print("File write failed:", e)

    try:
        upload_run_jsonl()
    except Exception as e:
        print("Upload failed:", e)

def upload_run_jsonl():
    if not GITHUB_TOKEN or not GITHUB_OWNER or not GITHUB_REPO:
        print("GitHub credentials missing, skipping upload")
        return

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/run.jsonl"

    try:
        with open(LOG_FILE, "rb") as f:
            content = f.read()
    except FileNotFoundError:
        print("No run.jsonl file found to upload")
        return

    encoded_content = base64.b64encode(content).decode()

    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None

    body = {
        "message": "Update run.jsonl",
        "content": encoded_content,
        "branch": "main"
    }
    if sha:
        body["sha"] = sha

    r = requests.put(url, headers=headers, json=body)
    if r.status_code not in (200, 201):
        print("GitHub upload failed:", r.text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        user_text = update.message.text

        history = conversation_history.setdefault(chat_id, [])
        history.append({"role": "user", "content": user_text})
    except Exception as e:
        print("Error in message handling:", e)
        await update.message.reply_text(json.dumps({"error": str(e), "log_url": LOG_URL}))
        return

    system_prompt = (
        "You are a careful data analyst. The user's LAST message asks a data-analysis "
        "question and tells you exactly what JSON shape to reply with. Work out the "
        "real answer (use any public data you know, e.g. MOSPI statistics, general "
        "world knowledge, or arithmetic on numbers given in the message). "
        "Reply with ONLY that exact JSON object and absolutely nothing else — no "
        "explanation, no markdown, no code fences, just the raw JSON."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[{"role": "system", "content": system_prompt}] + history[-6:],
        )
        reply_text = response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply_text})

        try:
            parsed = json.loads(reply_text)
        except json.JSONDecodeError:
            start, end = reply_text.find("{"), reply_text.rfind("}")
            parsed = json.loads(reply_text[start:end + 1])

        parsed["log_url"] = LOG_URL
        final_reply = json.dumps(parsed)

        log_query(user_text, final_reply)
        await update.message.reply_text(final_reply)

    except Exception as e:
        print("AI response error:", e)
        await update.message.reply_text(json.dumps({"error": str(e), "log_url": LOG_URL}))

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot is running... (Ctrl+C to stop)")
    app.run_polling()

if __name__ == "__main__":
    main()
