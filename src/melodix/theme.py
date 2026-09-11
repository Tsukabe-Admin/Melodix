"""theme.py — single source of truth for the Gruvbox palette.

Every module that needs to colour Rich markup or styles should import from
here instead of re-declaring hex literals. The CSS file mirrors these values
(Textual CSS cannot import Python), so keep the two in sync.
"""

# ── Backgrounds ───────────────────────────────────────────────────────────────
BG   = "#1d2021"   # hard background
BG0  = "#282828"   # dark0
BG1  = "#3c3836"   # dark1
BG2  = "#504945"   # dark2  – separators / inactive
BG3  = "#665c54"   # dark3  – inactive borders
BG4  = "#7c6f64"   # dark4

# ── Foregrounds ───────────────────────────────────────────────────────────────
FG   = "#ebdbb2"   # primary text
FG1  = "#d5c4a1"   # secondary text
FG2  = "#bdae93"   # tertiary text
FG3  = "#a89984"   # dimmed / labels

# ── Accents ───────────────────────────────────────────────────────────────────
RED    = "#fb4934"   # alert / peak
GREEN  = "#b8bb26"   # playing / positive
YELLOW = "#fabd2f"   # primary accent / active
BLUE   = "#83a598"   # info / secondary
PURPLE = "#d3869b"   # metadata accent
AQUA   = "#8ec07c"   # volume / progress
ORANGE = "#fe8019"   # toggles / warnings
GRAY   = "#928374"   # muted

WHITE = "#ffffff"   # visualizer sheen
