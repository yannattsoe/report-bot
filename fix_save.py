import re

with open('report_bot_gemini.py', 'r') as f:
    content = f.read()

old = '''        ws.append_row([
            date,
            operator,
            json.dumps(jobs_completed, ensure_ascii=False),
            json.dumps(jobs_pending, ensure_ascii=False),
            json.dumps(errors, ensure_ascii=False),
            machine_issues,
            json.dumps(job_types, ensure_ascii=False),
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ])'''

new = '''        if group_type == "production":
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
            ])'''

content = content.replace(old, new)

with open('report_bot_gemini.py', 'w') as f:
    f.write(content)

print("Done")
