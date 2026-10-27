import os
import re
import time
from datetime import datetime
from flask import Flask, render_template, request, redirect, flash
import pymysql
import pandas as pd
import numpy as np
from matplotlib.figure import Figure
import config
from income import income_bp
from export import export_bp

app = Flask(__name__)
app.secret_key = "expense-tracker-secret"
app.register_blueprint(income_bp)
app.register_blueprint(export_bp)

PAYMENTS = ["Cash", "Card", "UPI"]
CHART_DIR = os.path.join(app.static_folder, "charts")
os.makedirs(CHART_DIR, exist_ok=True)


def get_db():
    return pymysql.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME
    )


def ensure_budget_table():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            budget_id INT AUTO_INCREMENT PRIMARY KEY,
            category_id INT NOT NULL,
            budget_month CHAR(7) NOT NULL,
            budget_amount DECIMAL(10,2) NOT NULL CHECK (budget_amount > 0),
            UNIQUE (category_id, budget_month),
            FOREIGN KEY (category_id) REFERENCES categories(category_id)
        )
    """)
    conn.commit()
    conn.close()


ensure_budget_table()


def read_amount():
    try:
        amount = float(request.form["amount"])
    except ValueError:
        return None
    return amount if amount > 0 else None


def valid_month(month):
    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        return False
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        return False
    return True


def get_categories():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT category_id, category_name FROM categories ORDER BY category_name")
    rows = cur.fetchall()
    conn.close()
    return rows


def budget_rows(month):
    sql = """
        SELECT b.budget_id, c.category_name, b.budget_amount,
               COALESCE(SUM(e.amount), 0) AS spent
        FROM budgets b
        JOIN categories c ON b.category_id = c.category_id
        LEFT JOIN expenses e
               ON e.category_id = b.category_id
              AND DATE_FORMAT(e.expense_date, '%%Y-%%m') = b.budget_month
        WHERE b.budget_month = %s
        GROUP BY b.budget_id, c.category_name, b.budget_amount
        ORDER BY c.category_name
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, (month,))
    rows = cur.fetchall()
    conn.close()

    result = []
    for bid, name, budget, spent in rows:
        budget = float(budget)
        spent = float(spent)
        pct = spent / budget * 100
        if pct > 100:
            status = "Over budget"
        elif pct >= 80:
            status = "Near limit"
        else:
            status = "OK"
        item = {
            "id": bid,
            "name": name,
            "budget": f"{budget:.2f}",
            "spent": f"{spent:.2f}",
            "remaining": f"{budget - spent:.2f}",
            "pct": f"{pct:.0f}",
            "status": status,
        }
        result.append(item)
    return result


def get_df(start, end, category):
    sql = ("SELECT e.expense_date, c.category_name, e.amount "
           "FROM expenses e JOIN categories c ON e.category_id = c.category_id "
           "WHERE 1=1")
    params = []
    if start:
        sql += " AND e.expense_date >= %s"
        params.append(start)
    if end:
        sql += " AND e.expense_date <= %s"
        params.append(end)
    if category:
        sql += " AND e.category_id = %s"
        params.append(category)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=["expense_date", "category_name", "amount"])
    if not df.empty:
        df["amount"] = df["amount"].astype(float)
        df["month"] = pd.to_datetime(df["expense_date"]).dt.strftime("%Y-%m")
    return df


def make_charts(cat, monthly):
    fig = Figure(figsize=(6, 5))
    ax = fig.subplots()
    ax.pie(cat.values, autopct="%1.1f%%")
    ax.legend(cat.index, title="Category", loc="center left", bbox_to_anchor=(1, 0.5))
    ax.set_title("Spending by Category (share of total)")
    fig.savefig(os.path.join(CHART_DIR, "pie.png"), bbox_inches="tight")

    fig = Figure(figsize=(6, 5))
    ax = fig.subplots()
    ax.bar(monthly.index, monthly.values, label="Total spent")
    ax.set_title("Monthly Spending")
    ax.set_xlabel("Month")
    ax.set_ylabel("Amount (INR)")
    ax.tick_params(axis="x", rotation=45)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "bar.png"))


@app.route("/")
def home():
    q = request.args.get("q", "").strip()

    sql = """
        SELECT e.expense_id, e.expense_date, c.category_name,
               e.amount, e.description, e.payment_method
        FROM expenses e
        JOIN categories c ON e.category_id = c.category_id
    """
    params = []
    if q:
        sql += " WHERE e.description LIKE %s OR c.category_name LIKE %s"
        like = f"%{q}%"
        params = [like, like]
    sql += " ORDER BY e.expense_date DESC, e.expense_id DESC"

    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    expenses = cur.fetchall()
    conn.close()

    this_month = datetime.now().strftime("%Y-%m")
    warnings = [r for r in budget_rows(this_month) if r["status"] != "OK"]

    return render_template("index.html", categories=get_categories(),
                           expenses=expenses, payments=PAYMENTS, q=q,
                           warnings=warnings, this_month=this_month)


