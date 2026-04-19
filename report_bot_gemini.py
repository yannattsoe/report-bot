"""
Daily Report Telegram Bot (Gemini Free Version - Railway Ready)
"""

import logging
import asyncio
import os
from datetime import datetime, time
from collections import defaultdict

import google.generativeai as genai
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

# ==================== CONFIG (Environment Variables) ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OWNER_TELEGRAM_ID = int(os.environ.get("OWNER_TELEGRAM_ID"))

SUMMARY_HOUR = 18
SUMMARY_MINUTE = 0

# ==================== SETUP ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-2.5-flash")

daily_reports: dict[str, list] = defaultdict(list)


# ==================== HANDLERS ====================

async def collect_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    if msg.chat.type == "private":
        return

    today = datetime.now().strftime("%Y-%m-%d")
    user_name = msg.from_user.full_name or msg.from_user.username or "Unknown"
    report_time = datetime.now().strftime("%H:%M")

    daily_reports[today].append({
        "user": user_name,
        "text": msg.text,
        "time": report_time
    })
    logger.info(f"Report collected from {user_name} at {report_time}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%Y-%m-%d")
    count = len(daily_reports.get(today, []))
    await update.message.reply_text(
        f"📊 ဒီနေ့ ({today}) report {count} ခု ရောက်ပြီ\n"
        f"⏰ Summary ပို့မယ့်အချိန်: {SUMMARY_HOUR:02d}:{SUMMARY_MINUTE:02d}"
    )


async def cmd_summarize_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        await update.message.reply_text("❌ Permission မရှိပါ")
        return
    await update.message.reply_text("⏳ Summary လုပ်နေပြီ...")
    await send_daily_summary(context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Report Bot Commands:\n\n"
        "/status - ဒီနေ့ report count ကြည့်မယ်\n"
        "/summarize - ချက်ချင်း summary လုပ်မယ် (owner only)\n"
        "/help - help ကြည့်မယ်"
    )


# ==================== GEMINI SUMMARY ====================

async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%Y-%m-%d")
    reports = daily_reports.get(today, [])

    if not reports:
        await context.bot.send_message(
            chat_id=OWNER_TELEGRAM_ID,
            text=f"📭 {today} - ဒီနေ့ report မရောက်သေးပါ"
        )
        return

    report_text = f"Date: {today}\nTotal reports: {len(reports)}\n\n"
    for i, r in enumerate(reports, 1):
        report_text += f"[{i}] {r['user']} ({r['time']}):\n{r['text']}\n\n"

    prompt = f"""အောက်က report တွေကို ဖတ်ပြီး boss အတွက် full breakdown summary ရေးပေးပါ။
Myanmar/Burmese language နဲ့ ရေးပေးပါ။

Format အောက်ပါအတိုင်း ရေးပေးပါ:

📅 DATE - summary ခေါင်းစဉ်

👥 TEAM OVERVIEW
- လူဘယ်နှစ်ယောက် report တင်သလဲ
- overall performance

📋 INDIVIDUAL BREAKDOWN
တစ်ယောက်စီ အသေးစိတ်

✅ ACHIEVEMENTS TODAY
- ပြီးသွားတဲ့ task တွေ

⚠️ ISSUES / PENDING
- ပြဿနာ ဒါမှမဟုတ် မပြီးသေးတာ

💡 RECOMMENDATIONS
- boss အနေနဲ့ ဘာ action လုပ်သင့်လဲ

---
REPORTS:
{report_text}"""

    try:
        response = gemini_model.generate_content(prompt)
        summary = response.text

        max_len = 4000
        if len(summary) <= max_len:
            await context.bot.send_message(
                chat_id=OWNER_TELEGRAM_ID,
                text=f"📊 Daily Report Summary\n\n{summary}"
            )
        else:
            parts = [summary[i:i+max_len] for i in range(0, len(summary), max_len)]
            for idx, part in enumerate(parts, 1):
                header = f"📊 Daily Report Summary (Part {idx}/{len(parts)})\n\n" if idx == 1 else ""
                await context.bot.send_message(
                    chat_id=OWNER_TELEGRAM_ID,
                    text=f"{header}{part}"
                )
                await asyncio.sleep(0.5)

        logger.info(f"Summary sent to owner for {today}")

    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        await context.bot.send_message(
            chat_id=OWNER_TELEGRAM_ID,
            text=f"❌ Summary error: {str(e)}\n\nRaw reports:\n{report_text[:3000]}"
        )


# ==================== SCHEDULER ====================

async def scheduled_summary(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running scheduled daily summary...")
    await send_daily_summary(context)


# ==================== MAIN ====================

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("summarize", cmd_summarize_now))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_report))

    job_time = time(hour=SUMMARY_HOUR, minute=SUMMARY_MINUTE)
    app.job_queue.run_daily(scheduled_summary, time=job_time)

    logger.info(f"Bot started. Summary scheduled at {SUMMARY_HOUR:02d}:{SUMMARY_MINUTE:02d} daily")
    app.run_polling()


if __name__ == "__main__":
    main()
