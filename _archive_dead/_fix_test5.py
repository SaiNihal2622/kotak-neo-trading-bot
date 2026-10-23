from pathlib import Path
p = Path('tests/test_anti_template.py')
src = p.read_text(encoding='utf-8')
old = '''        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {}}  # no positions
            })
        assert result is not None'''
new = '''        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {}}  # no positions
            })
        # FIX 2026-09-17: enforcement removed (no static templates).
        assert result is None'''
if old in src:
    src = src.replace(old, new)
    print('Fixed opens_fresh')
p.write_text(src, encoding='utf-8')
