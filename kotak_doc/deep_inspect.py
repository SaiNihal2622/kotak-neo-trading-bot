"""Deep inspect Kotak Neo SDK: quote types, scrip master, websocket, order types."""
import inspect
import neo_api_client

# 1. QuotesAPI — what quote_type values?
print("=" * 70)
print("QuotesAPI.get_quotes source:")
print("=" * 70)
try:
    print(inspect.getsource(neo_api_client.QuotesAPI.get_quotes))
except Exception as e:
    print(f"err: {e}")

# 2. ScripMasterAPI
print("\n" + "=" * 70)
print("ScripMasterAPI source:")
print("=" * 70)
try:
    print(inspect.getsource(neo_api_client.ScripMasterAPI.scrip_master_init))
except Exception as e:
    print(f"err: {e}")

# 3. NeoAPI.subscribe
print("\n" + "=" * 70)
print("NeoAPI.subscribe source:")
print("=" * 70)
try:
    print(inspect.getsource(neo_api_client.NeoAPI.subscribe))
except Exception as e:
    print(f"err: {e}")

# 4. OrderAPI.place_order (the full thing)
print("\n" + "=" * 70)
print("OrderAPI.order_placing source:")
print("=" * 70)
try:
    print(inspect.getsource(neo_api_client.OrderAPI.order_placing))
except Exception as e:
    print(f"err: {e}")

# 5. MarginAPI
print("\n" + "=" * 70)
print("MarginAPI.margin_init source:")
print("=" * 70)
try:
    print(inspect.getsource(neo_api_client.MarginAPI.margin_init))
except Exception as e:
    print(f"err: {e}")

# 6. NeoWebSocket class
print("\n" + "=" * 70)
print("NeoWebSocket class methods:")
print("=" * 70)
for m in dir(neo_api_client.NeoWebSocket):
    if not m.startswith("_"):
        obj = getattr(neo_api_client.NeoWebSocket, m, None)
        if callable(obj):
            try:
                sig = inspect.signature(obj)
                print(f"  {m}{sig}")
            except (ValueError, TypeError):
                print(f"  {m}(...)")
