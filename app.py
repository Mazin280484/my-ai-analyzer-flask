from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
REPORT_FILE = os.path.join(BASE_DIR, 'report.html')
PORT = int(os.environ.get("PORT", 5000))  # Use $PORT if set (for Render), else 5000 locally

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

def get_top_categories(cur, budget_ids, limit=3):
    try:
        cur.execute(f"""
            SELECT category, SUM(amount) as total
            FROM tasks
            WHERE dailyBudgetId IN ({','.join('?' for _ in budget_ids)})
            GROUP BY category
            ORDER BY total DESC
            LIMIT ?
        """, (*budget_ids, limit))
        return cur.fetchall()
    except Exception as e:
        print(f"get_top_categories error: {e}")
        return []

def get_top_subtasks(cur, budget_ids, limit=3):
    try:
        cur.execute(f"""
            SELECT subTask, SUM(amount) as total
            FROM tasks
            WHERE dailyBudgetId IN ({','.join('?' for _ in budget_ids)})
            GROUP BY subTask
            ORDER BY total DESC
            LIMIT ?
        """, (*budget_ids, limit))
        return cur.fetchall()
    except Exception as e:
        print(f"get_top_subtasks error: {e}")
        return []

def get_all_budget_ids(cur):
    try:
        cur.execute("SELECT id FROM daily_budget ORDER BY date")
        rows = cur.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        print(f"get_all_budget_ids error: {e}")
        return []

def get_last_n_budget_ids(cur, n):
    try:
        cur.execute("SELECT id FROM daily_budget ORDER BY date DESC LIMIT ?", (n,))
        rows = cur.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        print(f"get_last_n_budget_ids error: {e}")
        return []

def format_category_list(items):
    if not items:
        return "<li>No data available.</li>"
    return "".join(f"<li><span class='item-label'>{cat}</span> <span class='amount'>({amt:.2f} OMR)</span></li>" for cat, amt in items)

def format_subtask_list(items):
    if not items:
        return "<li>No data available.</li>"
    return "".join(f"<li><span class='item-label'>{subtask}</span> <span class='amount'>({amt:.2f} OMR)</span></li>" for subtask, amt in items)

