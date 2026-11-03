import os
import re
import time
from datetime import datetime
from functools import wraps

import pymysql
import pandas as pd
import numpy as np

from flask import (
    Flask, render_template, request, redirect,
    flash, session, url_for
)
from werkzeug.security import generate_password_hash, check_password_hash
from matplotlib.figure import Figure

import config
from income import income_bp
from export import export_bp


# ==========================================
# APP CONFIGURATION
# ==========================================

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "spendsmart-local-development-key"
)

app.register_blueprint(income_bp)
app.register_blueprint(export_bp)

PAYMENTS = ["Cash", "Card", "UPI"]

CHART_DIR = os.path.join(app.static_folder, "charts")
os.makedirs(CHART_DIR, exist_ok=True)


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_db():
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME
    )


# ==========================================
# LOGIN PROTECTION
# ==========================================

def login_required(view_function):
    @wraps(view_function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            flash("Please log in to continue.")
            return redirect(url_for("login"))

        return view_function(*args, **kwargs)

    return wrapper


@app.before_request
def require_login():

    allowed_endpoints = [
        "login",
        "signup",
        "static"
    ]

    if request.endpoint in allowed_endpoints:
        return None

    if "user_id" not in session:
        return redirect(url_for("login"))


# ==========================================
# DATABASE TABLE SETUP
# ==========================================

def ensure_budget_table():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            budget_id INT AUTO_INCREMENT PRIMARY KEY,
            category_id INT NOT NULL,
            budget_month CHAR(7) NOT NULL,
            budget_amount DECIMAL(10,2) NOT NULL,
            user_id INT NULL,
            UNIQUE (category_id, budget_month),
            FOREIGN KEY (category_id)
                REFERENCES categories(category_id)
        )
    """)

    conn.commit()
    conn.close()


ensure_budget_table()


# ==========================================
# COMMON FUNCTIONS
# ==========================================

def read_amount():

    try:
        amount = float(request.form["amount"])
    except (ValueError, TypeError, KeyError):
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


def current_user_id():
    return session["user_id"]


def get_categories():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT category_id, category_name
        FROM categories
        WHERE user_id = %s
        ORDER BY category_name
    """, (current_user_id(),))

    rows = cur.fetchall()
    conn.close()

    return rows


