import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv("PG_HOST", "localhost"),
    port=os.getenv("PG_PORT", "5432"),
    dbname=os.getenv("PG_DB", "kap_db"),
    user=os.getenv("PG_USER", "kap_user"),
    password=os.getenv("PG_PASSWORD", "")
)

cur = conn.cursor()
cur.execute("SELECT sentiment, COUNT(*) FROM kap_disclosures GROUP BY sentiment;")
rows = cur.fetchall()
for row in rows:
    print(f"{row[0]}: {row[1]}")

cur.close()
conn.close()
