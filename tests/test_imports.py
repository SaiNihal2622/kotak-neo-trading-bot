"""Verify dashboard imports without launching streamlit."""
import sys
from pathlib import Path

LOG = open("dashboard_import.txt", "w", encoding="utf-8")
def o(m): LOG.write(m + "\n"); LOG.flush()

sys.path.insert(0, '.')
try:
    # Dashboard file uses streamlit decorators; we can check syntax + presence of main()
    import ast
    with open("dashboard/app.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    o(f"Dashboard has {len(funcs)} functions: {funcs[:8]}...")
    if "main" in funcs:
        o("Dashboard: main() defined OK")
    else:
        o("Dashboard: no main() — may need launching via `streamlit run`")
except Exception as e:
    o(f"Dashboard check FAIL: {e}")
LOG.close()
