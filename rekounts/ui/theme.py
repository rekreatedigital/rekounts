"""One palette and one stylesheet for the whole Hub.

Every page — Dictation, Insights, Dictionary, Settings, Account — is a child of
the Dashboard, so this sheet is applied once at the root and every widget in
every page inherits it. Keeping it in a single module is what makes the paddings
and typography consistent across pages instead of drifting per file.

Deep charcoal surfaces, white/gray text, one near-white accent used sparingly
(active nav item, today's chart bar, an engaged switch). The only non-gray in
the app is a muted red reserved for destructive actions.
"""

BG            = "#0e0f13"   # window background
SIDEBAR       = "#15171c"   # nav rail
CARD          = "#1a1c22"   # cards, inputs, settings rows
CARD_HI       = "#20232b"   # hover / raised
BORDER        = "#2a2d35"
TEXT          = "#e8eaed"   # primary
TEXT_2        = "#9aa0aa"   # secondary
TEXT_3        = "#666b74"   # dim / meta
ACCENT        = "#e8eaed"   # the single accent (near-white)
DANGER        = "#e59a9a"   # destructive hover text
DANGER_BORDER = "#6e4a4a"

# Shared metrics — used by layouts so spacing is a decision made once.
PAGE_MARGINS = (32, 28, 32, 24)   # left, top, right, bottom for every page
ROW_H_PAD = 16
ROW_V_PAD = 12
# Every combo/field in a settings row. Wide enough for the longest option text
# the app offers ("Small — balanced (recommended)" needs ~184px of the ~CONTROL_W
# minus 44px of frame and arrow) — a QComboBox clips its label rather than
# eliding it, so a narrow column silently cuts words in half.
CONTROL_W = 240

STYLE = f"""
QWidget#DashRoot {{ background: {BG}; color: {TEXT}; font-size: 13px; }}
QWidget#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QLabel {{ color: {TEXT}; background: transparent; }}
QLabel[role="brand"] {{ font-size: 16px; font-weight: 800; color: {TEXT}; }}
QLabel[role="page-title"] {{ font-size: 20px; font-weight: 700; color: {TEXT}; }}
QLabel[role="meta"] {{ color: {TEXT_3}; font-size: 11px; }}
QLabel[role="hint"] {{ color: {TEXT_2}; font-size: 12px; }}
QLabel[role="day"] {{ color: {TEXT_2}; font-size: 11px; font-weight: 700;
    letter-spacing: 1.5px; padding: 10px 2px 2px 2px; }}
QLabel[role="badge"] {{ color: {TEXT_2}; background: {CARD_HI};
    border: 1px solid {BORDER}; border-radius: 8px; padding: 1px 8px; font-size: 10px; }}

/* --- settings sections & rows --------------------------------------- */
QLabel[role="section"] {{ color: {TEXT_2}; font-size: 11px; font-weight: 700;
    letter-spacing: 1.5px; }}
QLabel[role="row-title"] {{ color: {TEXT}; font-size: 13px; }}
QLabel[role="row-hint"] {{ color: {TEXT_3}; font-size: 11px; }}
QLabel[role="tag"] {{ color: {TEXT_3}; border: 1px solid {BORDER};
    border-radius: 4px; padding: 0px 5px; font-size: 9px; font-weight: 700;
    letter-spacing: 1px; }}
QWidget#Row {{ background: transparent; }}
QWidget#Row:hover {{ background: {CARD_HI}; }}
QFrame#RowSep {{ background: {BORDER}; border: none; max-height: 1px; }}

QPushButton#NavBtn {{
    text-align: left; padding: 9px 14px; border: none; border-radius: 8px;
    color: {TEXT_2}; background: transparent; font-size: 13px;
    /* Kills the platform focus rectangle — a dotted box drawn INSIDE the
       selected item, on top of a highlight that already says "you are here".
       Keyboard users are not stranded: :focus below gives them the same
       affordance as the mouse, in the design's own language. */
    outline: none;
}}
QPushButton#NavBtn:hover {{ background: {CARD}; color: {TEXT}; }}
QPushButton#NavBtn:focus {{ background: {CARD}; color: {TEXT}; outline: none; }}
QPushButton#NavBtn:checked {{ background: {CARD_HI}; color: {TEXT}; font-weight: 600; }}

QLineEdit {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 10px; color: {TEXT}; selection-background-color: {TEXT_3};
}}
QLineEdit:hover {{ border: 1px solid {TEXT_3}; }}
QLineEdit:focus {{ border: 1px solid {TEXT_2}; }}
QLineEdit#HotkeyEdit {{ font-weight: 600; letter-spacing: 0.5px; }}

QComboBox {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 10px; color: {TEXT};
}}
QComboBox:hover {{ border: 1px solid {TEXT_3}; }}
QComboBox:focus {{ border: 1px solid {TEXT_2}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CARD}; color: {TEXT}; padding: 4px;
    border: 1px solid {BORDER}; selection-background-color: {CARD_HI};
    outline: none;
}}

QSpinBox {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 8px; color: {TEXT};
}}
QSpinBox:hover {{ border: 1px solid {TEXT_3}; }}
QSpinBox:focus {{ border: 1px solid {TEXT_2}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none;
    background: transparent; }}

QPushButton#Ghost {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 6px 12px; color: {TEXT_2};
}}
QPushButton#Ghost:hover {{ border: 1px solid {TEXT_2}; color: {TEXT}; }}
QPushButton#Ghost:focus {{ border: 1px solid {TEXT_2}; }}
QPushButton#Ghost:disabled {{ color: {TEXT_3}; border: 1px solid {BORDER}; }}

QPushButton#Danger {{
    background: transparent; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 6px 12px; color: {TEXT_2};
}}
QPushButton#Danger:hover {{ border: 1px solid {DANGER_BORDER}; color: {DANGER}; }}
QPushButton#Danger:focus {{ border: 1px solid {DANGER_BORDER}; }}

QWidget#Card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QWidget#StatCard {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
QScrollArea {{ border: none; background: transparent; }}
/* The viewport and the widget inside it are plain QWidgets: without this they
   paint the default light window color behind every scrolling page. */
QScrollArea > QWidget {{ background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_3}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""
