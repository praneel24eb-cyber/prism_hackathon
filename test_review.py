"""Quick test script for CodeGuardian."""
import httpx
import json

SAMPLE_DIFF = """--- a/app.py
+++ b/app.py
@@ -1,10 +1,25 @@
+import os
+import sqlite3
+
+DB_PASSWORD = "admin123"
+SECRET_KEY = "sk-12345-hardcoded-key"
+
+def get_user(username):
+    conn = sqlite3.connect("app.db")
+    query = f"SELECT * FROM users WHERE name = '{username}'"
+    result = conn.execute(query)
+    return result.fetchall()
+
+def process_users():
+    users = get_all_users()
+    for user in users:
+        orders = db.query(f"SELECT * FROM orders WHERE user_id={user.id}")
+        for order in orders:
+            send_email(user.email, order)
+
+@app.route("/admin")
+def admin_panel():
+    return render_template("admin.html", data=get_all_data())
"""

response = httpx.post(
    "http://localhost:8000/test-review",
    json={
        "diff": SAMPLE_DIFF,
        "repo": "test/demo-repo",
        "pr_number": 42,
    },
    timeout=120.0,
)

data = response.json()
print("=" * 60)
print(f"Status: {response.status_code}")
print(f"Issues Found: {data.get('issues', 0)}")
print(f"Risk Score: {data.get('risk_score', 0)}/10")
print("=" * 60)
print()
print(data.get("review", "No review generated"))
