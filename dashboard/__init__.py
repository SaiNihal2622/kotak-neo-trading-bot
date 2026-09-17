"""dashboard package — Streamlit app for the Kotak Neo bot.

Two submodules:
- app.py            : the Streamlit entry point (was a flat module before)
- real_provider.py  : RealDataProvider reading from data_cache/*.json

Note: scripts/dashboard.py is a SEPARATE module (the offline HTML version).
That one is imported as `scripts.dashboard`, not `dashboard`, so they don't
conflict.
"""
