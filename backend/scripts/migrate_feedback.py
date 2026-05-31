"""
Migration: Add 'feedback' column to 'messages' table.
Run this script once after updating the code:
    docker exec bim-backend python scripts/migrate_feedback.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from src.database.session import engine

def migrate():
    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'messages' AND column_name = 'feedback'
        """))
        if result.fetchone():
            print("✅ Column 'feedback' already exists. Skipping.")
            return

        # Add column
        conn.execute(text(
            "ALTER TABLE messages ADD COLUMN feedback VARCHAR(10)"
        ))
        conn.commit()
        print("✅ Added 'feedback' column to 'messages' table.")


if __name__ == "__main__":
    migrate()
