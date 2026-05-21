"""Print registered routes — run: venv\\Scripts\\python.exe scripts\\check_routes.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from main import app  # noqa: E402

print("Loaded app from:", ROOT)
print("login.html exists:", os.path.isfile(os.path.join(ROOT, "static", "login.html")))
print()
for route in app.routes:
    methods = getattr(route, "methods", None) or getattr(route, "methods", set())
    path = getattr(route, "path", None) or ""
    name = getattr(route, "name", "")
    if path and ("login" in path or "signup" in path or "health" in path):
        print(methods, path, name)
