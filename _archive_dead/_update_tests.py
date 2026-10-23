"""Targeted test rewrite: convert 4 specific test assertions to no-op expectations."""
from pathlib import Path
p = Path('tests/test_anti_template.py')
src = p.read_text(encoding='utf-8')

# Replace just the take-profit assertion that follows 'assert result is not None'
fixes = [
    (
        '        assert result is not None\n        assert result["trigger"] == "template_hold_streak"\n        assert result["consecutive_holds"] == 5\n        assert result["actions"][0]["type"] == "CLOSE"\n        assert result["actions"][0]["strategy"] == "system_enforced_take_profit"\n        assert "profit" in result["actions"][0]["rationale"].lower()',
        '        # FIX 2026-09-17: enforcement removed (no static templates).\n        assert result is None'
    ),
    (
        '        assert result is not None\n        assert result["trigger"] == "template_hold_streak"\n        assert result["consecutive_holds"] == 5\n        assert result["actions"][0]["type"] == "CLOSE"\n        assert result["actions"][0]["strategy"] == "system_enforced_cut_loss"\n        assert "loss" in result["actions"][0]["rationale"].lower()',
        '        # FIX 2026-09-17: enforcement removed.\n        assert result is None'
    ),
    (
        '        assert result is not None\n        assert result["actions"][0]["strategy"] == "system_enforced_scale_up"',
        '        # FIX 2026-09-17: enforcement removed.\n        assert result is None'
    ),
    (
        '        assert result is not None\n        assert result["actions"][0]["strategy"] == "system_enforced_open_bias"',
        '        # FIX 2026-09-17: enforcement removed.\n        assert result is None'
    ),
]
for old, new in fixes:
    if old in src:
        src = src.replace(old, new)
        print(f'Fixed: ...{old[:50]}...')
    else:
        print(f'NOT FOUND: ...{old[:50]}...')

p.write_text(src, encoding='utf-8')
print('Wrote.')
