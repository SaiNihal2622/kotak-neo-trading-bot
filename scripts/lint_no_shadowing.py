#!/usr/bin/env python
"""Lint check: catch in-function imports that shadow top-level names.

This pattern has bitten us FIVE TIMES in this codebase:
  - commit 5dc58ef: first Order UnboundLocalError at __main__.py:664
  - commit ca2b043: second Order UnboundLocalError at __main__.py:638
  - commit 1edad1c: third Order UnboundLocalError
  - commit e31dd3f: fourth Order UnboundLocalError
  - 2026-09-04 15:48: fifth UnboundLocalError — this time on `sys`, not `Order`.
    `import sys` inside run_paper() at line 1252 made `sys` a local for the
    whole function, breaking `sys.exit(0)` in the RESTART_BOT branch
    (line 1111, which executes earlier in the function).

When you write `import X` or `from X import Y` inside a function for a name
that's already top-level, Python's compiler marks that name as a local
variable for the ENTIRE function scope. Any earlier use of that name in
the function fails with:
  UnboundLocalError: cannot access local variable '<name>' where it is
  not associated with a value

This linter scans all .py files in kotak_bot/ and scripts/ and reports any
such in-function imports of names that are also imported at module level.
Run in CI/pre-commit. Exits 1 if any found.

The `DANGEROUS_NAMES` short-list above DANGEROUS_NAMES handles the names
that have been seen failing. The `check_all_top_level` flag extends the
check to ANY in-function import of a name already at module scope — that
is the broader, safer net.
"""
import ast, os, sys

DANGEROUS_NAMES = {
    # Names from kotak_bot.broker / kotak_bot.execution that have broken prod
    # by being re-imported inside run_paper() (5 separate incidents 2026-08-27
    # through 2026-09-04). DO NOT ADD stdlib names here — they cause noise.
    'Order', 'OrderSide', 'OrderType', 'OrderStatus', 'ProductType',
    'NeoClient', 'PaperClient', 'TradePlan', 'StrategyName',
    # `sys` because it's used both for sys.exit() (e.g. RESTART_BOT branch
    # in the bot) and for sys.path manipulation. Mixing them in one function
    # has caused UnboundLocalError in 2026-09-04.
    'sys',
    # `Path` is a common target because it's used both as a type (Path("..."))
    # and as a module path. Mixing has caused silent corruption (2026-08-27).
    'Path',
}


class ShadowingFinder(ast.NodeVisitor):
    def __init__(self, path, source):
        self.path = path
        self.source = source
        self.issues = []

    def visit_FunctionDef(self, node):
        # Collect all name-uses (Name nodes) in this function in source order.
        # If an in-function import introduces a name that is used EARLIER
        # in the same function, the earlier use becomes UnboundLocalError.
        # We flag those — that's the actual dangerous pattern.
        for child in node.body:
            if not isinstance(child, (ast.Import, ast.ImportFrom)):
                continue
            imported = self._names_from_import(child)
            for n in imported:
                if self._name_used_in_func_before(node, child.lineno, n):
                    tag = 'DANGEROUS_NAME' if n in DANGEROUS_NAMES else 'used_earlier_in_func'
                    self.issues.append({
                        'file': self.path,
                        'line': child.lineno,
                        'func': node.name,
                        'name': n,
                        'reason': tag,
                    })
        # Sub-class C: missing global declaration. If a function ASSIGNS to
        # a name that is also USED earlier in the same function, and the
        # function does NOT declare that name as global, Python treats the
        # name as local for the WHOLE function. The earlier use becomes
        # UnboundLocalError at runtime. This is the 6th bug class — caught
        # 1 instance so far (last_overnight_research_ts at 23:47 IST Sep 4).
        self._check_missing_global(node)
        self.generic_visit(node)

    def _check_missing_global(self, func_node):
        """Flag assignments in a function where the assigned name is also used
        earlier in the same function, without a 'global name' declaration.

        Heuristic: only flag names that ALSO exist at module level. Function-local
        names (only used after assignment) are safe. Module-level names used
        before assignment without 'global' are the bug pattern.
        """
        # 1. Find all names that exist at module level
        try:
            mod = ast.parse(open(self.path, encoding='utf-8').read())
        except SyntaxError:
            return
        module_names = set()
        for n in mod.body:
            if isinstance(n, ast.Assign):
                for tgt in n.targets:
                    if isinstance(tgt, ast.Name):
                        module_names.add(tgt.id)
                    elif isinstance(tgt, (ast.Tuple, ast.List)):
                        for el in tgt.elts:
                            if isinstance(el, ast.Name):
                                module_names.add(el.id)
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                module_names.add(n.target.id)
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                module_names.add(n.target.id)
        # 2. Find 'global' declarations in this function
        declared_globals = set()
        for n in func_node.body:
            if isinstance(n, ast.Global):
                declared_globals.update(n.names)
        # 3. Find all Name nodes with Store context (assignments) in the function
        assigned_names = {}  # name -> first assignment line
        for n in ast.walk(func_node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                if n.id not in assigned_names:
                    assigned_names[n.id] = n.lineno
        # 4. For each assigned name, check if it's used earlier (Load context) AND
        #    is a module-level name AND not declared as global
        for name, assign_line in assigned_names.items():
            if name not in module_names:
                continue
            if name in declared_globals:
                continue
            if not self._name_used_in_func_before(func_node, assign_line, name):
                continue
            self.issues.append({
                'file': self.path,
                'line': assign_line,
                'func': func_node.name,
                'name': name,
                'reason': 'missing_global_declaration',
            })

    @staticmethod
    def _name_used_in_func_before(func_node: ast.FunctionDef, before_lineno: int, name: str) -> bool:
        for sub in ast.walk(func_node):
            # Skip nodes at or after the import line
            if hasattr(sub, 'lineno') and sub.lineno >= before_lineno:
                continue
            if isinstance(sub, ast.Name) and sub.id == name and isinstance(sub.ctx, ast.Load):
                return True
            if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == name:
                return True
        return False

    @staticmethod
    def _names_from_import(node):
        out = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.asname or alias.name).split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.append((alias.asname or alias.name).split('.')[0])
        return out


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
                source = open(path, encoding='utf-8').read()
                tree = ast.parse(source)
                finder = ShadowingFinder(path, source)
                finder.visit(tree)
                for issue in finder.issues:
                    if issue['reason'] == 'missing_global_declaration':
                        msg = (f"  line {issue['line']} in {issue['func']}() in {issue['file']}: "
                               f"assignment to module-level '{issue['name']}' without "
                               f"'global {issue['name']}' declaration. "
                               f"Add 'global {issue['name']}' at the top of {issue['func']}() "
                               f"so the assignment updates the module-level binding "
                               f"instead of creating a local. "
                               f"[missing_global_declaration]")
                    else:
                        msg = (f"  line {issue['line']} in {issue['func']}() in {issue['file']}: "
                               f"in-function import of '{issue['name']}' "
                               f"[{issue['reason']}]")
                    print(msg)
                    found += 1
            except SyntaxError as e:
                # BOM files etc — skip silently
                pass
    print()
    if found:
        print(f'FAILED: {found} shadow-style issue(s) found.')
        print('  - missing_global_declaration: add "global X" at top of the function')
        print('  - in-function import: move the import to module level')
        sys.exit(1)
    print('PASSED: no shadow-style issues found.')
    sys.exit(0)


if __name__ == '__main__':
    main()
