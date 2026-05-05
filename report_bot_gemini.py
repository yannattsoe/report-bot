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
from datetime import datetime, time, timedelta
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
SECONDARY_OWNER_ID = int(os.environ.get("SECONDARY_OWNER_ID", "0"))
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
LEAVE_SPREADSHEET_ID = os.environ.get("LEAVE_SPREADSHEET_ID", "")

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

# Raw_Reports header check cache — တစ်ခါပဲ စစ်ဖို့
_raw_reports_header_checked = False


# ==================== GOOGLE SHEETS ====================

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gspread_client = gspread.authorize(creds)  # 'client' မသုံးဘူး — global Gemini client overwrite မဖြစ်အောင်
    return gspread_client.open_by_key(SPREADSHEET_ID)


def get_leave_sheet():
    """Leave bot ရဲ့ Employees sheet ကနေ ဖတ်မယ်"""
    if not LEAVE_SPREADSHEET_ID:
        raise ValueError("LEAVE_SPREADSHEET_ID not configured")
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gspread_client = gspread.authorize(creds)
    return gspread_client.open_by_key(LEAVE_SPREADSHEET_ID)


def get_employees_by_group():
    """Leave bot Employees sheet ကနေ group တစ်ခုချင်း ဝန်ထမ်းစာရင်း ဖတ်မယ်"""
    try:
        if not LEAVE_SPREADSHEET_ID:
            return {}
        sheet = get_leave_sheet()
        ws = sheet.worksheet("Employees")
        records = ws.get_all_records()
        result = {}
        for r in records:
            group = str(r.get("Group", "")).strip().lower()
            if not group:
                continue
            # comma ခွဲထားတဲ့ multi-group handle မယ်
            groups = [g.strip() for g in group.split(",")]
            for g in groups:
                if g not in result:
                    result[g] = []
                result[g].append({
                    "name": r.get("Name", ""),
                    "telegram_id": str(r.get("Telegram_ID", "")).strip(),
                    "username": str(r.get("Telegram_Username", "")).strip().lower().lstrip("@")
                })
        return result
    except Exception as e:
        logger.error(f"Get employees error: {e}")
        return {}


def save_raw_report(date, group_type, user_name, report_text, report_time, user_id="", username=""):
    """Report တင်တိုင်း raw text Sheet မှာ သိမ်းမယ် (restart ဖြစ်ရင် data မပျောက်အောင်)"""
    global _raw_reports_header_checked
    try:
        sheet = get_sheet()
        try:
            ws = sheet.worksheet("Raw_Reports")
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet("Raw_Reports", rows=1000, cols=8)
            ws.append_row(["Date", "Group", "User", "Time", "Text", "Timestamp", "UserID", "Username"])
            _raw_reports_header_checked = True
        # Header တစ်ကြိမ်ပဲ စစ်မယ် (API call သက်သာဖို့)
        if not _raw_reports_header_checked:
            headers = ws.row_values(1)
            if "UserID" not in headers:
                ws.update_cell(1, len(headers) + 1, "UserID")
                headers.append("UserID")
            if "Username" not in headers:
                ws.update_cell(1, len(headers) + 1, "Username")
            _raw_reports_header_checked = True
        ws.append_row([
            date, group_type, user_name, report_time, report_text,
            datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d %H:%M"),
            str(user_id),
            username.lower().lstrip("@") if username else ""
        ])
    except Exception as e:
        logger.error(f"Save raw report error: {e}")


def get_todays_raw_reports(date):
    """Summary အချိန်မှာ Sheet ကနေ ဒီနေ့ reports ဖတ်မယ် (bot restart ဖြစ်ခဲ့ရင်)"""
    try:
        sheet = get_sheet()
        try:
            ws = sheet.worksheet("Raw_Reports")
        except gspread.exceptions.WorksheetNotFound:
            return {}  # sheet မရှိသေးရင် empty ပြန်မယ်
        records = ws.get_all_records()
        result = {}
        for r in records:
            if str(r.get("Date", "")) == date:
                gt = r.get("Group", "")
                if gt not in result:
                    result[gt] = []
                result[gt].append({
                    "user": r.get("User", ""),
                    "text": r.get("Text", ""),
                    "time": r.get("Time", "")
                })
        return result
    except Exception as e:
        logger.error(f"Get raw reports error: {e}")
        return {}


