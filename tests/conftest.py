import os
import sys
import tempfile

os.environ["WIKI_ROOT"] = os.path.join(tempfile.gettempdir(), "llmwiki_test_data")
os.environ["SINGLE_USER_ID"] = "local"
os.environ["OLLAMA_URL"] = "http://localhost:11434"
os.environ["LOGFIRE_TOKEN"] = ""
os.environ["SENTRY_DSN"] = ""
os.environ["APP_URL"] = "http://localhost:8000"
os.environ["API_URL"] = "http://localhost:8000"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