def category_belongs_to_user(category_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT category_id
        FROM categories
        WHERE category_id = %s AND user_id = %s
    """, (category_id, current_user_id()))

    row = cur.fetchone()
    conn.close()

    return row is not None


# ==========================================
# BUDGET FUNCTIONS
# ==========================================

def budget_rows(month):

    sql = """
        SELECT b.budget_id, c.category_name, b.budget_amount,
               COALESCE(SUM(e.amount), 0) AS spent
        FROM budgets b
        JOIN categories c
            ON b.category_id = c.category_id
        LEFT JOIN expenses e
            ON e.category_id = b.category_id
            AND e.user_id = b.user_id
            AND DATE_FORMAT(e.expense_date, '%%Y-%%m') = b.budget_month
        WHERE b.budget_month = %s
          AND b.user_id = %s
          AND c.user_id = %s
        GROUP BY b.budget_id, c.category_name, b.budget_amount
        ORDER BY c.category_name
    """

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        sql,
        (month, current_user_id(), current_user_id())
    )

    rows = cur.fetchall()
    conn.close()

    result = []

    for bid, name, budget, spent in rows:

        budget = float(budget)
        spent = float(spent)

        pct = spent / budget * 100 if budget > 0 else 0

        if pct > 100:
            status = "Over budget"
        elif pct >= 80:
            status = "Near limit"
        else:
            status = "OK"

        result.append({
            "id": bid,
            "name": name,
            "budget": f"{budget:.2f}",
            "spent": f"{spent:.2f}",
            "remaining": f"{budget - spent:.2f}",
            "pct": f"{pct:.0f}",
            "status": status
        })

    return result


# ==========================================
# ANALYTICS DATA
# ==========================================

def get_df(start, end, category):

    sql = """
        SELECT e.expense_date, c.category_name, e.amount
        FROM expenses e
        JOIN categories c
            ON e.category_id = c.category_id
        WHERE e.user_id = %s
          AND c.user_id = %s
    """

    params = [current_user_id(), current_user_id()]

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

    df = pd.DataFrame(
        rows,
        columns=["expense_date", "category_name", "amount"]
    )

    if not df.empty:

        df["amount"] = df["amount"].astype(float)

        df["month"] = pd.to_datetime(
            df["expense_date"]
        ).dt.strftime("%Y-%m")

    return df


# ==========================================
# CHARTS
# ==========================================

def make_charts(cat, monthly):

    fig = Figure(figsize=(6, 5))
    ax = fig.subplots()

    ax.pie(cat.values, autopct="%1.1f%%")

    ax.legend(
        cat.index,
        title="Category",
        loc="center left",
        bbox_to_anchor=(1, 0.5)
    )

    ax.set_title("Spending by Category (share of total)")

    fig.savefig(
        os.path.join(CHART_DIR, "pie.png"),
        bbox_inches="tight"
    )

    fig = Figure(figsize=(6, 5))
    ax = fig.subplots()

    ax.bar(
        monthly.index,
        monthly.values,
        label="Total spent"
    )

    ax.set_title("Monthly Spending")
    ax.set_xlabel("Month")
    ax.set_ylabel("Amount (INR)")

    ax.tick_params(axis="x", rotation=45)
    ax.legend()

    fig.tight_layout()

    fig.savefig(
        os.path.join(CHART_DIR, "bar.png")
    )


# ==========================================
# SIGNUP
# ==========================================

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if "user_id" in session:
        return redirect("/")

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash("Please fill in all fields.")
            return redirect("/signup")

        if len(username) > 50:
            flash("Username must be 50 characters or fewer.")
            return redirect("/signup")

        if len(email) > 100:
            flash("Email must be 100 characters or fewer.")
            return redirect("/signup")

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Please enter a valid email address.")
            return redirect("/signup")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return redirect("/signup")

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect("/signup")

        password_hash = generate_password_hash(password)

        conn = get_db()
        cur = conn.cursor()

        try:

            cur.execute("SELECT COUNT(*) FROM users")
            is_first_user = cur.fetchone()[0] == 0

            cur.execute("""
                INSERT INTO users (username, email, password_hash)
                VALUES (%s, %s, %s)
            """, (username, email, password_hash))

            new_user_id = cur.lastrowid

            # Give the first registered user ownership
            # of the existing records in the database.
            if is_first_user:

                cur.execute("""
                    UPDATE categories
                    SET user_id = %s
                    WHERE user_id IS NULL
                """, (new_user_id,))

                cur.execute("""
                    UPDATE expenses
                    SET user_id = %s
                    WHERE user_id IS NULL
                """, (new_user_id,))

                cur.execute("""
                    UPDATE income
                    SET user_id = %s
                    WHERE user_id IS NULL
                """, (new_user_id,))

                cur.execute("""
                    UPDATE budgets
                    SET user_id = %s
                    WHERE user_id IS NULL
                """, (new_user_id,))

            conn.commit()

            flash("Account created successfully. Please log in.")
            return redirect("/login")

        except pymysql.err.IntegrityError:

            conn.rollback()
            flash("Username or email already exists.")
            return redirect("/signup")

        except Exception:

            conn.rollback()
            raise

        finally:
            conn.close()

    return render_template("signup.html")


# ==========================================
# LOGIN
# ==========================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if "user_id" in session:
        return redirect("/")

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT user_id, username, password_hash
            FROM users
            WHERE email = %s
        """, (email,))

        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):

            session.clear()
            session["user_id"] = user[0]
            session["username"] = user[1]

            flash("Login successful!")
            return redirect("/")

        flash("Invalid email or password.")
        return redirect("/login")

    return render_template("login.html")


# ==========================================
# LOGOUT
# ==========================================

@app.route("/logout")
def logout():

    session.clear()

    flash("You have been logged out.")

    return redirect("/login")


# ==========================================
# DASHBOARD
# ==========================================

