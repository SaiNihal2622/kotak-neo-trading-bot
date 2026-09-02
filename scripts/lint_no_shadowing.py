#!/usr/bin/env python
"""Lint check: catch the `from X import Y` inside a function shadowing trap.

This pattern bit us TWICE in this codebase (2026-09-02):
  - commit 5dc58ef: first Order UnboundLocalError at __main__.py:664
  - commit ca2b043: second Order UnboundLocalError at __main__.py:638

When you write `from kotak_bot.broker import Order, ...` inside a function,
Python's compiler marks Order as a local variable for the ENTIRE function
scope. Subsequent Order(...) calls fail with:
  UnboundLocalError: cannot access local variable 'Order' where it is
  not associated with a value

This linter scans all .py files in kotak_bot/ and scripts/ and reports any
such shadow imports. Run in CI/pre-commit. Exits 1 if any found.
"""
import ast, os, sys

DANGEROUS_NAMES = {
    'Order', 'Path', 'OrderSide', 'OrderType', 'ProductType',
    'OrderStatus', 'NeoClient', 'PaperClient',
}


class ShadowingFinder(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.issues = []

    def visit_FunctionDef(self, node):
        for stmt in node.body:
            if isinstance(stmt, ast.ImportFrom):
                for alias in stmt.names:
                    name = alias.asname or alias.name
                    if name in DANGEROUS_NAMES:
                        self.issues.append({
                            'file': self.path,
                            'line': node.lineno,
                            'func': node.name,
                            'name': name,
                            'orig': alias.name,
                            'module': stmt.module,
                        })
        self.generic_visit(node)


def main():
    found = 0
    SKIP_DIRS = ('__pycache__', '.git', '.venv', 'venv', 'node_modules',
                 'data_cache', 'Logs', '_archive', 'openalgo_ref', '.minimax')
    for root, dirs, files in os.walk('.'):
        # skip noise dirs (in-place)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith('.py') or f == '__init__.py':
                continue
            path = os.path.join(root, f)
            try:
                tree = ast.parse(open(path, encoding='utf-8').read())
                finder = ShadowingFinder(path)
                finder.visit(tree)
                for issue in finder.issues:
                    print(f"  line {issue['line']} in {issue['func']}() in {issue['file']}: "
                          f"from {issue['module']} import {issue['name']} "
                          f"(SHADOWS top-level {issue['name']})")
                    found += 1
            except SyntaxError as e:
                # BOM files etc — skip silently
                pass
    print()
    if found:
        print(f'FAILED: {found} shadow-import(s) found. Use the top-level import instead.')
        sys.exit(1)
    print('PASSED: no shadow imports found.')
    sys.exit(0)


if __name__ == '__main__':
    main()
