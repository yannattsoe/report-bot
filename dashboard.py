"""
Golden 8 KPI Dashboard
Flask web app — Railway မှာ bot နဲ့ တပြိုင်နက် run မယ်
Google Sheets ကနေ data ဖတ်ပြီး KPI ပြမယ်
"""

import os
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

from flask import Flask, render_template_string
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

MYANMAR_TZ = ZoneInfo("Asia/Yangon")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
LEAVE_SPREADSHEET_ID = os.environ.get("LEAVE_SPREADSHEET_ID", "")
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "golden8")


def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


def get_today_report_status():
    """Raw_Reports sheet ကနေ ဒီနေ့ report တင်ပြီး/မတင်ရသေးတဲ့သူ စစ်မယ်"""
    today = datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d")
    result = {"production": [], "front_office": [], "designer": []}
    try:
        sheet = get_sheet()
        ws = sheet.worksheet("Raw_Reports")
        records = ws.get_all_records()
        for r in records:
            if str(r.get("Date", "")) == today:
                grp = str(r.get("Group", ""))
                if grp in result:
                    result[grp].append({
                        "user": r.get("User", ""),
                        "time": r.get("Time", "")
                    })
    except Exception as e:
        pass
    return result


def get_production_analytics(days=7):
    """Production_Analytics sheet ကနေ ပြီးခဲ့တဲ့ N ရက် data ဖတ်မယ်"""
    try:
        sheet = get_sheet()
        ws = sheet.worksheet("Production_Analytics")
        records = ws.get_all_records()
        cutoff = (datetime.now(MYANMAR_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        recent = [r for r in records if str(r.get("Date", "")) >= cutoff]
        return recent
    except:
        return []


def get_frontoffice_analytics(days=7):
    try:
        sheet = get_sheet()
        ws = sheet.worksheet("FrontOffice_Analytics")
        records = ws.get_all_records()
        cutoff = (datetime.now(MYANMAR_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        return [r for r in records if str(r.get("Date", "")) >= cutoff]
    except:
        return []


def get_design_analytics(days=7):
    try:
        sheet = get_sheet()
        ws = sheet.worksheet("Design_Analytics")
        records = ws.get_all_records()
        cutoff = (datetime.now(MYANMAR_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        return [r for r in records if str(r.get("Date", "")) >= cutoff]
    except:
        return []


def parse_json_field(val):
    try:
        if isinstance(val, list):
            return val
        return json.loads(val) if val else []
    except:
        return []


def build_weekly_trend(prod_data):
    """ရက်စွဲ တစ်ခုချင်း jobs completed count"""
    daily = defaultdict(int)
    daily_errors = defaultdict(int)
    for r in prod_data:
        date = str(r.get("Date", ""))
        jobs = parse_json_field(r.get("Jobs_Completed", "[]"))
        errors = parse_json_field(r.get("Errors", "[]"))
        daily[date] += len(jobs)
        daily_errors[date] += len(errors)

    # Last 7 days အကုန် (data မရှိရင် 0)
    dates = []
    jobs_counts = []
    error_counts = []
    for i in range(6, -1, -1):
        d = (datetime.now(MYANMAR_TZ) - timedelta(days=i)).strftime("%Y-%m-%d")
        short = (datetime.now(MYANMAR_TZ) - timedelta(days=i)).strftime("%m/%d")
        dates.append(short)
        jobs_counts.append(daily.get(d, 0))
        error_counts.append(daily_errors.get(d, 0))
    return dates, jobs_counts, error_counts


def calc_error_rate(prod_data):
    total_jobs = 0
    total_errors = 0
    for r in prod_data:
        total_jobs += len(parse_json_field(r.get("Jobs_Completed", "[]")))
        total_jobs += len(parse_json_field(r.get("Jobs_Pending", "[]")))
        total_errors += len(parse_json_field(r.get("Errors", "[]")))
    if total_jobs == 0:
        return 0
    return round((total_errors / total_jobs) * 100, 1)


def get_job_type_breakdown(prod_data):
    counts = defaultdict(int)
    for r in prod_data:
        types = parse_json_field(r.get("Job_Types", "[]"))
        for t in types:
            counts[str(t).strip()] += 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="my">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Golden 8 KPI Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  .header { background: linear-gradient(135deg, #1e40af, #7c3aed); padding: 20px 30px; display: flex; align-items: center; justify-content: space-between; }
  .header h1 { font-size: 1.5rem; font-weight: 700; }
  .header .sub { font-size: 0.85rem; opacity: 0.8; margin-top: 4px; }
  .refresh-btn { background: rgba(255,255,255,0.2); border: none; color: white; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 0.85rem; }
  .refresh-btn:hover { background: rgba(255,255,255,0.3); }
  .container { padding: 24px; max-width: 1400px; margin: 0 auto; }
  .section-title { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; margin-bottom: 12px; margin-top: 28px; }
  .grid-4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
  .grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 16px; }
  .grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
  .card { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }
  .kpi-card { text-align: center; }
  .kpi-label { font-size: 0.78rem; color: #94a3b8; margin-bottom: 8px; }
  .kpi-value { font-size: 2.2rem; font-weight: 700; }
  .kpi-sub { font-size: 0.75rem; color: #64748b; margin-top: 4px; }
  .green { color: #22c55e; }
  .yellow { color: #eab308; }
  .red { color: #ef4444; }
  .blue { color: #60a5fa; }
  .purple { color: #a78bfa; }
  .card h3 { font-size: 0.95rem; font-weight: 600; margin-bottom: 16px; color: #cbd5e1; }
  .report-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #334155; }
  .report-row:last-child { border-bottom: none; }
  .badge { padding: 3px 10px; border-radius: 20px; font-size: 0.72rem; font-weight: 600; }
  .badge-green { background: #14532d; color: #22c55e; }
  .badge-red { background: #450a0a; color: #f87171; }
  .group-header { font-size: 0.72rem; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin: 12px 0 6px; }
  .error-item { padding: 6px 0; font-size: 0.82rem; color: #fca5a5; border-bottom: 1px solid #334155; }
  .error-item:last-child { border-bottom: none; }
  .job-type-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; }
  .job-type-bar { height: 8px; background: #6366f1; border-radius: 4px; min-width: 4px; }
  .job-type-label { font-size: 0.82rem; color: #cbd5e1; flex: 1; }
  .job-type-count { font-size: 0.82rem; color: #94a3b8; }
  canvas { max-height: 220px; }
  .updated { font-size: 0.72rem; color: #475569; text-align: right; margin-top: 20px; }
  .no-data { color: #475569; font-size: 0.82rem; font-style: italic; }
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>🖨️ Golden 8 KPI Dashboard</h1>
    <div class="sub">Production • Front Office • Design — Real-time Overview</div>
  </div>
  <button class="refresh-btn" onclick="location.reload()">🔄 Refresh</button>
</div>

<div class="container">

  <!-- KPI Summary Cards -->
  <div class="section-title">ဒီနေ့ Overview</div>
  <div class="grid-4">
    <div class="card kpi-card">
      <div class="kpi-label">Production Reports</div>
      <div class="kpi-value {{ 'green' if prod_reports > 0 else 'red' }}">{{ prod_reports }}</div>
      <div class="kpi-sub">တင်ပြီးသူ / ဒီနေ့</div>
    </div>
    <div class="card kpi-card">
      <div class="kpi-label">Front Office Reports</div>
      <div class="kpi-value {{ 'green' if fo_reports > 0 else 'red' }}">{{ fo_reports }}</div>
      <div class="kpi-sub">တင်ပြီးသူ / ဒီနေ့</div>
    </div>
    <div class="card kpi-card">
      <div class="kpi-label">Design Reports</div>
      <div class="kpi-value {{ 'green' if design_reports > 0 else 'red' }}">{{ design_reports }}</div>
      <div class="kpi-sub">တင်ပြီးသူ / ဒီနေ့</div>
    </div>
    <div class="card kpi-card">
      <div class="kpi-label">Error Rate (7 ရက်)</div>
      <div class="kpi-value {{ 'green' if error_rate < 5 else ('yellow' if error_rate < 15 else 'red') }}">{{ error_rate }}%</div>
      <div class="kpi-sub">Production errors</div>
    </div>
  </div>

  <!-- Report Status -->
  <div class="section-title">ဒီနေ့ Report Status</div>
  <div class="grid-3">

    <div class="card">
      <h3>🏭 Production</h3>
      {% if today_status.production %}
        {% for r in today_status.production %}
        <div class="report-row">
          <span style="font-size:0.85rem">{{ r.user }}</span>
          <span class="badge badge-green">✓ {{ r.time }}</span>
        </div>
        {% endfor %}
      {% else %}
        <div class="no-data">မတင်ရသေးပါ</div>
      {% endif %}
    </div>

    <div class="card">
      <h3>🖥️ Front Office</h3>
      {% if today_status.front_office %}
        {% for r in today_status.front_office %}
        <div class="report-row">
          <span style="font-size:0.85rem">{{ r.user }}</span>
          <span class="badge badge-green">✓ {{ r.time }}</span>
        </div>
        {% endfor %}
      {% else %}
        <div class="no-data">မတင်ရသေးပါ</div>
      {% endif %}
    </div>

    <div class="card">
      <h3>🎨 Design</h3>
      {% if today_status.designer %}
        {% for r in today_status.designer %}
        <div class="report-row">
          <span style="font-size:0.85rem">{{ r.user }}</span>
          <span class="badge badge-green">✓ {{ r.time }}</span>
        </div>
        {% endfor %}
      {% else %}
        <div class="no-data">မတင်ရသေးပါ</div>
      {% endif %}
    </div>

  </div>

  <!-- Charts -->
  <div class="section-title">Weekly Trend (ပြီးခဲ့တဲ့ ၇ ရက်)</div>
  <div class="grid-2">

    <div class="card">
      <h3>📦 Jobs Completed vs Errors</h3>
      <canvas id="weeklyChart"></canvas>
    </div>

    <div class="card">
      <h3>🏷️ Job Type Breakdown</h3>
      {% if job_types %}
        {% set max_count = job_types.values() | max %}
        {% for jtype, count in job_types.items() %}
        <div class="job-type-row">
          <span class="job-type-label">{{ jtype }}</span>
          <div class="job-type-bar" style="width: {{ [((count / max_count) * 150) | int, 4] | max }}px"></div>
          <span class="job-type-count">{{ count }}</span>
        </div>
        {% endfor %}
      {% else %}
        <div class="no-data">Data မရှိသေးပါ</div>
      {% endif %}
    </div>

  </div>

  <div class="updated">Last updated: {{ updated_at }} (Myanmar Time)</div>

</div>

<script>
const ctx = document.getElementById('weeklyChart').getContext('2d');
new Chart(ctx, {
  type: 'bar',
  data: {
    labels: {{ dates | tojson }},
    datasets: [
      {
        label: 'Jobs Completed',
        data: {{ jobs_counts | tojson }},
        backgroundColor: '#6366f1',
        borderRadius: 4,
      },
      {
        label: 'Errors',
        data: {{ error_counts | tojson }},
        backgroundColor: '#ef4444',
        borderRadius: 4,
      }
    ]
  },
  options: {
    responsive: true,
    plugins: { legend: { labels: { color: '#94a3b8', font: { size: 11 } } } },
    scales: {
      x: { ticks: { color: '#64748b' }, grid: { color: '#1e293b' } },
      y: { ticks: { color: '#64748b' }, grid: { color: '#334155' }, beginAtZero: true }
    }
  }
});
</script>

</body>
</html>
"""


@app.route("/")
def index():
    return "Golden 8 Dashboard — <a href='/dashboard'>Go to Dashboard</a>", 200


@app.route("/dashboard")
def dashboard():
    try:
        today_status = get_today_report_status()
        prod_data = get_production_analytics(days=7)
        dates, jobs_counts, error_counts = build_weekly_trend(prod_data)
        error_rate = calc_error_rate(prod_data)
        job_types = get_job_type_breakdown(prod_data)

        return render_template_string(
            HTML_TEMPLATE,
            today_status=today_status,
            prod_reports=len(today_status.get("production", [])),
            fo_reports=len(today_status.get("front_office", [])),
            design_reports=len(today_status.get("designer", [])),
            error_rate=error_rate,
            dates=dates,
            jobs_counts=jobs_counts,
            error_counts=error_counts,
            job_types=job_types,
            updated_at=datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d %H:%M"),
        )
    except Exception as e:
        return f"<pre>Dashboard error: {e}</pre>", 500


if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
