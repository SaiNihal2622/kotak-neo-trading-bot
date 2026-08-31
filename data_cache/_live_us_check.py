import yfinance as yf
import datetime
print(f'Now: {datetime.datetime.now().astimezone()}')
print()
print('=== INTRADAY US FUTURES (1d, 5m interval) ===')
for sym, name in [('ES=F', 'S&P500'), ('NQ=F', 'Nasdaq'), ('YM=F', 'Dow'), ('CL=F', 'Crude')]:
    try:
        df = yf.Ticker(sym).history(period='1d', interval='5m')
        if df is None or df.empty:
            print(f'  {name}: empty')
            continue
        closes = df['Close'].dropna()
        if len(closes) < 2:
            print(f'  {name}: only {len(closes)} data points')
            continue
        first = float(closes.iloc[0])
        last = float(closes.iloc[-1])
        chg_open = (last - first) / first * 100
        # Also compute vs yesterday's close
        df2 = yf.Ticker(sym).history(period='5d', interval='1d')
        if df2 is not None and not df2.empty and len(df2) > 1:
            prev_close = float(df2['Close'].iloc[-2])
            chg_prev = (last - prev_close) / prev_close * 100
        else:
            chg_prev = 0
        lo = float(df['Low'].min())
        hi = float(df['High'].max())
        print(f'  {name:10s}: last={last:>10.2f}  from_open={chg_open:+.2f}%  vs_prev_close={chg_prev:+.2f}%  intraday=[{lo:.2f}, {hi:.2f}]')
    except Exception as e:
        print(f'  {name}: error {e}')

print()
print('=== INDIA LIVE (1m interval) ===')
for sym, name in [('^NSEI', 'NIFTY'), ('^NSEBANK', 'BANKNIFTY'), ('^INDIAVIX', 'VIX')]:
    try:
        df = yf.Ticker(sym).history(period='1d', interval='5m')
        if df is None or df.empty:
            print(f'  {name}: empty')
            continue
        closes = df['Close'].dropna()
        if len(closes) < 1:
            print(f'  {name}: no data')
            continue
        last = float(closes.iloc[-1])
        first = float(closes.iloc[0])
        chg = (last - first) / first * 100
        print(f'  {name:10s}: last={last:>10.2f}  from_open={chg:+.2f}%  bars={len(closes)}')
    except Exception as e:
        print(f'  {name}: error {e}')
