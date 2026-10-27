import pymysql
import config

print("Starting setup...")

conn = pymysql.connect(
    host=config.DB_HOST,
    user=config.DB_USER,
    password=config.DB_PASSWORD
)
cur = conn.cursor()

cur.execute(f"CREATE DATABASE IF NOT EXISTS {config.DB_NAME}")
cur.execute(f"USE {config.DB_NAME}")

cur.execute("DROP TABLE IF EXISTS budgets")
cur.execute("DROP TABLE IF EXISTS expenses")
cur.execute("DROP TABLE IF EXISTS categories")

cur.execute("""
    CREATE TABLE categories (
        category_id INT AUTO_INCREMENT PRIMARY KEY,
        category_name VARCHAR(50) NOT NULL UNIQUE
    )
""")

cur.execute("""
    CREATE TABLE expenses (
        expense_id INT AUTO_INCREMENT PRIMARY KEY,
        expense_date DATE NOT NULL,
        category_id INT NOT NULL,
        amount DECIMAL(10,2) NOT NULL CHECK (amount > 0),
        description VARCHAR(255),
        payment_method VARCHAR(30),
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
    )
""")

cur.execute("""
    CREATE TABLE budgets (
        budget_id INT AUTO_INCREMENT PRIMARY KEY,
        category_id INT NOT NULL,
        budget_month CHAR(7) NOT NULL,
        budget_amount DECIMAL(10,2) NOT NULL CHECK (budget_amount > 0),
        UNIQUE (category_id, budget_month),
        FOREIGN KEY (category_id) REFERENCES categories(category_id)
    )
""")

cur.execute("""
    INSERT INTO categories (category_name) VALUES
    ('Food'), ('Transport'), ('Rent'),
    ('Shopping'), ('Health'), ('Entertainment')
""")

conn.commit()

cur.execute("SELECT COUNT(*) FROM categories")
print("Setup done. Categories:", cur.fetchone()[0])
conn.close()