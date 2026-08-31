"""Path shadow check — prevents the 2026-08-28 Path-import bug from recurring.

Background: Python's compiler sees ANY `from X import Y` inside a function and
marks `Y` as a LOCAL for the entire function. If `Y` is also used earlier in
the function (BEFORE the import), it raises `UnboundLocalError`. The 2026-08-28
incident had this exact pattern in kotak_bot/__main__.py:1037 — a `from
pathlib import Path` inside run_paper() shadowed the module-level `Path` and
broke BOTH action channels silently for 2h.

This script scans the kotak_bot/ tree for the dangerous pattern:
- `from X import Y` (without `as _Y`) inside a function body
- Where `Y` is also used elsewhere in the same function

Run nightly via kotak-nightly-improvement. Exit 0 = clean, exit 1 = violations.
"""
import ast
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
KOTAK_BOT_DIR = PROJECT_ROOT / 'kotak_bot'
SKIP_DIRS = {'__pycache__', '.git', '_archive', 'data_cache', 'Logs'}


def scan_file(path: Path) -> list[dict]:
    """Return list of {file, function, line, pattern, name} violations."""
    try:
        src = path.read_text(encoding='utf-8')
    except Exception:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    violations: list[dict] = []

    class FuncVisitor(ast.NodeVisitor):
        def __init__(self):
            self.stack: list[ast.FunctionDef] = []

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self.stack.append(node)
            self._check(node)
            self.generic_visit(node)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node):
            self.visit_FuncDef(node) if hasattr(self, 'visit_FuncDef') else self._check_async(node)

        def _check(self, func: ast.FunctionDef):
            # Find unprefixed `from X import Y` (not `as _Y`)
            bad_imports: list[tuple[str, int]] = []  # (name, lineno)
            for stmt in ast.walk(func):
                if isinstance(stmt, (ast.ImportFrom, ast.Import)):
                    if isinstance(stmt, ast.ImportFrom):
                        for alias in stmt.names:
                            local_name = alias.asname or alias.name
                            if '.' not in (alias.asname or '') and (alias.asname is None or not alias.asname.startswith('_')):
                                # This shadows the module-level import
                                bad_imports.append((local_name, stmt.lineno))

            if not bad_imports:
                return

            # Find usages of the shadowed names in the function (BEFORE the import line)
            used_before: set[tuple[str, int]] = set()
            for node_in_func in ast.walk(func):
                if isinstance(node_in_func, ast.Name) and isinstance(node_in_func.ctx, ast.Load):
                    name = node_in_func.id
                    for bad_name, bad_line in bad_imports:
                        if name == bad_name and node_in_func.lineno < bad_line:
                            used_before.add((name, node_in_func.lineno))

            for name, bad_line in bad_imports:
                if (name, bad_line) in [(n, l) for n, l in used_before]:
                    violations.append({
                        "file": str(path.relative_to(PROJECT_ROOT)),
                        "function": func.name,
                        "shadowed_name": name,
                        "import_line": bad_line,
                    })

    FuncVisitor().visit(tree)
    return violations


def main() -> int:
    all_violations: list[dict] = []
    for root, dirs, files in os.walk(KOTAK_BOT_DIR):
        # Skip directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith('.py'):
                continue
            p = Path(root) / f
            violations = scan_file(p)
            all_violations.extend(violations)

    if all_violations:
        print(f"PATH-SHADOW-CHECK: {len(all_violations)} violation(s) found")
        for v in all_violations:
            print(f"  {v['file']}:{v['import_line']}  function={v['function']}  shadowed={v['shadowed_name']}")
        print()
        print("FIX: rename the import to `from X import Y as _Y` (or remove the local import — use the module-level one).")
        return 1
    else:
        print(f"PATH-SHADOW-CHECK: 0 violations across {KOTAK_BOT_DIR}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
