"""Inspect every method in the neo_api_client to find ALL available endpoints."""
import inspect
import neo_api_client

api_classes = [
    "TotpAPI", "LoginAPI", "LogoutAPI",
    "OrderAPI", "ModifyOrder", "OrderReportAPI", "OrderHistoryAPI", "TradeReportAPI",
    "PositionsAPI", "PortfolioAPI", "MarginAPI", "LimitsAPI",
    "QuotesAPI", "ScripMasterAPI",
]

# ScripSearch is a function
print("=" * 70)
print("KOTAK NEO API v2 — COMPLETE METHOD INVENTORY")
print("=" * 70)

# ScripSearch signature
try:
    sig = inspect.signature(neo_api_client.ScripSearch)
    print(f"\n[ScripSearch] {sig}")
except Exception as e:
    print(f"ScripSearch err: {e}")

for cls_name in api_classes:
    cls = getattr(neo_api_client, cls_name)
    print(f"\n[{cls_name}]")
    methods = [m for m in dir(cls) if not m.startswith("_")]
    for m in methods:
        obj = getattr(cls, m, None)
        if callable(obj) and not isinstance(obj, type):
            try:
                sig = inspect.signature(obj)
                print(f"  {m}{sig}")
            except (ValueError, TypeError):
                print(f"  {m}(...)")

# NeoAPI (main class) - get methods too
print("\n[NeoAPI] - main client class methods:")
for m in dir(neo_api_client.NeoAPI):
    if not m.startswith("_") and m not in ("configuration", "api_client", "NeoWebSocket"):
        obj = getattr(neo_api_client.NeoAPI, m, None)
        if callable(obj):
            try:
                sig = inspect.signature(obj)
                print(f"  {m}{sig}")
            except (ValueError, TypeError):
                print(f"  {m}(...)")