def save_analytics(date, group_type, operator, col3, col4, col5, col6, col7):
    """
    Production  → Jobs_Completed, Jobs_Pending, Errors, Machine_Issues, Job_Types
    FrontOffice → Orders_Received, Payments, Pending_Followup, Issues, (unused)
    Designer    → Designs_Completed, Designs_Pending, Revisions, (unused), Priority_Tomorrow
    """
    try:
        sheet = get_sheet()
        sheet_name = {
            "production": "Production_Analytics",
            "front_office": "FrontOffice_Analytics",
            "designer": "Design_Analytics"
        }.get(group_type, "Production_Analytics")

        ws = sheet.worksheet(sheet_name)
        ts = datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d %H:%M")

        if group_type == "production":
            # Columns: Date, Operator, Jobs_Completed, Jobs_Pending, Errors, Machine_Issues, Job_Types, Timestamp
            ws.append_row([
                date, operator,
                json.dumps(col3, ensure_ascii=False),
                json.dumps(col4, ensure_ascii=False),
                json.dumps(col5, ensure_ascii=False),
                col6,
                json.dumps(col7, ensure_ascii=False),
                ts
            ])
        elif group_type == "front_office":
            # Columns: Date, Operator, Orders_Received, Payments, Pending_Followup, Issues, Timestamp
            ws.append_row([
                date, operator,
                json.dumps(col3, ensure_ascii=False),
                json.dumps(col4, ensure_ascii=False),
                json.dumps(col5, ensure_ascii=False),
                col6,
                ts
            ])
        else:  # designer
            # Columns: Date, Operator, Designs_Completed, Revisions, Designs_Pending, Priority_Tomorrow, Timestamp
            ws.append_row([
                date, operator,
                json.dumps(col3, ensure_ascii=False),
                json.dumps(col4, ensure_ascii=False),
                json.dumps(col5, ensure_ascii=False),
                json.dumps(col7, ensure_ascii=False),
                ts
            ])
    except Exception as e:
        logger.error(f"Save analytics error ({group_type}): {e}", exc_info=True)


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
            prompt = f"""အောက်က production reports တွေကို ဖတ်ပြီး တစ်ခုတည်းသော JSON object အနေနဲ့ ထုတ်ပေးပါ။
JSON object တစ်ခုပဲ ထုတ်ပါ၊ array မဟုတ်ဘူး၊ တခြားစကား မထည့်နဲ့။
Report ပေါင်းများနေရင် jobs တွေ အကုန်ပေါင်းထည့်ပြီး operator field မှာ နာမည်တွေ comma နဲ့ ဖော်ပြပါ။

{{
  "operator": "နာမည်တွေ comma နဲ့",
  "jobs_completed": ["job1", "job2"],
  "jobs_pending": ["job1"],
  "errors": ["error1"],
  "machine_issues": "မရှိပါ",
  "job_types": ["DTF", "Sticker"]
}}

Report:
{report_text}"""

        elif group_type == "front_office":
            prompt = f"""အောက်က front office reports တွေကို ဖတ်ပြီး တစ်ခုတည်းသော JSON object အနေနဲ့ ထုတ်ပေးပါ။
JSON object တစ်ခုပဲ ထုတ်ပါ၊ array မဟုတ်ဘူး၊ တခြားစကား မထည့်နဲ့။
Report ပေါင်းများနေရင် items တွေ အကုန်ပေါင်းထည့်ပါ။

{{
  "operator": "နာမည်တွေ comma နဲ့",
  "orders_received": ["customer name, job type, size, quantity"],
  "payments_collected": ["customer name, amount"],
  "pending_followup": ["customer name"],
  "issues": "ပြဿနာများ သို့မဟုတ် မရှိပါ"
}}

Important: Extract ALL items. Do not return empty arrays if data exists.

Report:
{report_text}"""

        else:  # designer
            prompt = f"""အောက်က designer reports တွေကို ဖတ်ပြီး တစ်ခုတည်းသော JSON object အနေနဲ့ ထုတ်ပေးပါ။
JSON object တစ်ခုပဲ ထုတ်ပါ၊ array မဟုတ်ဘူး၊ တခြားစကား မထည့်နဲ့။
Report ပေါင်းများနေရင် designs တွေ အကုန်ပေါင်းထည့်ပါ။

{{
  "operator": "နာမည်တွေ comma နဲ့",
  "designs_completed": ["design1"],
  "revisions": ["design - reason"],
  "designs_pending": ["design1"],
  "priority_tomorrow": ["design1"]
}}

Report:
{report_text}"""

        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        text = response.text.strip()
        # JSON ထုတ်မယ်
        text = re.sub(r'```json|```', '', text).strip()
        parsed = json.loads(text)
        # Gemini က array ပြန်ပေးရင် (multiple operators) merge လုပ်မယ်
        if isinstance(parsed, list):
            merged = {}
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                for k, v in item.items():
                    if k == "operator":
                        merged[k] = merged.get(k, "") + ("," if merged.get(k) else "") + str(v)
                    elif isinstance(v, list):
                        merged.setdefault(k, [])
                        merged[k].extend(v)
                    else:
                        merged[k] = v
            return merged
        return parsed
    except Exception as e:
        logger.error(f"Extract analytics error: {e}")
        return {}


