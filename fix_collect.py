with open('report_bot_gemini.py', 'r') as f:
    content = f.read()

old = '''    if analytics:
        operator = analytics.get("operator", user_name)
        save_analytics(
            today, group_type, operator,
            analytics.get("jobs_completed", []),
            analytics.get("jobs_pending", []),
            analytics.get("errors", []),
            analytics.get("machine_issues", ""),
            analytics.get("job_types", [])
        )'''

new = '''    if analytics:
        operator = analytics.get("operator", user_name)
        if group_type == "production":
            save_analytics(
                today, group_type, operator,
                analytics.get("jobs_completed", []),
                analytics.get("jobs_pending", []),
                analytics.get("errors", []),
                analytics.get("machine_issues", ""),
                analytics.get("job_types", [])
            )
        elif group_type == "front_office":
            save_analytics(
                today, group_type, operator,
                analytics.get("orders_received", []),
                analytics.get("payments_collected", []),
                analytics.get("pending_followup", []),
                analytics.get("issues", ""),
                []
            )
git add .
git commit -m "fix front office and designer analytics keys"
git push
