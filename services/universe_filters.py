"""
Universe Filter Constants — Defines what makes a name eligible for the
Tier 1 universe.

These are deliberately permissive starting thresholds for a research
sandbox. The goal is breadth, not curation. Refinements happen via the
funnel (Tier 2 narrows further, Tier 3 narrows further).
"""

# Price floor — filter true penny stocks but keep cheap names
MIN_PRICE_USD = 5.00

# Volume floor — name must meet this on at least ONE of the volume windows
# (catches both consistently liquid names AND recently liquid names)
MIN_AVG_DAILY_VOLUME_SHARES = 100_000

# Market cap floor — exclude micro-caps with weird options pricing
MIN_MARKET_CAP_USD = 250_000_000

# Hard cap on universe size — trim to top N by daily dollar volume if exceeded
MAX_UNIVERSE_SIZE = 4_500

# Volume averaging windows (in trading days)
VOLUME_WINDOW_SHORT = 20    # ~1 month
VOLUME_WINDOW_MEDIUM = 60   # ~1 quarter
VOLUME_WINDOW_LONG = 252    # ~1 year
