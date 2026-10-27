# Personal Expense Tracking and Analysis System

A Flask web application that records personal expenses in MySQL and
analyses them with Pandas, NumPy and Matplotlib.

## Features
- Add, edit, delete and list expenses
- Add your own categories (duplicates are rejected)
- Search expenses by description or category
- Report page with date-range and category filters
- Summary statistics: total, count, average, median, largest expense,
  highest-spending category and month
- Monthly totals and category-wise shares
- Pie chart (category share) and bar chart (monthly spending)
- Monthly budgets per category with "Near limit" and "Over budget" warnings
- Income tracking with monthly savings and savings rate
- Download expenses as a CSV file

## Technologies
Python, Flask, MySQL, PyMySQL, Pandas, NumPy, Matplotlib, HTML/CSS

## Project structure
```
app.py            Main Flask app: expenses, categories, budgets, report
income.py         Income and savings routes (Flask blueprint)
export.py         CSV download route (Flask blueprint)
config.py         Database settings
setup_db.py       Creates the database, tables and starting categories
requirements.txt  Python packages needed
templates/        HTML pages (base, index, edit, report, budgets, income)
static/charts/    Chart images created by the report page
```

## Setup
1. Install Python and MySQL, and make sure MySQL is running.
2. Open the project folder in VS Code.
3. Install the packages:
   ```
   py -m pip install -r requirements.txt
   ```
4. Open `config.py` and set `DB_PASSWORD` to your MySQL password.
5. Create the database and tables (this resets existing data):
   ```
   py setup_db.py
   ```
6. Start the website:
   ```
   py app.py
   ```
7. Open http://127.0.0.1:5000 in a browser.

The budgets and income tables are created automatically when the app starts.

## Database design
- `categories(category_id, category_name)`
- `expenses(expense_id, expense_date, category_id, amount, description, payment_method)`
- `budgets(budget_id, category_id, budget_month, budget_amount)`
- `income(income_id, income_date, source, amount)`
- `expenses.category_id` and `budgets.category_id` are foreign keys
  to `categories.category_id`.
- Amounts must be greater than 0, and each category can have only one
  budget per month.

## Validation and safety
- Amounts, budgets and income must be positive numbers.
- Category names cannot be empty or duplicated.
- The "From" date must not be after the "To" date in report filters.
- All SQL uses parameterised queries.
- CSV export neutralises cells that start with =, +, - or @.

## Notes
This is a single-user learning project that uses fictional or
voluntarily entered data. It is not a banking or financial-advice system.
Do not share `config.py` publicly if it contains your real password.