import os
import sys

os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5434/llmwiki_test"
os.environ["SINGLE_USER_ID"] = "00000000-0000-0000-0000-000000000001"
os.environ["STORAGE_ROOT"] = "./data/test_files/"
os.environ["OLLAMA_URL"] = "http://localhost:11434"
os.environ["LOGFIRE_TOKEN"] = ""
os.environ["SENTRY_DSN"] = ""
os.environ["APP_URL"] = "http://localhost:8000"
os.environ["API_URL"] = "http://localhost:8000"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
