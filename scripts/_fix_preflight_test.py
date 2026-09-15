"""One-off script to fix the hardcoded dates in test_preflight_check.py."""
from pathlib import Path
ROOT = Path(__file__).parent.parent.resolve()
f = ROOT / "tests" / "test_preflight_check.py"
content = f.read_text(encoding="utf-8")
# Replace the offending test
old = """def test_check_inline_journal_filters_by_today(tmp_dcache):
    \"\"\"Only today's FILL entries are counted.\"\"\"
    journal = tmp_dcache / \"trade_journal.jsonl\"
    journal.write_text(
        '{\"trade_id\":\"FILL-OLD\",\"ts\":\"2026-09-01T10:00:00\"}\\n'
        '{\"trade_id\":\"FILL-NEW\",\"ts\":\"2026-09-08T10:00:00\"}\\n',
        encoding=\"utf-8\",
    )"""
new = """def test_check_inline_journal_filters_by_today(tmp_dcache):
    \"\"\"Only today's FILL entries are counted.\"\"\"
    from datetime import datetime
    today = datetime.now().strftime(\"%Y-%m-%d\")
    journal = tmp_dcache / \"trade_journal.jsonl\"
    journal.write_text(
        '{\"trade_id\":\"FILL-OLD\",\"ts\":\"2026-09-01T10:00:00\"}\\n'
        f'{{\"trade_id\":\"FILL-NEW\",\"ts\":\"{today}T10:00:00\"}}\\n',
        encoding=\"utf-8\",
    )"""
content = content.replace(old, new)
f.write_text(content, encoding="utf-8")
print("OK")
