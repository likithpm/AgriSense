# create_db.py

import sqlite3

conn = sqlite3.connect("agrisense.db")

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS crops(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crop_name TEXT,
    season TEXT,
    category TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS fertilizers(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crop_name TEXT,
    fertilizer_name TEXT
)
""")



print("Database Created")

cursor.execute("""
INSERT INTO crops
(crop_name, season, category)

VALUES

('Rice','Kharif','Cereal'),
('Maize','Kharif','Cereal'),
('Groundnut','Kharif','Oilseed'),
('Cotton','Kharif','Cash Crop')
""")

cursor.execute("""
INSERT INTO fertilizers
(crop_name,fertilizer_name)

VALUES

('Rice','Urea'),
('Rice','DAP'),
('Cotton','NPK 20-20-20'),
('Groundnut','Gypsum')
""")
conn.commit()

conn.close()