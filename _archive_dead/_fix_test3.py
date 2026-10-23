"""Quick fix: convert remaining 3 anti-template tests to no-op expectations."""
from pathlib import Path
p = Path('tests/test_anti_template.py')
src = p.read_text(encoding='utf-8')

# Test 1: test_anti_template_cuts_loss
old1 = '''        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {"NIFTY_PE": {"qty": 75, "pnl": -800.0}}}
            })
        assert result is not None
        assert result["actions"][0]["type"] == "CLOSE"
        assert result["actions"][0]["strategy"] == "system_enforced_cut_loss"'''
new1 = '''        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {"NIFTY_PE": {"qty": 75, "pnl": -800.0}}}
            })
        # FIX 2026-09-17: enforcement removed (no static templates).
        assert result is None'''
if old1 in src:
    src = src.replace(old1, new1)
    print('Fixed test_anti_template_cuts_loss')
else:
    print('NOT FOUND: cuts_loss')

# Test 2: test_anti_template_scales_up
old2 = '''        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {"NIFTY_PE": {"qty": 75, "pnl": 50.0}}}  # small P&L
            })
        assert result is not None
        assert result["actions"][0]["type"] == "OPEN"
        # Should be a bear put vertical in NIFTY (bearish bias)
        action = result["actions"][0]
        assert action["underlying"] == "NIFTY"
        assert "scale" in action["strategy"].lower()'''
new2 = '''        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {"NIFTY_PE": {"qty": 75, "pnl": 50.0}}}  # small P&L
            })
        # FIX 2026-09-17: enforcement removed (no static templates).
        assert result is None'''
if old2 in src:
    src = src.replace(old2, new2)
    print('Fixed test_anti_template_scales_up')
else:
    print('NOT FOUND: scales_up')

# Test 3: test_anti_template_opens_fresh_when_no_position
old3 = '''        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {}}  # no position
            })
        assert result is not None
        assert result["actions"][0]["strategy"] == "system_enforced_open_bias"'''
new3 = '''        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {}}  # no position
            })
        # FIX 2026-09-17: enforcement removed (no static templates).
        assert result is None'''
if old3 in src:
    src = src.replace(old3, new3)
    print('Fixed test_anti_template_opens_fresh_when_no_position')
else:
    print('NOT FOUND: opens_fresh')

p.write_text(src, encoding='utf-8')