@app.route("/add_category", methods=["POST"])
def add_category():
    name = request.form.get("category_name", "").strip()
    if not name:
        flash("Category name cannot be empty.")
        return redirect("/")
    if len(name) > 50:
        flash("Category name must be 50 characters or fewer.")
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO categories (category_name) VALUES (%s)", (name,))
        conn.commit()
        flash(f"Category '{name}' added.")
    except pymysql.err.IntegrityError:
        flash("That category already exists.")
    finally:
        conn.close()
    return redirect("/")


@app.route("/add", methods=["POST"])
def add():
    amount = read_amount()
    if amount is None:
        flash("Amount must be a positive number.")
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO expenses (expense_date, category_id, amount, description, payment_method) "
        "VALUES (%s, %s, %s, %s, %s)",
        (request.form["expense_date"], request.form["category_id"], amount,
         request.form["description"], request.form["payment_method"])
    )
    conn.commit()
    conn.close()
    flash("Expense added.")
    return redirect("/")


@app.route("/edit/<int:expense_id>", methods=["GET", "POST"])
def edit(expense_id):
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        amount = read_amount()
        if amount is None:
            conn.close()
            flash("Amount must be a positive number.")
            return redirect(f"/edit/{expense_id}")
        cur.execute(
            "UPDATE expenses SET expense_date=%s, category_id=%s, amount=%s, "
            "description=%s, payment_method=%s WHERE expense_id=%s",
            (request.form["expense_date"], request.form["category_id"], amount,
             request.form["description"], request.form["payment_method"], expense_id)
        )
        conn.commit()
        conn.close()
        flash("Expense updated.")
        return redirect("/")

    cur.execute(
        "SELECT expense_id, expense_date, category_id, amount, description, payment_method "
        "FROM expenses WHERE expense_id=%s", (expense_id,)
    )
    e = cur.fetchone()
    conn.close()
    if e is None:
        flash("Expense not found.")
        return redirect("/")
    return render_template("edit.html", e=e, categories=get_categories(), payments=PAYMENTS)


@app.route("/delete/<int:expense_id>", methods=["POST"])
def delete(expense_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM expenses WHERE expense_id=%s", (expense_id,))
    conn.commit()
    conn.close()
    flash("Expense deleted.")
    return redirect("/")


@app.route("/budgets")
def budgets():
    month = request.args.get("month") or datetime.now().strftime("%Y-%m")
    if not valid_month(month):
        flash("Please choose a valid month.")
        return redirect("/budgets")
    return render_template("budgets.html", month=month,
                           categories=get_categories(), rows=budget_rows(month))


@app.route("/set_budget", methods=["POST"])
def set_budget():
    month = request.form.get("budget_month", "")
    if not valid_month(month):
        flash("Please choose a valid month.")
        return redirect("/budgets")
    try:
        amount = float(request.form["amount"])
    except ValueError:
        amount = 0
    if amount <= 0:
        flash("Budget must be a positive number.")
        return redirect(f"/budgets?month={month}")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO budgets (category_id, budget_month, budget_amount) "
        "VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE budget_amount = VALUES(budget_amount)",
        (request.form["category_id"], month, amount)
    )
    conn.commit()
    conn.close()
    flash("Budget saved.")
    return redirect(f"/budgets?month={month}")


@app.route("/delete_budget/<int:budget_id>", methods=["POST"])
def delete_budget(budget_id):
    month = request.form.get("month", "")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM budgets WHERE budget_id=%s", (budget_id,))
    conn.commit()
    conn.close()
    flash("Budget removed.")
    return redirect(f"/budgets?month={month}" if valid_month(month) else "/budgets")


@app.route("/report")
def report():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    category = request.args.get("category", "")

    if start and end and start > end:
        flash("The 'From' date must be before the 'To' date.")
        return redirect("/report")

    ctx = dict(categories=get_categories(), start=start, end=end, category=category)
    df = get_df(start, end, category)
    if df.empty:
        return render_template("report.html", empty=True, **ctx)

    amounts = df["amount"].to_numpy()
    monthly = df.groupby("month")["amount"].sum()
    cat = df.groupby("category_name")["amount"].sum().sort_values(ascending=False)
    share = cat / cat.sum() * 100

    make_charts(cat, monthly)

    stats = dict(
        total=f"{np.sum(amounts):.2f}",
        count=len(amounts),
        average=f"{np.mean(amounts):.2f}",
        median=f"{np.median(amounts):.2f}",
        largest=f"{np.max(amounts):.2f}",
        top_category=cat.index[0],
        top_month=monthly.idxmax(),
    )
    monthly_rows = [(m, f"{v:.2f}") for m, v in monthly.items()]
    cat_rows = [(n, f"{cat[n]:.2f}", f"{share[n]:.1f}") for n in cat.index]

    return render_template(
        "report.html",
        empty=False,
        stats=stats,
        stamp=int(time.time()),
        monthly=monthly_rows,
        cats=cat_rows,
        **ctx
    )


if __name__ == "__main__":
    app.run(debug=True)