
import os

DB_URL = os.getenv("DB_URL", "sqlite:///dicom_index.sqlite3")
DICOM_ROOT = os.getenv("DICOM_ROOT", "./_demo_studies")
CACHE_DIR = os.getenv("CACHE_DIR", "./cache")
INBOX_DIR = os.getenv("INBOX_DIR", "./_inbox_plus")
RADIANT_CMD = os.getenv("RADIANT_CMD", "RadiantViewer")

os.makedirs(CACHE_DIR, exist_ok=True)
