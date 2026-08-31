# database.py

import sqlite3

conn = sqlite3.connect("agrisense.db")

cursor = conn.cursor()

cursor.execute(
    "SELECT * FROM crops"
)

rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()