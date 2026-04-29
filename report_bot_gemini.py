"""
Daily Report Bot - Full Version
- Multi-group support (Production, Front Office, Designer)
- Job analytics with Gemini AI
- Daily summary: 10:00 PM Myanmar time
- Weekly summary: Saturday 1:00 PM Myanmar time
- Google Sheets data storage
"""

import logging
import asyncio
import os
import json
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo
from collections import defaultdict

from google import genai
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

# ==================== CONFIG ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OWNER_TELEGRAM_ID = int(os.environ.get("OWNER_TELEGRAM_ID"))
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# Group IDs
PRODUCTION_GROUP_ID = int(os.environ.get("PRODUCTION_GROUP_ID", "0"))
FRONT_OFFICE_GROUP_ID = int(os.environ.get("FRONT_OFFICE_GROUP_ID", "0"))
DESIGNER_GROUP_ID = int(os.environ.get("DESIGNER_GROUP_ID", "0"))
MANAGER_IDS = {
    8649672085: {"name": "Thar Thar", "group": "front_office"},
    6699538735: {"name": "Gatone", "group": "production"},
}
manager_reports = {}

MYANMAR_TZ = ZoneInfo("Asia/Yangon")

# Daily summary: 10:00 PM Myanmar = 15:30 UTC
DAILY_HOUR_UTC = 15
DAILY_MINUTE_UTC = 30

# Weekly summary: Saturday 1:00 PM Myanmar = Saturday 06:30 UTC
WEEKLY_HOUR_UTC = 6
WEEKLY_MINUTE_UTC = 30

# ==================== SETUP ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

client = genai.Client(api_key=GEMINI_API_KEY)


# In-memory report storage
daily_reports = defaultdict(lambda: defaultdict(list))
# daily_reports[date][group_type] = [{"user": ..., "text": ..., "time": ...}]


# ==================== GOOGLE SHEETS ====================

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)


def save_analytics(date, group_type, operator, jobs_completed, jobs_pending, errors, machine_issues, job_types):
    try:
        sheet = get_sheet()
        sheet_name = {
            "production": "Production_Analytics",
            "front_office": "FrontOffice_Analytics",
            "designer": "Design_Analytics"
        }.get(group_type, "Production_Analytics")

        ws = sheet.worksheet(sheet_name)
        if group_type == "production":
            ws.append_row([
                date, operator,
                json.dumps(jobs_completed, ensure_ascii=False),
                json.dumps(jobs_pending, ensure_ascii=False),
                json.dumps(errors, ensure_ascii=False),
                machine_issues,
                json.dumps(job_types, ensure_ascii=False),
                datetime.now().strftime("%Y-%m-%d %H:%M")
            ])
        elif group_type == "front_office":
            ws.append_row([
                date, operator,
                json.dumps(jobs_completed, ensure_ascii=False),
                json.dumps(jobs_pending, ensure_ascii=False),
                json.dumps(errors, ensure_ascii=False),
                machine_issues,
                datetime.now().strftime("%Y-%m-%d %H:%M")
            ])
        else:
            ws.append_row([
                date, operator,
                json.dumps(jobs_completed, ensure_ascii=False),
                json.dumps(jobs_pending, ensure_ascii=False),
                json.dumps(errors, ensure_ascii=False),
                machine_issues,
                datetime.now().strftime("%Y-%m-%d %H:%M")
            ])
    except Exception as e:
        logger.error(f"Save analytics error: {e}")


def get_weekly_analytics(group_type):
    try:
        sheet = get_sheet()
        sheet_name = {
            "production": "Production_Analytics",
            "front_office": "FrontOffice_Analytics",
            "designer": "Design_Analytics"
        }.get(group_type, "Production_Analytics")

        ws = sheet.worksheet(sheet_name)
        records = ws.get_all_records()

        # Last 7 days
        from datetime import timedelta
        week_ago = (datetime.now(MYANMAR_TZ) - timedelta(days=7)).strftime("%Y-%m-%d")
        weekly = [r for r in records if str(r.get("Date", "")) >= week_ago]
        return weekly
    except Exception as e:
        logger.error(f"Get weekly analytics error: {e}")
        return []


