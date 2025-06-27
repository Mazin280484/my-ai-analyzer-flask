from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
REPORT_FILE = os.path.join(BASE_DIR, 'report.html')
PORT = 5000

app = Flask(__name__)
CORS(app)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------- Utility Functions ----------------

def fetch_single(cur, query, default=0):
    try:
        cur.execute(query)
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else default
    except Exception as e:
        print(f"fetch_single error: {e}")
        return default

def get_top_categories(cur, limit=5):
    try:
        cur.execute("""
            SELECT category, SUM(amount) as total
            FROM tasks
            GROUP BY category
            ORDER BY total DESC
            LIMIT ?
        """, (limit,))
        return cur.fetchall()
    except Exception as e:
        print(f"get_top_categories error: {e}")
        return []

def get_top_subtask(cur):
    try:
        cur.execute("""
            SELECT subTask, SUM(amount) as total
            FROM tasks
            GROUP BY subTask
            ORDER BY total DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, 0)
    except Exception as e:
        print(f"get_top_subtask error: {e}")
        return (None, 0)

def get_overspending_days(cur, plan_budget):
    try:
        cur.execute("""
            SELECT date, SUM(amount) as total
            FROM tasks
            JOIN daily_budget ON tasks.dailyBudgetId = daily_budget.id
            GROUP BY date
            HAVING total > ?
            ORDER BY total DESC
        """, (plan_budget,))
        return cur.fetchall()
    except Exception as e:
        print(f"get_overspending_days error: {e}")
        return []

def analyze_db(db_path, filename):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("SELECT date, saving FROM daily_budget ORDER BY date DESC LIMIT 1")
        row = cur.fetchone()
        today_date, today_saving = (row[0], row[1]) if row else ("N/A", 0)

        plan_budget = fetch_single(cur, "SELECT planBudget FROM daily_budget ORDER BY date DESC LIMIT 1")
        goal_saving = 0.2 * plan_budget
        saving_vs_goal = today_saving - goal_saving

        top_categories = get_top_categories(cur, 5)
        top_subtask, top_subtask_amt = get_top_subtask(cur)
        overspending_days = get_overspending_days(cur, plan_budget)

        conn.close()
    except Exception as e:
        print(f"Error analyzing DB: {e}")
        today_saving = 0
        today_date = "N/A"
        goal_saving = 0
        top_categories = []
        top_subtask = None
        top_subtask_amt = 0
        overspending_days = []

    summary_html = f"""
    <section class="goal">
      <h2>Savings Overview</h2>
      <ul>
        <li><strong>Target: Save 20% of Planned Budget</strong></li>
        <li>Today's Savings <span class="date">({today_date})</span>: <span class="amount">{today_saving:.2f} OMR</span></li>
        <li>Target Savings: <span class="amount">{goal_saving:.2f} OMR</span></li>
        <li>
          Progress: 
          <span class="{'success' if today_saving >= goal_saving else 'fail'}">
            {'Goal achieved!' if today_saving >= goal_saving else 'Target not met'}
          </span>
          <span class="compare">
            ({today_saving:.2f} OMR vs {goal_saving:.2f} OMR)
          </span>
        </li>
      </ul>
    </section>
    <hr>
    <section class="insights">
      <h2>Insights & Highlights</h2>
      <ol>
        <li><strong>What affected your goal today?</strong><ul>"""

    if today_saving >= goal_saving:
        summary_html += "<li class='success'>You've reached your savings goal for today.</li>"
    else:
        summary_html += "<li>Review major expenses and higher spending days.</li>"
        if top_categories:
            summary_html += "<li>Main categories impacting your savings: "
            summary_html += ", ".join(f"<b>{cat}</b>" for cat, _ in top_categories[:2]) + "</li>"

    summary_html += "</ul></li>"

    if top_categories:
        summary_html += "<li><b>Top Spending Categories:</b> " + ", ".join(
            f"{cat} <span class='amount'>({amt:.2f} OMR)</span>" for cat, amt in top_categories
        ) + "</li>"
    else:
        summary_html += "<li>No spending category data available.</li>"

    if top_subtask:
        summary_html += f"<li><b>Highest Expense Sub-task:</b> {top_subtask} <span class='amount'>({top_subtask_amt:.2f} OMR)</span></li>"
    else:
        summary_html += "<li>No sub-task data available.</li>"

    if overspending_days:
        summary_html += "<li><b>Days Exceeding Budget:</b><ul>"
        for date, total in overspending_days[:3]:
            summary_html += f"<li>{date}: <span class='amount overspent'>{total:.2f} OMR</span></li>"
        summary_html += "</ul></li>"
    else:
        summary_html += "<li>No days of overspending detected.</li>"

    summary_html += "</ol></section>"
    return summary_html

# ---------------- Upload Endpoint ----------------

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    db_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(db_path)

    summary_html = analyze_db(db_path, file.filename)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>AI Analyzer Report</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f4f4f4;
                color: #222;
                padding: 20px;
            }}
            .container {{
                max-width: 700px;
                margin: auto;
                background: #fff;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.1);
            }}
            h1 {{ color: #355c7d; }}
            .success {{ color: green; font-weight: bold; }}
            .fail {{ color: red; font-weight: bold; }}
            .amount {{ color: #333; font-weight: bold; }}
            .overspent {{ color: red; font-weight: bold; }}
            .date, .compare {{ color: #888; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>AI Analyzer Report</h1>
            {summary_html}
            <hr>
            <div class="footer">
                <b>Last uploaded DB:</b> {file.filename}<br>
                <b>Generated:</b> {timestamp}
            </div>
        </div>
    </body>
    </html>
    """

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    # Use HTTPS for report_url if on Render or if request is secure
    scheme = "https" if request.is_secure or "onrender.com" in request.host else "http"
    return jsonify({'success': True, 'report_url': f'{scheme}://{request.host}/report'}), 200

@app.route('/report', methods=['GET'])
def report():
    if not os.path.exists(REPORT_FILE):
        return "<h1>AI Analyzer Report</h1><p>No analysis yet.</p>", 200
    return send_file(REPORT_FILE)

# ---------------- Root Welcome Endpoint ----------------

@app.route('/', methods=['GET'])
def index():
    return "<h1>AI Analyzer Backend Running</h1><p>Use /upload (POST) to upload a database and /report (GET) to see the latest report.</p>", 200

if __name__ == '__main__':
    if not os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write("<h1>AI Analyzer Report</h1><p>No analysis yet.</p>")
    app.run(host='0.0.0.0', port=PORT, debug=True)