def analyze_db(db_path, filename):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Get all budget IDs, last 7 budget IDs, and (X)
        all_budget_ids = get_all_budget_ids(cur)
        last7_budget_ids = get_last_n_budget_ids(cur, 7)
        X = len(all_budget_ids)

        # -- Saving Summary Calculations --
        # Overall (All records)
        cur.execute("SELECT SUM(planBudget * 0.2), SUM(saving) FROM daily_budget")
        row = cur.fetchone()
        overall_goal_savings = row[0] if row and row[0] is not None else 0
        overall_total_savings = row[1] if row and row[1] is not None else 0

        # Last 7 records
        cur.execute(
            "SELECT SUM(planBudget * 0.2), SUM(saving) FROM daily_budget WHERE id IN ({seq})".format(
                seq=','.join(['?']*len(last7_budget_ids))
            ),
            last7_budget_ids if last7_budget_ids else [-1]
        )
        row7 = cur.fetchone()
        last7_goal_savings = row7[0] if row7 and row7[0] is not None else 0
        last7_total_savings = row7[1] if row7 and row7[1] is not None else 0

        # For overall (all records)
        all_top_categories = get_top_categories(cur, all_budget_ids, 3) if all_budget_ids else []
        all_top_subtasks = get_top_subtasks(cur, all_budget_ids, 3) if all_budget_ids else []

        # For last 7 records
        last7_top_categories = get_top_categories(cur, last7_budget_ids, 3) if last7_budget_ids else []
        last7_top_subtasks = get_top_subtasks(cur, last7_budget_ids, 3) if last7_budget_ids else []

        conn.close()
    except Exception as e:
        print(f"Error analyzing DB: {e}")
        X = 0
        all_top_categories = []
        all_top_subtasks = []
        last7_top_categories = []
        last7_top_subtasks = []
        overall_goal_savings = 0
        overall_total_savings = 0
        last7_goal_savings = 0
        last7_total_savings = 0

    # --- Saving Summary Section ---
    saving_html = f"""
    <section class="saving-section">
      <h2>Saving Summary</h2>
      <div class="saving-block">
        <p class="saving-title"><b>Overall savings across the last ({X}) records</b></p>
        <ul class="saving-list">
          <li>
            <span class="section-label">Overall Total Goal Savings</span>
            <span class="amount">({overall_goal_savings:.2f} OMR)</span>
          </li>
          <li>
            <span class="section-label">Overall Total Savings</span>
            <span class="amount">({overall_total_savings:.2f} OMR)</span>
          </li>
        </ul>
        <p class="saving-title"><b>Your savings in the last 7 records</b></p>
        <ul class="saving-list">
          <li>
            <span class="section-label">Total Goal Savings</span>
            <span class="amount">({last7_goal_savings:.2f} OMR)</span>
          </li>
          <li>
            <span class="section-label">Total Savings</span>
            <span class="amount">({last7_total_savings:.2f} OMR)</span>
          </li>
        </ul>
      </div>
    </section>
    """

    # --- Highlights Section (unchanged except moved below Savings) ---
    summary_html = f"""
    {saving_html}
    <section class="highlights-section">
      <h2>Highlights</h2>
      <div class="highlight-block">
        <p class="highlight-title"><b>Analyze what factors overall affected your budget across the last ({X}) records</b></p>
        <ul class="highlight-list">
          <li>
            <span class="section-label">Top Spending Categories</span>
            <ul class="sublist">
              {format_category_list(all_top_categories)}
            </ul>
          </li>
          <li>
            <span class="section-label">Top Expenses Sub-Tasks</span>
            <ul class="sublist">
              {format_subtask_list(all_top_subtasks)}
            </ul>
          </li>
        </ul>
        <p class="highlight-title"><b>See what affected your budget in the last 7 records</b></p>
        <ul class="highlight-list">
          <li>
            <span class="section-label">Top Spending Categories</span>
            <ul class="sublist">
              {format_category_list(last7_top_categories)}
            </ul>
          </li>
          <li>
            <span class="section-label">Top Expenses Sub-Tasks</span>
            <ul class="sublist">
              {format_subtask_list(last7_top_subtasks)}
            </ul>
          </li>
        </ul>
      </div>
    </section>
    """
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
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            html {{
                font-size: 16px;
            }}
            @media (max-width: 1200px) {{
                html {{ font-size: 15px; }}
            }}
            @media (max-width: 900px) {{
                html {{ font-size: 14px; }}
            }}
            @media (max-width: 600px) {{
                html {{ font-size: 13px; }}
            }}
            @media (max-width: 400px) {{
                html {{ font-size: 12px; }}
            }}
            body {{
                font-family: 'Segoe UI', Arial, sans-serif;
                background: #f7f9fa;
                color: #212b36;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 780px;
                margin: 36px auto 30px auto;
                background: #fff;
                padding: 2.0rem 2.2rem;
                border-radius: 12px;
                box-shadow: 0 4px 18px rgba(50,60,70,0.09), 0 1.5px 4px rgba(0,0,0,0.04);
            }}
            h1 {{
                color: #355c7d;
                font-size: 2.1rem;
                letter-spacing: 0.01em;
                margin-bottom: 1.8rem;
                margin-top: 0.4rem;
                font-weight: 600;
                border-bottom: 2px solid #e9eef3;
                padding-bottom: 0.6rem;
            }}
            h2 {{
                font-size: 1.45rem;
                color: #2d5e9e;
                margin-top: 0.2rem;
                margin-bottom: 1.2rem;
                font-weight: 600;
                letter-spacing: 0.01em;
            }}
            .highlights-section {{
                margin-bottom: 1.6rem;
            }}
            .highlight-block {{
                background: #f2f7fb;
                border-radius: 8px;
                padding: 1.15rem 1.3rem 1.1rem 1.3rem;
                margin-bottom: 1.2rem;
                box-shadow: 0 1px 3px rgba(44,62,80,0.04);
            }}
            .highlight-title {{
                font-size: 1.03rem;
                margin: 0.8em 0 0.7em 0;
                color: #28466d;
                font-weight: 500;
                letter-spacing: 0.01em;
            }}
            .highlight-list {{
                margin-left: 0.5em;
                margin-bottom: 1.1em;
                padding-left: 1.1em;
            }}
            .highlight-list > li {{
                margin-bottom: 0.8em;
            }}
            .section-label {{
                font-weight: 600;
                color: #3a4256;
                letter-spacing: 0.01em;
            }}
            .sublist {{
                margin: 0.2em 0 0.2em 0.6em;
                padding-left: 1.1em;
                list-style-type: disc;
            }}
            .sublist li {{
                margin-bottom: 0.2em;
                line-height: 1.7;
                font-size: 1em;
            }}
            .item-label {{
                color: #394960;
                font-weight: 500;
            }}
            .amount {{
                color: #336699;
                font-weight: 600;
                margin-left: 0.15em;
                letter-spacing: 0.01em;
            }}
            /* Saving Summary styles */
            .saving-section {{
                margin-bottom: 1.8rem;
            }}
            .saving-block {{
                background: #f5fbe9;
                border-radius: 8px;
                padding: 1.15rem 1.3rem 1.1rem 1.3rem;
                margin-bottom: 1.2rem;
                box-shadow: 0 1px 3px rgba(44,62,80,0.04);
            }}
            .saving-title {{
                font-size: 1.03rem;
                margin: 0.8em 0 0.7em 0;
                color: #3d5d2d;
                font-weight: 500;
                letter-spacing: 0.01em;
            }}
            .saving-list {{
                margin-left: 0.5em;
                margin-bottom: 1.1em;
                padding-left: 1.1em;
            }}
            .saving-list > li {{
                margin-bottom: 0.8em;
            }}
            @media (max-width: 600px) {{
                .container {{
                    padding: 1.2rem 0.7rem;
                }}
                h1, h2 {{
                    font-size: 1.1rem;
                }}
                .highlight-title, .section-label, .saving-title {{
                    font-size: 0.99rem;
                }}
                .footer {{
                    font-size: 0.93rem;
                }}
            }}
            .footer {{
                font-size: 0.98rem;
                color: #5a6f89;
                border-top: 1.5px solid #e9eef3;
                margin-top: 2.4rem;
                padding-top: 1.2rem;
                text-align: left;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>AI Analyzer Report</h1>
            {summary_html}
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