@app.route("/")
def home():

    q = request.args.get("q", "").strip()
    user_id = current_user_id()

    sql = """
        SELECT e.expense_id, e.expense_date, c.category_name,
               e.amount, e.description, e.payment_method
        FROM expenses e
        JOIN categories c ON e.category_id = c.category_id
        WHERE e.user_id = %s
          AND c.user_id = %s
    """

    params = [user_id, user_id]

    if q:
        sql += """
            AND (
                e.description LIKE %s
                OR c.category_name LIKE %s
            )
        """
        like = f"%{q}%"
        params.extend([like, like])

    sql += " ORDER BY e.expense_date DESC, e.expense_id DESC"

    conn = get_db()
    cur = conn.cursor()

    cur.execute(sql, params)
    expenses = cur.fetchall()

    cur.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM income
        WHERE user_id = %s
    """, (user_id,))

    total_income = float(cur.fetchone()[0])

    cur.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE user_id = %s
    """, (user_id,))

    total_expenses = float(cur.fetchone()[0])

    cur.execute("""
        SELECT DATE_FORMAT(income_date, '%%Y-%%m'), SUM(amount)
        FROM income
        WHERE user_id = %s
          AND income_date >= DATE_SUB(CURDATE(), INTERVAL 5 MONTH)
        GROUP BY DATE_FORMAT(income_date, '%%Y-%%m')
        ORDER BY DATE_FORMAT(income_date, '%%Y-%%m')
    """, (user_id,))

    monthly_income = cur.fetchall()

    cur.execute("""
        SELECT DATE_FORMAT(expense_date, '%%Y-%%m'), SUM(amount)
        FROM expenses
        WHERE user_id = %s
          AND expense_date >= DATE_SUB(CURDATE(), INTERVAL 5 MONTH)
        GROUP BY DATE_FORMAT(expense_date, '%%Y-%%m')
        ORDER BY DATE_FORMAT(expense_date, '%%Y-%%m')
    """, (user_id,))

    monthly_expenses = cur.fetchall()

    cur.execute("""
        SELECT c.category_name, SUM(e.amount)
        FROM expenses e
        JOIN categories c ON e.category_id = c.category_id
        WHERE e.user_id = %s
          AND c.user_id = %s
        GROUP BY c.category_name
        ORDER BY SUM(e.amount) DESC
    """, (user_id, user_id))

    category_data = cur.fetchall()

    conn.close()

    monthly_income = [
        [str(month), float(amount or 0)]
        for month, amount in monthly_income
    ]

    monthly_expenses = [
        [str(month), float(amount or 0)]
        for month, amount in monthly_expenses
    ]

    category_data = [
        [str(category), float(amount or 0)]
        for category, amount in category_data
    ]

    balance = total_income - total_expenses

    savings_rate = (
        (balance / total_income) * 100
        if total_income > 0 else 0
    )

    summary = {
        "income": total_income,
        "expenses": total_expenses,
        "balance": balance,
        "savings_rate": savings_rate
    }

    this_month = datetime.now().strftime("%Y-%m")

    warnings = [
        row for row in budget_rows(this_month)
        if row["status"] != "OK"
    ]

    return render_template(
        "index.html",
        categories=get_categories(),
        expenses=expenses,
        payments=PAYMENTS,
        q=q,
        warnings=warnings,
        this_month=this_month,
        summary=summary,
        monthly_income=monthly_income,
        monthly_expenses=monthly_expenses,
        category_data=category_data
    )


# ==========================================
# ADD CATEGORY
# ==========================================

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

        cur.execute("""
            INSERT INTO categories (category_name, user_id)
            VALUES (%s, %s)
        """, (name, current_user_id()))

        conn.commit()
        flash(f"Category '{name}' added.")

    except pymysql.err.IntegrityError:

        conn.rollback()
        flash("That category already exists.")

    finally:
        conn.close()

    return redirect("/")


# ==========================================
# ADD EXPENSE
# ==========================================

@app.route("/add", methods=["POST"])
def add():

    amount = read_amount()

    if amount is None:
        flash("Amount must be a positive number.")
        return redirect("/")

    category_id = request.form.get("category_id")

    if not category_id or not category_belongs_to_user(category_id):
        flash("Please select a valid category.")
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO expenses
        (expense_date, category_id, amount, description,
         payment_method, user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        request.form["expense_date"],
        category_id,
        amount,
        request.form.get("description", ""),
        request.form.get("payment_method", "Cash"),
        current_user_id()
    ))

    conn.commit()
    conn.close()

    flash("Expense added.")

    return redirect("/")


# ==========================================
# EDIT EXPENSE
# ==========================================

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

        category_id = request.form.get("category_id")

        if not category_id or not category_belongs_to_user(category_id):
            conn.close()
            flash("Please select a valid category.")
            return redirect(f"/edit/{expense_id}")

        cur.execute("""
            UPDATE expenses
            SET expense_date = %s,
                category_id = %s,
                amount = %s,
                description = %s,
                payment_method = %s
            WHERE expense_id = %s
              AND user_id = %s
        """, (
            request.form["expense_date"],
            category_id,
            amount,
            request.form.get("description", ""),
            request.form.get("payment_method", "Cash"),
            expense_id,
            current_user_id()
        ))

        conn.commit()
        conn.close()

        flash("Expense updated.")

        return redirect("/")

    cur.execute("""
        SELECT expense_id, expense_date, category_id,
               amount, description, payment_method
        FROM expenses
        WHERE expense_id = %s AND user_id = %s
    """, (expense_id, current_user_id()))

    e = cur.fetchone()

    conn.close()

    if e is None:
        flash("Expense not found.")
        return redirect("/")

    return render_template(
        "edit.html",
        e=e,
        categories=get_categories(),
        payments=PAYMENTS
    )


