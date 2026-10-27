import re
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, flash
import pymysql
import config

income_bp = Blueprint("income", __name__)


def get_db():
    return pymysql.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME
    )


def ensure_income_table():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS income (
            income_id INT AUTO_INCREMENT PRIMARY KEY,
            income_date DATE NOT NULL,
            source VARCHAR(100) NOT NULL,
            amount DECIMAL(10,2) NOT NULL CHECK (amount > 0)
        )
    """)
    conn.commit()
    conn.close()


ensure_income_table()


def valid_month(month):
    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        return False
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        return False
    return True


@income_bp.route("/income")
def income():
    month = request.args.get("month") or datetime.now().strftime("%Y-%m")
    if not valid_month(month):
        flash("Please choose a valid month.")
        return redirect("/income")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT income_id, income_date, source, amount FROM income "
        "WHERE DATE_FORMAT(income_date, '%%Y-%%m') = %s "
        "ORDER BY income_date DESC, income_id DESC",
        (month,)
    )
    rows = cur.fetchall()
    cur.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM expenses "
        "WHERE DATE_FORMAT(expense_date, '%%Y-%%m') = %s",
        (month,)
    )
    spent = float(cur.fetchone()[0])
    conn.close()

    earned = sum(float(r[3]) for r in rows)
    savings = earned - spent
    rate = f"{savings / earned * 100:.1f}%" if earned > 0 else "n/a"
    summary = {
        "earned": f"{earned:.2f}",
        "spent": f"{spent:.2f}",
        "savings": f"{savings:.2f}",
        "rate": rate,
        "negative": savings < 0,
    }
    return render_template("income.html", month=month, rows=rows, summary=summary)


@income_bp.route("/add_income", methods=["POST"])
def add_income():
    income_date = request.form.get("income_date", "")
    source = request.form.get("source", "").strip()
    try:
        amount = float(request.form.get("amount", ""))
    except ValueError:
        amount = 0

    if not income_date:
        flash("Please choose a date.")
        return redirect("/income")
    if not source or len(source) > 100:
        flash("Source must be 1 to 100 characters.")
        return redirect("/income")
    if amount <= 0:
        flash("Income must be a positive number.")
        return redirect("/income")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO income (income_date, source, amount) VALUES (%s, %s, %s)",
        (income_date, source, amount)
    )
    conn.commit()
    conn.close()
    flash("Income added.")
    return redirect(f"/income?month={income_date[:7]}")


@income_bp.route("/delete_income/<int:income_id>", methods=["POST"])
def delete_income(income_id):
    month = request.form.get("month", "")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM income WHERE income_id=%s", (income_id,))
    conn.commit()
    conn.close()
    flash("Income removed.")
    return redirect(f"/income?month={month}" if valid_month(month) else "/income")