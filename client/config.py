
import os
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")
VIEWER_CMD = os.getenv("RADIANT_CMD", "RadiantViewer")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