# ==========================================
# DELETE EXPENSE
# ==========================================

@app.route("/delete/<int:expense_id>", methods=["POST"])
def delete(expense_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM expenses
        WHERE expense_id = %s AND user_id = %s
    """, (expense_id, current_user_id()))

    conn.commit()
    conn.close()

    flash("Expense deleted.")

    return redirect("/")


# ==========================================
# BUDGETS
# ==========================================

@app.route("/budgets")
def budgets():

    month = request.args.get("month") or datetime.now().strftime("%Y-%m")

    if not valid_month(month):
        flash("Please choose a valid month.")
        return redirect("/budgets")

    return render_template(
        "budgets.html",
        month=month,
        categories=get_categories(),
        rows=budget_rows(month)
    )


@app.route("/set_budget", methods=["POST"])
def set_budget():

    month = request.form.get("budget_month", "")

    if not valid_month(month):
        flash("Please choose a valid month.")
        return redirect("/budgets")

    try:
        amount = float(request.form["amount"])
    except (ValueError, TypeError, KeyError):
        amount = 0

    if amount <= 0:
        flash("Budget must be a positive number.")
        return redirect(f"/budgets?month={month}")

    category_id = request.form.get("category_id")

    if not category_id or not category_belongs_to_user(category_id):
        flash("Please select a valid category.")
        return redirect(f"/budgets?month={month}")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO budgets
        (category_id, budget_month, budget_amount, user_id)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        budget_amount = VALUES(budget_amount),
        user_id = VALUES(user_id)
    """, (
        category_id,
        month,
        amount,
        current_user_id()
    ))

    conn.commit()
    conn.close()

    flash("Budget saved.")

    return redirect(f"/budgets?month={month}")


@app.route("/delete_budget/<int:budget_id>", methods=["POST"])
def delete_budget(budget_id):

    month = request.form.get("month", "")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM budgets
        WHERE budget_id = %s AND user_id = %s
    """, (budget_id, current_user_id()))

    conn.commit()
    conn.close()

    flash("Budget removed.")

    return redirect(
        f"/budgets?month={month}"
        if valid_month(month)
        else "/budgets"
    )


# ==========================================
# ANALYTICS REPORT
# ==========================================

@app.route("/report")
def report():

    start = request.args.get("start", "")
    end = request.args.get("end", "")
    category = request.args.get("category", "")

    if start and end and start > end:
        flash("The 'From' date must be before the 'To' date.")
        return redirect("/report")

    if category and not category_belongs_to_user(category):
        flash("Please choose a valid category.")
        return redirect("/report")

    ctx = dict(
        categories=get_categories(),
        start=start,
        end=end,
        category=category
    )

    df = get_df(start, end, category)

    if df.empty:
        return render_template(
            "report.html",
            empty=True,
            **ctx
        )

    amounts = df["amount"].to_numpy()

    monthly = df.groupby("month")["amount"].sum()

    cat = (
        df.groupby("category_name")["amount"]
        .sum()
        .sort_values(ascending=False)
    )

    share = cat / cat.sum() * 100

    make_charts(cat, monthly)

    stats = {
        "total": f"{np.sum(amounts):.2f}",
        "count": len(amounts),
        "average": f"{np.mean(amounts):.2f}",
        "median": f"{np.median(amounts):.2f}",
        "largest": f"{np.max(amounts):.2f}",
        "top_category": cat.index[0],
        "top_month": monthly.idxmax()
    }

    monthly_rows = [
        (month, f"{value:.2f}")
        for month, value in monthly.items()
    ]

    cat_rows = [
        (name, f"{cat[name]:.2f}", f"{share[name]:.1f}")
        for name in cat.index
    ]

    return render_template(
        "report.html",
        empty=False,
        stats=stats,
        stamp=int(time.time()),
        monthly=monthly_rows,
        cats=cat_rows,
        **ctx
    )


# ==========================================
# RUN APPLICATION
# ==========================================

if __name__ == "__main__":
    app.run(debug=True)