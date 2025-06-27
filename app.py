from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import sqlite3
from datetime import datetime
from transformers import GPT2LMHeadModel, GPT2Tokenizer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
REPORT_FILE = os.path.join(BASE_DIR, 'report.html')
PORT = 5000

app = Flask(__name__)
CORS(app)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------- GPT-2 Chatbot Setup ----------------
print("Loading GPT-2 model...")
model_name = "distilgpt2"
tokenizer = GPT2Tokenizer.from_pretrained(model_name)
model = GPT2LMHeadModel.from_pretrained(model_name)
print("GPT-2 model loaded.")

def generate_gpt2_reply(prompt, max_length=120):
    inputs = tokenizer.encode(prompt, return_tensors="pt")
    outputs = model.generate(
        inputs,
        max_length=max_length,
        pad_token_id=tokenizer.eos_token_id,
        do_sample=True,
        top_k=50,
        top_p=0.95
    )
    reply = tokenizer.decode(outputs[0], skip_special_tokens=True)
    if reply.startswith(prompt):
        reply = reply[len(prompt):]
    return reply.strip()

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    prompt = data.get("message", "")
    if not prompt.strip():
        return jsonify({"error": "No input message provided"}), 400
    reply = generate_gpt2_reply(prompt)
    return jsonify({"response": reply})

# ---------------- Database Analysis & Utility ----------------

def fetch_single(cur, query, default=0):
    try:
        cur.execute(query)
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else default
    except Exception:
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
    except Exception:
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
        if row:
            return row[0], row[1]
    except Exception:
        pass
    return None, 0

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
    except Exception:
        return []

def analyze_db(db_path, filename):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("SELECT date, saving FROM daily_budget ORDER BY date DESC LIMIT 1")
        row = cur.fetchone()
        today_saving = row[1] if row else 0
        today_date = row[0] if row else "N/A"

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
        plan_budget = 0
        goal_saving = 0
        saving_vs_goal = 0
        top_categories = []
        top_subtask = None
        top_subtask_amt = 0
        overspending_days = []

    summary_html = f"""
    <section class="goal">
      <h2>Savings Overview</h2>
      <ul>
        <li><strong>Target:</strong> Save 20% of Planned Budget</li>
        <li>Today's Savings <span class="date">({today_date})</span>: <span class="amount">{today_saving:.2f} OMR</span></li>
        <li>Target Savings: <span class="amount">{goal_saving:.2f} OMR</span></li>
        <li>
          Progress:
          <span class="{'success' if today_saving >= goal_saving else 'fail'}">
            {'Goal achieved' if today_saving >= goal_saving else 'Target not met'}
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
        <li>
          <strong>What affected your goal today?</strong>
          <ul>
    """
    if today_saving >= goal_saving:
        summary_html += "<li class='success'>You've reached your savings goal for today.</li>"
    else:
        summary_html += "<li>Review high expenses and budget breakdown.</li>"
        if top_categories:
            summary_html += "<li>Main categories impacting savings: "
            summary_html += ", ".join(f"<b>{cat}</b>" for cat, _ in top_categories[:2])
            summary_html += "</li>"
    summary_html += "</ul></li>"

    if top_categories:
        summary_html += "<li><b>Top Spending Categories:</b> "
        summary_html += ", ".join(f"{cat} <span class='amount'>({amt:.2f} OMR)</span>" for cat, amt in top_categories)
        summary_html += "</li>"
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

# ---------------- File Upload & Report Endpoint ----------------

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
            :root {{
                --accent: #355c7d;
                --success: #2a9d8f;
                --fail: #e63946;
                --bg: #f8f9fa;
                --panel: #fff;
                --muted: #888;
                --overspent: #e63946;
                --amount: #22223b;
            }}
            body {{
                font-family: 'Segoe UI', Arial, sans-serif;
                margin: 0;
                background: var(--bg);
                color: var(--amount);
            }}
            .container {{
                max-width: 700px;
                margin: 40px auto;
                padding: 24px 28px 28px 28px;
                background: var(--panel);
                border-radius: 18px;
                box-shadow: 0 4px 32px rgba(53,92,125,0.07);
            }}
            h1 {{
                color: var(--accent);
                font-size: 2.2em;
                margin-bottom: 0.1em;
                letter-spacing: -1px;
            }}
            h2 {{
                color: var(--accent);
                margin-top: 1.2em;
                margin-bottom: 0.4em;
                font-size: 1.32em;
            }}
            ul, ol {{
                padding-left: 1.5em;
            }}
            .goal, .insights {{
                margin-bottom: 1.5em;
            }}
            .success {{
                color: var(--success);
                font-weight: 600;
            }}
            .fail {{
                color: var(--fail);
                font-weight: 600;
            }}
            .amount {{
                color: var(--amount);
                font-weight: 500;
            }}
            .overspent {{
                color: var(--overspent);
                font-weight: 600;
            }}
            .compare {{
                color: var(--muted);
                font-size: 0.95em;
                margin-left: 0.5em;
            }}
            .date {{
                color: var(--muted);
                font-size: 0.98em;
                margin-left: 0.2em;
            }}
            hr {{
                border: none;
                border-top: 1.5px solid #eee;
                margin: 32px 0 24px 0;
            }}
            .footer {{
                margin-top: 2em;
                font-size: .97em;
                color: var(--muted);
                text-align: right;
            }}
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

    return jsonify({'success': True, 'report_url': f'http://{request.host}/report'}), 200

@app.route('/report', methods=['GET'])
def report():
    return send_file(REPORT_FILE)