# ==================== GEMINI FUNCTIONS ====================

def extract_analytics_from_report(report_text, group_type):
    """Gemini ကို သုံးပြီး report ထဲက structured data ထုတ်မယ်"""
    try:
        if group_type == "production":
            prompt = f"""အောက်က production report ကို ဖတ်ပြီး JSON format နဲ့ ထုတ်ပေးပါ။
JSON ပဲ ထုတ်ပေးပါ၊ တခြားစကား မထည့်နဲ့။

{{
  "operator": "နာမည်",
  "jobs_completed": ["job1", "job2"],
  "jobs_pending": ["job1"],
  "errors": ["error1"],
  "machine_issues": "မရှိပါ",
  "job_types": ["DTF", "Sticker"]
}}

Report:
{report_text}"""

        elif group_type == "front_office":
            prompt = f"""အောက်က front office report ကို ဖတ်ပြီး JSON format နဲ့ ထုတ်ပေးပါ။
JSON ပဲ ထုတ်ပေးပါ၊ တခြားစကား မထည့်နဲ့။

{{
  "operator": "name of the person who wrote this report",
  "orders_received": ["extract each order: customer name, job type, size, quantity"],
  "payments_collected": ["extract each payment: customer name and amount"],
  "pending_followup": ["customers that need follow up tomorrow"],
  "issues": "any problems mentioned, or မရှိပါ if none"
}}

Important: Extract ALL items found in the report. Do not return empty arrays if data exists.

Report:
{report_text}"""

        else:  # designer
            prompt = f"""အောက်က designer report ကို ဖတ်ပြီး JSON format နဲ့ ထုတ်ပေးပါ။
JSON ပဲ ထုတ်ပေးပါ၊ တခြားစကား မထည့်နဲ့။

{{
  "operator": "နာမည်",
  "designs_completed": ["design1"],
  "revisions": ["design - reason"],
  "designs_pending": ["design1"],
  "priority_tomorrow": ["design1"]
}}

Report:
{report_text}"""

        response = client.models.generate_content(model="gemini-3-flash-preview", contents=prompt)
        text = response.text.strip()
        # JSON ထုတ်မယ်
        text = re.sub(r'```json|```', '', text).strip()
        return json.loads(text)
    except Exception as e:
        logger.error(f"Extract analytics error: {e}")
        return {}


def generate_daily_summary(reports_by_group, date):
    """Daily summary ရေးမယ်"""
    try:
        report_text = f"Date: {date}\n\n"
        for group, reports in reports_by_group.items():
            report_text += f"=== {group.upper()} ===\n"
            for r in reports:
                report_text += f"{r['user']} ({r['time']}):\n{r['text']}\n\n"

        prompt = f"""အောက်က reports တွေကို ဖတ်ပြီး boss အတွက် daily summary ရေးပေးပါ။
မြန်မာဘာသာနဲ့ ရေးပေးပါ။

📅 DAILY SUMMARY ({date})

🏭 PRODUCTION
- ပြီးစီးသော jobs
- ကျန်ရှိသော jobs  
- Error / ပျက်စီးမှု
- စက်ပြဿနာ

🖥️ FRONT OFFICE
- လက်ခံသော orders
- ငွေရှင်းမှု
- Follow up လိုတဲ့ customer

🎨 DESIGN
- ပြီးသော design
- Revision
- Pending

⚠️ ISSUES တွေ highlight

💡 BOSS ACTION ITEMS
- ဘာ action လုပ်သင့်လဲ

---
{report_text}"""

        response = client.models.generate_content(model="gemini-3-flash-preview", contents=prompt)
        return response.text
    except Exception as e:
        logger.error(f"Daily summary error: {e}")
        return f"Summary error: {e}"


