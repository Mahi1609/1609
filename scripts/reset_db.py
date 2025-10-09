# scripts/reset_db.py
"""
WARNING: destructive. Drops all tables and recreates them. Use in dev only.
"""
import sys, os
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from discovery.db import engine
from sqlmodel import SQLModel
from discovery import models  # ensure models loaded

confirm = input("This will DROP ALL TABLES in the configured DB (dev). Type 'YES' to continue: ")
if confirm != "YES":
    print("Aborting.")
    raise SystemExit(1)

print("Dropping all tables...")
SQLModel.metadata.drop_all(engine)
print("Recreating tables...")
SQLModel.metadata.create_all(engine)
print("Reset complete.")
