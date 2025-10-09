# scripts/init_db.py
import sys
import os
# ensure project root is on path if running from scripts folder
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from discovery.db import init_db
print("Initializing database schema...")
init_db()
print("Done: schema created/updated.")