def generate_weekly_summary(prod_data, fo_data, design_data):
    """Weekly summary ရေးမယ်"""
    try:
        prompt = f"""အောက်က တစ်ပတ်စာ data တွေကို ဖတ်ပြီး boss အတွက် weekly summary ရေးပေးပါ။
မြန်မာဘာသာနဲ့ ရေးပေးပါ။

📊 WEEKLY PERFORMANCE REPORT

🏭 PRODUCTION TEAM
တစ်ယောက်စီ performance အသေးစိတ် (jobs count, error rate, completion rate)
Top performer ဘယ်သူလဲ၊ ဘာကြောင့်
အားနည်းတဲ့သူ ဘယ်သူလဲ၊ ဘာကြောင့်
Error အများဆုံး job type
စက်ပြဿနာ တစ်ပတ်စာ

🖥️ FRONT OFFICE TEAM
တစ်ယောက်စီ performance
Order volume trend
Pending follow ups

🎨 DESIGN TEAM
တစ်ယောက်စီ performance
Revision rate
Pending designs

📈 BUSINESS INSIGHTS
Production volume trend (တိုးလာ/ကျသွားနေလား)
Quality trend
အကြံပြုချက်တွေ

💡 BOSS RECOMMENDATIONS
- ဘယ်သူကို သတိပေးသင့်တယ်
- ဘယ် process ပြင်သင့်တယ်
- လာမယ့်ပတ် ဦးစားပေးရမယ့်အရာ
- Staff training လိုအပ်မလား

---
PRODUCTION DATA:
{json.dumps(prod_data, ensure_ascii=False, indent=2)}

FRONT OFFICE DATA:
{json.dumps(fo_data, ensure_ascii=False, indent=2)}

DESIGN DATA:
{json.dumps(design_data, ensure_ascii=False, indent=2)}"""

        response = client.models.generate_content(model="gemini-3-flash-preview", contents=prompt)
        return response.text
    except Exception as e:
        logger.error(f"Weekly summary error: {e}")
        return f"Weekly summary error: {e}"


# ==================== HANDLERS ====================

def get_group_type(chat_id):
    if chat_id == PRODUCTION_GROUP_ID:
        return "production"
    elif chat_id == FRONT_OFFICE_GROUP_ID:
        return "front_office"
    elif chat_id == DESIGNER_GROUP_ID:
        return "designer"
    return None


async def collect_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    if msg.chat.type == "private":
        return

    chat_id = msg.chat_id

    # Manager private message စစ်မယ်
    if msg.chat.type == "private":
        user_id = msg.from_user.id
        if user_id in MANAGER_IDS:
            today = datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d")
            if today not in manager_reports:
                manager_reports[today] = {}
            manager_reports[today][user_id] = {
                "name": MANAGER_IDS[user_id]["name"],
                "group": MANAGER_IDS[user_id]["group"],
                "text": msg.text,
                "time": datetime.now(MYANMAR_TZ).strftime("%H:%M")
            }
            await msg.reply_text("✅ Manager report သိမ်းပြီးပါပြီ။")
            logger.info(f"Manager report from {MANAGER_IDS[user_id]['name']}")
        return

    group_type = get_group_type(chat_id)

    if not group_type:
        return  # Unknown group — ignore

    today = datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d")
    user_name = msg.from_user.full_name or msg.from_user.username or "Unknown"
    report_time = datetime.now(MYANMAR_TZ).strftime("%H:%M")

    daily_reports[today][group_type].append({
        "user": user_name,
        "text": msg.text,
        "time": report_time
    })

    # Analytics ကို summary အချိန်မှာပဲ လုပ်မယ် (quota သက်သာဖို့)

    logger.info(f"Report collected from {user_name} ({group_type}) at {report_time}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d")
    total = sum(len(r) for r in daily_reports[today].values())
    prod = len(daily_reports[today].get("production", []))
    fo = len(daily_reports[today].get("front_office", []))
    design = len(daily_reports[today].get("designer", []))

    await update.message.reply_text(
        f"📊 ဒီနေ့ ({today}) Report အခြေအနေ\n\n"
        f"🏭 Production: {prod} ခု\n"
        f"🖥️ Front Office: {fo} ခု\n"
        f"🎨 Design: {design} ခု\n"
        f"📝 စုစုပေါင်း: {total} ခု\n\n"
        f"⏰ Daily summary: ည ၁၀:၀၀\n"
        f"📅 Weekly summary: စနေ နေ့လည် ၁:၀၀"
    )



