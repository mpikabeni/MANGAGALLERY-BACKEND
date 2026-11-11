"""WSGI compatibility entry point. The canonical application lives in main.py."""
from main import app

__all__ = ["app"]

@app.route("/")
def home():
  return {"status": "online", "message": "MangaGallery Backend is running!"}