def generate_daily_summary(reports_by_group, date, manager_notes_text=""):
    """Daily summary ရေးမယ် — manager notes ပါရင် operator reports နဲ့ တိုက်စစ်မယ်"""
    try:
        report_text = f"Date: {date}\n\n"
        for group, reports in reports_by_group.items():
            if group.startswith("manager_"):
                continue
            report_text += f"=== {group.upper()} ===\n"
            for r in reports:
                report_text += f"{r['user']} ({r['time']}):\n{r['text']}\n\n"

        manager_section = ""
        if manager_notes_text:
            manager_section = f"""
=== MANAGER REPORTS ===
{manager_notes_text}

⚠️ CROSS-CHECK လုပ်ပါ: Manager report နဲ့ Operator report တိုက်စစ်ပြီး ကွာဟချက်တွေ ရှိရင် highlight လုပ်ပါ။
"""

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

{"🔍 MANAGER vs OPERATOR CROSS-CHECK" + chr(10) + "- Manager report နဲ့ operator report ကွာဟချက်တွေ" + chr(10) + "- မကိုက်ညီတာတွေ boss ကို သတိပေးပါ" if manager_notes_text else ""}

💡 BOSS ACTION ITEMS
- ဘာ action လုပ်သင့်လဲ

---
OPERATOR REPORTS:
{report_text}
{manager_section}"""

        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
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

        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
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
    chat_id = msg.chat_id

    # Manager private message စစ်မယ်
    if msg.chat.type == "private":
        user_id = msg.from_user.id
        if user_id in MANAGER_IDS:
            today = datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d")
            report_time = datetime.now(MYANMAR_TZ).strftime("%H:%M")
            mgr_name = MANAGER_IDS[user_id]["name"]
            mgr_group = MANAGER_IDS[user_id]["group"]
            if today not in manager_reports:
                manager_reports[today] = {}
            manager_reports[today][user_id] = {
                "name": mgr_name,
                "group": mgr_group,
                "text": msg.text,
                "time": report_time
            }
            # Sheet မှာ manager report သိမ်းမယ် (restart ဖြစ်ရင် မပျောက်အောင်)
            save_raw_report(today, f"manager_{mgr_group}", mgr_name, msg.text, report_time)
            await msg.reply_text("✅ Manager report သိမ်းပြီးပါပြီ။")
            logger.info(f"Manager report from {mgr_name}")
        return

    group_type = get_group_type(chat_id)

    if not group_type:
        return  # Unknown group — ignore

    today = datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d")
    user_id = msg.from_user.id
    tg_username = msg.from_user.username or ""
    report_time = datetime.now(MYANMAR_TZ).strftime("%H:%M")

    # Report ထဲက နာမည် extract မယ် — "အမည် - [နာမည်]" format
    name_match = re.search(r'အမည်\s*[-–]\s*\[?([^\]\n\(\[]+)', msg.text)
    extracted_name = name_match.group(1).strip().rstrip('-').strip() if name_match else ""
    if extracted_name and len(extracted_name) > 1:
        user_name = extracted_name
    else:
        user_name = msg.from_user.full_name or tg_username or "Unknown"

    daily_reports[today][group_type].append({
        "user": user_name,
        "text": msg.text,
        "time": report_time
    })

    # Sheet မှာ raw text သိမ်းမယ် (restart ဖြစ်ရင် data မပျောက်အောင်)
    save_raw_report(today, group_type, user_name, msg.text, report_time, user_id, tg_username)

    # Report ရပြီ confirmation reply
    await msg.reply_text(f"✅ {user_name} ရဲ့ report ရပြီပါပြီ။ ({report_time})")

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
    if update.effective_user.id not in [OWNER_TELEGRAM_ID, SECONDARY_OWNER_ID]:
        await update.message.reply_text("❌ Permission မရှိပါ")
        return

    await update.message.reply_text("⏳ Monthly report လုပ်နေပြီ...")

    now = datetime.now(MYANMAR_TZ)
    year = now.year
    month = now.month

    try:
        sheet = get_sheet()  # global client မ overwrite မဖြစ်အောင် get_sheet() သုံးမယ်

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

        gemini = genai.Client(api_key=GEMINI_API_KEY)
        response = gemini.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        summary = response.text

        max_len = 4000
        if len(summary) <= max_len:
            await update.message.reply_text("📊 Monthly Report\n\n" + summary)
        else:
            parts = [summary[i:i+max_len] for i in range(0, len(summary), max_len)]
            for idx, part in enumerate(parts, 1):
                await update.message.reply_text(f"📊 Monthly Report (Part {idx}/{len(parts)})\n\n" + part)
                await asyncio.sleep(0.5)

    except Exception as e:
        await update.message.reply_text(f"❌ Monthly report error: {str(e)}")

async def cmd_summarize_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in [OWNER_TELEGRAM_ID, SECONDARY_OWNER_ID]:
        await update.message.reply_text("❌ Permission မရှိပါ")
        return
    await update.message.reply_text("⏳ Summary လုပ်နေပြီ...")
    await send_daily_summary(context)


async def cmd_weekly_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in [OWNER_TELEGRAM_ID, SECONDARY_OWNER_ID]:
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

    # Memory ထဲမှာ မရှိရင် Sheet ကနေ ဖတ်မယ် (bot restart ဖြစ်ခဲ့ရင်)
    if not any(reports_by_group.values()):
        reports_by_group = get_todays_raw_reports(today)

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
        # Manager reports ကို skip မယ် — analytics မထုတ်ဘူး
        if group_type.startswith("manager_"):
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
                elif group_type == "designer":
                    # col3=Designs_Completed, col4=Revisions, col5=Designs_Pending, col7=Priority_Tomorrow
                    save_analytics(today, group_type, operator,
                        analytics.get("designs_completed", []),
                        analytics.get("revisions", []),
                        analytics.get("designs_pending", []),
                        "",
                        analytics.get("priority_tomorrow", []))
        except Exception as e:
            logger.error(f"Analytics error for {group_type}: {e}")

    # Manager report ရှာမယ် — memory မှာ မရှိရင် Sheet ကနေ ဖတ်မယ်
    manager_data = {}
    if today in manager_reports:
        manager_data = manager_reports[today]
    else:
        # Sheet ကနေ manager reports ပြန်ဖတ်မယ် (restart ဖြစ်ခဲ့ရင်)
        raw = get_todays_raw_reports(today)
        for key, reports in raw.items():
            if key.startswith("manager_"):
                group = key.replace("manager_", "")
                for r in reports:
                    manager_data[r["user"]] = {
                        "name": r["user"],
                        "group": group,
                        "text": r["text"],
                        "time": r["time"]
                    }

    # Manager report နဲ့ operator reports တိုက်စစ်ပြီး Gemini ကို ပို့မယ်
    manager_notes_text = ""
    for uid, mgr in manager_data.items():
        manager_notes_text += f"\n\n👔 {mgr['name']} ({mgr['group']}) Manager Report:\n{mgr['text']}"

    summary = generate_daily_summary(reports_by_group, today, manager_notes_text)

    max_len = 4000
    if len(summary) <= max_len:
        await context.bot.send_message(
            chat_id=OWNER_TELEGRAM_ID,
            text=f"📊 Daily Report Summary\n\n{summary}"
        )
        if SECONDARY_OWNER_ID:
            await context.bot.send_message(
                chat_id=SECONDARY_OWNER_ID,
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
            if SECONDARY_OWNER_ID:
                await context.bot.send_message(
                    chat_id=SECONDARY_OWNER_ID,
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
        if SECONDARY_OWNER_ID:
            await context.bot.send_message(
                chat_id=SECONDARY_OWNER_ID,
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
            if SECONDARY_OWNER_ID:
                await context.bot.send_message(
                    chat_id=SECONDARY_OWNER_ID,
                    text=f"{header}{part}"
                )
            await asyncio.sleep(0.5)

    logger.info("Weekly summary sent")


async def send_report_reminder(context: ContextTypes.DEFAULT_TYPE):
    """ညနေ ၅:၁၅ — report မတင်ရသေးတဲ့သူတွေကို group ထဲ list ပြမယ်"""
    today = datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d")

    # ဒီနေ့ report တင်ပြီးသူ ရှာမယ်
    try:
        sheet = get_sheet()
        ws = sheet.worksheet("Raw_Reports")
        records = ws.get_all_records()
        reported_ids = set()        # Telegram ID match
        reported_users = set()      # report ထဲက နာမည် match (case-insensitive)
        username_to_names = {}      # username → [နာမည်တွေ] (တစ်နေ့တည်း ၂ ခါ တင်ရင်)

        for r in records:
            if str(r.get("Date", "")) == today and not str(r.get("Group", "")).startswith("manager_"):
                uid = str(r.get("UserID", "")).strip()
                grp = str(r.get("Group", ""))
                uname = str(r.get("Username", "")).strip().lower()
                rpt_name = str(r.get("User", "")).strip().lower()

                if uid:
                    reported_ids.add((grp, uid))

                # username → report name mapping သိမ်းမယ်
                if uname:
                    key = (grp, uname)
                    if key not in username_to_names:
                        username_to_names[key] = set()
                    username_to_names[key].add(rpt_name)

                reported_users.add((grp, rpt_name))
    except Exception as e:
        logger.error(f"Reminder - get raw reports error: {e}")
        return

    # ဒီနေ့ leave ယူထားတဲ့သူ ရှာမယ် (reminder မပို့ဖို့)
    on_leave_today = set()
    try:
        if LEAVE_SPREADSHEET_ID:
            leave_sheet = get_leave_sheet()
            ws_leave = leave_sheet.worksheet("Leave_Requests")
            leave_records = ws_leave.get_all_records()
            for r in leave_records:
                leave_date = str(r.get("Leave_Date", "")).strip()
                status = str(r.get("Status", "")).strip()
                if leave_date == today and status == "Approved":
                    on_leave_today.add(str(r.get("Name", "")).strip())
    except Exception as e:
        logger.error(f"Reminder - get leave data error: {e}")

    # Leave bot Employees sheet ကနေ ဝန်ထမ်းစာရင်း ဖတ်မယ်
    employees_by_group = get_employees_by_group()
    if not employees_by_group:
        logger.warning("Reminder - no employee data found")
        return

    group_chat_map = {
        "production": PRODUCTION_GROUP_ID,
        "front_office": FRONT_OFFICE_GROUP_ID,
        "designer": DESIGNER_GROUP_ID,
    }

    for group_type, chat_id in group_chat_map.items():
        if not chat_id:
            continue
        employees = employees_by_group.get(group_type, [])
        if not employees:
            continue

        # Report မတင်ရသေးတဲ့သူ ရှာမယ် (leave ယူထားတဲ့သူ ဖြုတ်မယ်)
        missing = []
        for emp in employees:
            emp_name = emp["name"]
            emp_name_lower = emp_name.strip().lower()
            emp_id = emp["telegram_id"]
            emp_uname = emp.get("username", "").strip().lower()

            # 1. ID နဲ့ match
            by_id = (group_type, emp_id) in reported_ids

            # 2. Username + report name နဲ့ match
            # Same username ၂ ခါ တင်ရင် report ထဲက နာမည် ဖတ်မယ်
            by_username = False
            if emp_uname:
                uname_key = (group_type, emp_uname)
                names_from_username = username_to_names.get(uname_key, set())
                if emp_name_lower in names_from_username:
                    # username ကနေ ဒီ employee ရဲ့ နာမည် တွေ့တယ်
                    by_username = True
                elif len(names_from_username) == 1:
                    # username တစ်ခုတည်း တစ်ကြိမ်ပဲ တင်ရင် ဒီ employee ဆိုပြီး မှတ်မယ်
                    by_username = True

            # 3. Report name fallback (case-insensitive)
            by_name = (group_type, emp_name_lower) in reported_users

            reported = by_id or by_username or by_name

            # leave check (case-insensitive)
            on_leave = any(emp_name_lower == l.strip().lower() for l in on_leave_today)
            if not reported and not on_leave:
                missing.append(emp_name)

        if missing:
            names_list = "\n".join([f"  • {n}" for n in missing])
            msg = (
                f"⏰ ညနေ ၅:၁၅ Report Reminder\n\n"
                f"အောက်ပါ ဝန်ထမ်းများ ဒီနေ့ report မတင်ရသေးပါ:\n\n"
                f"{names_list}\n\n"
                f"မြန်မြန် တင်ပေးပါ 🙏"
            )
            try:
                await context.bot.send_message(chat_id=chat_id, text=msg)
                logger.info(f"Reminder sent to {group_type}: {missing}")
            except Exception as e:
                logger.error(f"Reminder send error ({group_type}): {e}")
        else:
            logger.info(f"Reminder - all reported in {group_type}")


# ==================== MAIN ====================

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("summarize", cmd_summarize_now))
    app.add_handler(CommandHandler("monthly", cmd_monthly))
    app.add_handler(CommandHandler("weekly", cmd_weekly_now))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_report))

    # Report reminder: 5:15 PM Myanmar = 10:45 UTC (တနင်္လာ-သောကြာ ပဲ)
    reminder_time = time(hour=10, minute=45)
    app.job_queue.run_daily(send_report_reminder, time=reminder_time, days=(0, 1, 2, 3, 4))

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