async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        await update.message.reply_text("❌ Permission မရှိပါ")
        return

    await update.message.reply_text("⏳ Monthly report လုပ်နေပြီ...")

    now = datetime.now(MYANMAR_TZ)
    year = now.year
    month = now.month

    try:
        creds = Credentials.from_service_account_info(
            json.loads(GOOGLE_CREDENTIALS_JSON),
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID)

        all_data = {}
        for group, tab in [("production", "Production_Analytics"), ("front_office", "FrontOffice_Analytics"), ("designer", "Design_Analytics")]:
            try:
                ws = sheet.worksheet(tab)
                records = ws.get_all_records()
                monthly = [r for r in records if str(r.get("Date", "")).startswith(f"{year}-{month:02d}")]
                all_data[group] = monthly
            except Exception as e:
                all_data[group] = []

        prompt = f"""အောက်က {year} ခုနှစ် {month} လ data တွေကို ကြည့်ပြီး monthly performance report ရေးပေးပါ။ Myanmar language နဲ့ ရေးပါ။

Production Data: {json.dumps(all_data.get('production', []), ensure_ascii=False)}
Front Office Data: {json.dumps(all_data.get('front_office', []), ensure_ascii=False)}
Designer Data: {json.dumps(all_data.get('designer', []), ensure_ascii=False)}

Format:
📅 {year} ခုနှစ် {month} လ Monthly Report

🏭 Production
- Total jobs completed
- Error rate
- Top performer
- အကြံပြုချက်

🖥️ Front Office
- Total orders
- Total collection
- Issues summary

🎨 Design
- Total designs completed
- Revision rate
- အကြံပြုချက်

💡 Overall Summary & Recommendations"""

        response = client.models.generate_content(model="gemini-3-flash-preview", contents=prompt)
        summary = response.text

        max_len = 4000
        if len(summary) <= max_len:
            await update.message.reply_text("📊 Monthly Report

" + summary)
        else:
            parts = [summary[i:i+max_len] for i in range(0, len(summary), max_len)]
            for idx, part in enumerate(parts, 1):
                await update.message.reply_text(f"📊 Monthly Report (Part {idx}/{len(parts)})

" + part)
                await asyncio.sleep(0.5)

    except Exception as e:
        await update.message.reply_text(f"❌ Monthly report error: {str(e)}")

async def cmd_summarize_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        await update.message.reply_text("❌ Permission မရှိပါ")
        return
    await update.message.reply_text("⏳ Summary လုပ်နေပြီ...")
    await send_daily_summary(context)


async def cmd_weekly_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        await update.message.reply_text("❌ Permission မရှိပါ")
        return
    await update.message.reply_text("⏳ Weekly summary လုပ်နေပြီ...")
    await send_weekly_summary(context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Report Bot Commands:\n\n"
        "/status - ဒီနေ့ report count\n"
        "/summarize - ချက်ချင်း daily summary (owner only)\n"
        "/weekly - ချက်ချင်း weekly summary (owner only)\n"
        "/help - help"
    )


# ==================== SCHEDULED SUMMARIES ====================

async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d")
    reports_by_group = daily_reports.get(today, {})

    if not any(reports_by_group.values()):
        await context.bot.send_message(
            chat_id=OWNER_TELEGRAM_ID,
            text=f"📭 {today} - ဒီနေ့ report မရောက်သေးပါ"
        )
        return

    # Group တစ်ခုချင်း report အကုန် တစ်ခါတည်း Gemini ကို ပို့မယ်
    for group_type, reports in reports_by_group.items():
        if not reports:
            continue
        try:
            all_reports_text = "\n\n---\n\n".join([f"{r['user']} ({r['time']}):\n{r['text']}" for r in reports])
            analytics = extract_analytics_from_report(all_reports_text, group_type)
            if analytics:
                operator = analytics.get("operator", group_type)
                if group_type == "production":
                    save_analytics(today, group_type, operator,
                        analytics.get("jobs_completed", []),
                        analytics.get("jobs_pending", []),
                        analytics.get("errors", []),
                        analytics.get("machine_issues", ""),
                        analytics.get("job_types", []))
                elif group_type == "front_office":
                    save_analytics(today, group_type, operator,
                        analytics.get("orders_received", []),
                        analytics.get("payments_collected", []),
                        analytics.get("pending_followup", []),
                        analytics.get("issues", ""),
                        [])
                else:
                    save_analytics(today, group_type, operator,
                        analytics.get("designs_completed", []),
                        analytics.get("designs_pending", []),
                        analytics.get("revisions", []),
                        "",
                        analytics.get("priority_tomorrow", []))
        except Exception as e:
            logger.error(f"Analytics error for {group_type}: {e}")

    # Manager report နဲ့ တိုက်စစ်မယ်
    manager_note = ""
    if today in manager_reports:
        for uid, mgr in manager_reports[today].items():
            manager_note += f"\n\n👔 Manager Note ({mgr['name']} - {mgr['group']}):\n{mgr['text']}"

    summary = generate_daily_summary(reports_by_group, today)
    if manager_note:
        summary += "\n\n" + "="*30 + "\n" + manager_note

    max_len = 4000
    if len(summary) <= max_len:
        await context.bot.send_message(
            chat_id=OWNER_TELEGRAM_ID,
            text=f"📊 Daily Report Summary\n\n{summary}"
        )
    else:
        parts = [summary[i:i+max_len] for i in range(0, len(summary), max_len)]
        for idx, part in enumerate(parts, 1):
            header = f"📊 Daily Summary (Part {idx}/{len(parts)})\n\n" if idx == 1 else ""
            await context.bot.send_message(
                chat_id=OWNER_TELEGRAM_ID,
                text=f"{header}{part}"
            )
            await asyncio.sleep(0.5)

    logger.info(f"Daily summary sent for {today}")


async def send_weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    prod_data = get_weekly_analytics("production")
    fo_data = get_weekly_analytics("front_office")
    design_data = get_weekly_analytics("designer")

    summary = generate_weekly_summary(prod_data, fo_data, design_data)

    max_len = 4000
    if len(summary) <= max_len:
        await context.bot.send_message(
            chat_id=OWNER_TELEGRAM_ID,
            text=f"📊 Weekly Performance Report\n\n{summary}"
        )
    else:
        parts = [summary[i:i+max_len] for i in range(0, len(summary), max_len)]
        for idx, part in enumerate(parts, 1):
            header = f"📊 Weekly Report (Part {idx}/{len(parts)})\n\n" if idx == 1 else ""
            await context.bot.send_message(
                chat_id=OWNER_TELEGRAM_ID,
                text=f"{header}{part}"
            )
            await asyncio.sleep(0.5)

    logger.info("Weekly summary sent")


# ==================== MAIN ====================

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("summarize", cmd_summarize_now))
    app.add_handler(CommandHandler("monthly", cmd_monthly))
    app.add_handler(CommandHandler("weekly", cmd_weekly_now))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_report))

    # Daily: 10:00 PM Myanmar = 15:30 UTC
    daily_time = time(hour=DAILY_HOUR_UTC, minute=DAILY_MINUTE_UTC)
    app.job_queue.run_daily(send_daily_summary, time=daily_time)

    # Weekly: Saturday 1:00 PM Myanmar = Saturday 06:30 UTC
    weekly_time = time(hour=WEEKLY_HOUR_UTC, minute=WEEKLY_MINUTE_UTC)
    app.job_queue.run_daily(
        send_weekly_summary,
        time=weekly_time,
        days=(5,)  # Saturday
    )

    logger.info("Report Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
