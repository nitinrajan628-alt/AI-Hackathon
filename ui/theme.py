"""Visual system: design tokens and Streamlit chrome overrides.

Three appearance modes share one token contract, so every surface, table and
chart stays coherent:

  light   - institutional analytics default
  dark    - intentionally designed dark palette (not an inverted light theme),
            using lighter type weights because light-on-dark text renders
            optically heavier than dark-on-light at the same weight
  rainbow - a deliberately playful chrome: spectrum accents across headings,
            section labels, badges and rules. Chart series keep the
            colour-vision-deficiency-validated categorical palette so data
            remains readable; the rainbow lives in the chrome, not the data.
"""
from __future__ import annotations

import streamlit as st

THEMES = ("light", "dark", "rainbow")

FONT_STACK = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

# Spectrum used by rainbow mode for chrome accents (headings, labels, chips).
RAINBOW_HUES = ["#d1344a", "#e0722a", "#c79000", "#2f8f4e",
                "#1b8fa8", "#2a6fd6", "#6b4bc4", "#b5439b"]

TOKENS = {
    "light": {
        "page": "#f6f6f3", "surface": "#fcfcfb", "raised": "#ffffff",
        "ink": "#141412", "ink2": "#52514e", "muted": "#898781",
        "hairline": "#e3e2db", "border": "rgba(11,11,11,0.12)",
        "accent": "#1c5cab", "accent_soft": "#e8eff8",
        "negative": "#a83232", "positive": "#1f5c40",
        "badge_bg": "#f0efec", "code_bg": "#f0efec",
        "sidebar": "#efeeea", "input_bg": "#ffffff",
        "shadow": "0 1px 2px rgba(11,11,11,0.05)",
        # Type weights: standard on a light ground.
        "weight_body": "400", "weight_medium": "500", "weight_strong": "600",
        "weight_heading": "600", "letter_spacing": "0",
    },
    "dark": {
        "page": "#111110", "surface": "#1a1a19", "raised": "#201f1e",
        "ink": "#ece9e0", "ink2": "#bebcb2", "muted": "#918f88",
        "hairline": "#2c2c2a", "border": "rgba(255,255,255,0.14)",
        "accent": "#7db0ee", "accent_soft": "#1d2a3a",
        "negative": "#e58080", "positive": "#7dc4a2",
        "badge_bg": "#252523", "code_bg": "#242422",
        "sidebar": "#161615", "input_bg": "#242422",
        "shadow": "0 1px 2px rgba(0,0,0,0.4)",
        # Lighter weights: light-on-dark type blooms optically, so each role
        # steps down one weight and gains a little tracking for legibility.
        "weight_body": "300", "weight_medium": "400", "weight_strong": "500",
        "weight_heading": "500", "letter_spacing": "0.01em",
    },
    # Meme mode. The page itself is an animated rainbow; content sits on
    # translucent white panels purely so the numbers remain readable.
    "rainbow": {
        "page": "#ff00cc", "surface": "rgba(255,255,255,0.90)",
        "raised": "rgba(255,255,255,0.96)",
        "ink": "#12071c", "ink2": "#2c1440", "muted": "#6a4a86",
        "hairline": "rgba(120,40,180,0.28)", "border": "rgba(120,40,180,0.45)",
        "accent": "#c81cd6", "accent_soft": "rgba(255,255,255,0.75)",
        "negative": "#d1002e", "positive": "#00873d",
        "badge_bg": "rgba(255,255,255,0.85)", "code_bg": "rgba(255,255,255,0.88)",
        "sidebar": "#ff5ecb", "input_bg": "rgba(255,255,255,0.95)",
        "shadow": "0 3px 14px rgba(120,0,160,0.35)",
        "weight_body": "600", "weight_medium": "700", "weight_strong": "800",
        "weight_heading": "800", "letter_spacing": "0.01em",
    },
}

# Per-theme type. Rainbow gets the internet's least serious typeface.
FONTS = {
    "light": FONT_STACK,
    "dark": FONT_STACK,
    "rainbow": '"Comic Sans MS", "Comic Sans", "Chalkboard SE", '
               '"Comic Neue", cursive, system-ui, sans-serif',
}


def current_theme() -> str:
    theme = st.session_state.get("theme", "light")
    return theme if theme in TOKENS else "light"


def tokens() -> dict:
    return TOKENS[current_theme()]


# Saturated spectrum for meme mode - deliberately garish.
NEON = ["#ff0040", "#ff7a00", "#ffe600", "#20e000", "#00e5d0",
        "#0066ff", "#8c00ff", "#ff00c8"]


def _rainbow_rules() -> str:
    """Meme mode.

    Not a colour accent on a serious theme: the entire page is an animated
    rainbow, the typeface is Comic Sans, and nothing about it invites being
    taken seriously. Content panels stay translucent-white so the figures
    remain readable - the joke is the chrome, not the data.
    """
    neon = ", ".join(NEON + [NEON[0]])
    return f"""
    @keyframes rr-rainbow-pan {{
        0%   {{ background-position:   0% 50%; }}
        100% {{ background-position: 400% 50%; }}
    }}
    @keyframes rr-hue-cycle {{
        0%   {{ filter: hue-rotate(0deg); }}
        100% {{ filter: hue-rotate(360deg); }}
    }}
    @keyframes rr-wobble {{
        0%, 100% {{ transform: rotate(-2deg); }}
        50%      {{ transform: rotate(2deg); }}
    }}

    /* The whole page is the rainbow. */
    .stApp {{
        background: linear-gradient(115deg, {neon});
        background-size: 400% 400%;
        animation: rr-rainbow-pan 9s linear infinite;
    }}
    [data-testid="stSidebar"] {{
        background: linear-gradient(200deg, {neon});
        background-size: 300% 300%;
        animation: rr-rainbow-pan 7s linear infinite reverse;
        border-right: 4px solid #fff;
    }}
    [data-testid="stHeader"] {{
        background: linear-gradient(90deg, {neon}) !important;
        background-size: 400% 100% !important;
        animation: rr-rainbow-pan 6s linear infinite;
    }}
    [data-testid="stBottomBlockContainer"], [data-testid="stBottom"] > div {{
        background: transparent;
    }}

    /* Everything wears Comic Sans. */
    .stApp, .stApp * {{ font-family: var(--font-stack) !important; }}
    [data-testid="stIconMaterial"], span[class*="material"], i[class*="material"] {{
        font-family: "Material Symbols Rounded", "Material Icons" !important;
    }}

    /* Two text environments: loose text sits on the moving gradient and needs
       a hard outline; text inside a white panel must stay plain dark ink. */
    .stApp, .stApp p, .stApp span, .stApp label, .stApp li,
    .stApp h1, .stApp h2, .stApp h3, .stApp h4,
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
    .stCaption, .rr-sectionlabel,
    [data-testid="stSidebar"] *, .stTabs [data-baseweb="tab"] {{
        color: #ffffff !important;
        text-shadow: 2px 2px 0 #000, -1px -1px 0 #000,
                     1px -1px 0 #000, -1px 1px 0 #000;
    }}
    /* Panels, tables and inputs: dark ink, no outline. */
    .rr-card, .rr-card p, .rr-card span, .rr-card li, .rr-card div,
    .rr-slide, .rr-slide p, .rr-slide span, .rr-slide li, .rr-slide div,
    .rr-evidence-item, .rr-evidence-item div, .rr-evidence-item span,
    .rr-metric, .rr-metric div, .rr-kv, .rr-kv b,
    table.rr-table td, table.rr-table th,
    [data-testid="stExpander"] summary, [data-testid="stExpander"] summary *,
    [data-testid="stChatInput"] textarea,
    [data-baseweb="select"] *, [data-testid="stSelectbox"] div,
    .stTextInput input, pre, code {{
        text-shadow: none !important;
    }}
    .rr-card, .rr-card p, .rr-card span, .rr-card li,
    .rr-slide p, .rr-slide span, .rr-slide li,
    .rr-evidence-item div, .rr-evidence-item span,
    .rr-metric div, .rr-kv, .rr-kv b,
    table.rr-table td, [data-testid="stExpander"] summary,
    [data-testid="stChatInput"] textarea,
    [data-baseweb="select"] div, .stTextInput input, pre, code {{
        color: #12071c !important;
    }}
    table.rr-table th {{ color: #ffffff !important; }}
    /* text-shadow inherits, and would otherwise smear every axis tick and
       data label inside the Plotly SVG. */
    .js-plotly-plot text, .stPlotlyChart text, svg text {{
        text-shadow: none !important;
    }}

    .rr-brand {{
        font-size: 1.3rem !important;
        color: #fff200 !important;
        text-shadow: 2px 2px 0 #000, -2px -2px 0 #000,
                     2px -2px 0 #000, -2px 2px 0 #000 !important;
        animation: rr-wobble 1.6s ease-in-out infinite;
        display: inline-block;
    }}
    .rr-brand small {{ color: #ffffff !important; animation: none; }}

    /* Panels: translucent white so numbers stay legible. */
    .rr-card, .rr-slide, .rr-evidence-item, .rr-metric,
    [data-testid="stExpander"] details, [data-testid="stMetric"] {{
        background: rgba(255,255,255,0.92) !important;
        border: 3px solid transparent !important;
        border-radius: 14px !important;
        background-clip: padding-box !important;
        box-shadow: 0 0 0 3px #ff00c8, 0 0 0 6px #ffe600, 0 0 0 9px #00e5d0,
                    0 8px 22px rgba(0,0,0,0.35) !important;
    }}
    .rr-card {{ animation: rr-hue-cycle 8s linear infinite; }}

    .rr-headline {{
        font-size: 1.2rem !important;
        background: linear-gradient(90deg, {neon});
        background-size: 300% 100%;
        -webkit-background-clip: text; background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: rr-rainbow-pan 4s linear infinite;
    }}
    .rr-analysis-title {{
        color: #d6009c !important; font-size: 0.85rem !important;
        text-decoration: underline wavy #00e5d0;
    }}

    /* Controls. */
    .stButton > button, .stDownloadButton > button {{
        background: linear-gradient(90deg, {neon}) !important;
        background-size: 300% 100% !important;
        animation: rr-rainbow-pan 5s linear infinite;
        color: #ffffff !important; font-weight: 800 !important;
        border: 3px solid #ffffff !important; border-radius: 999px !important;
        text-shadow: 1px 1px 0 #000;
    }}
    .stButton > button:hover {{ transform: scale(1.05); color: #ffffff !important; }}
    [data-testid="stChatInput"] {{
        border: 4px solid transparent !important; border-radius: 999px !important;
        background:
          linear-gradient(rgba(255,255,255,0.97), rgba(255,255,255,0.97)) padding-box,
          linear-gradient(90deg, {neon}) border-box !important;
        background-size: auto, 300% 100% !important;
        animation: rr-rainbow-pan 4s linear infinite;
    }}
    [data-testid="stChatInput"] textarea {{
        color: #12071c !important; font-weight: 700 !important;
    }}
    [data-testid="stChatInput"] textarea::placeholder {{ color: #a03bbd !important; }}

    .rr-chip, .rr-badge {{
        background: linear-gradient(90deg, {neon}) !important;
        background-size: 300% 100% !important;
        animation: rr-rainbow-pan 6s linear infinite;
        color: #ffffff !important; border: 2px solid #fff !important;
        text-shadow: 1px 1px 0 rgba(0,0,0,0.6);
    }}

    /* Tables: keep the figures readable, decorate the frame. */
    .rr-tablewrap {{
        border: 3px solid #ffffff !important; border-radius: 12px !important;
        box-shadow: 0 0 0 3px #8c00ff, 0 6px 18px rgba(0,0,0,0.3);
    }}
    table.rr-table {{ background: rgba(255,255,255,0.95) !important; }}
    table.rr-table th {{
        background: linear-gradient(90deg, {neon}) !important;
        background-size: 300% 100% !important;
        animation: rr-rainbow-pan 5s linear infinite;
        color: #ffffff !important; text-shadow: 1px 1px 0 rgba(0,0,0,0.55);
    }}
    table.rr-table td {{ color: #12071c !important; }}
    table.rr-table tr:nth-child(even) td {{ background: rgba(255,230,255,0.55); }}
    table.rr-table tr.total td {{ background: #fff200 !important; font-weight: 900; }}

    .rr-slide-title, .rr-slide-section, .rr-analysis-title {{
        text-shadow: none !important;
    }}
    .rr-slide-title {{ color: #c81cd6 !important; }}
    .rr-slide-section {{ color: #0066ff !important; }}
    .rr-metric .label {{ color: #6a4a86 !important; }}

    /* Respect a stated preference for less motion - the colours stay, the
       animation stops. */
    @media (prefers-reduced-motion: reduce) {{
        .stApp, [data-testid="stSidebar"], [data-testid="stHeader"],
        .rr-card, .rr-headline, .rr-brand, .stButton > button,
        [data-testid="stChatInput"], .rr-chip, .rr-badge, table.rr-table th {{
            animation: none !important;
        }}
    }}
    """


def _responsive_rules() -> str:
    """Overrides for tablet, phone and touch screens.

    Streamlit already stacks ``st.columns`` vertically on narrow viewports, so
    these rules only cover what the framework cannot infer: the fixed sidebar
    width, hover-only overlay actions and the desktop-first column ordering.
    """
    # Strict child chain so only the chat page's own three columns are
    # reordered - nested st.columns calls inside them must keep their order.
    chat_columns = (
        '.st-key-chat_layout > [data-testid="stLayoutWrapper"] '
        '> [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]'
    )
    return """
    /* Touch screens never fire :hover, so overlay actions that are only
       revealed on hover would otherwise be unreachable. */
    @media (hover: none) {
        div[class*="st-key-tile_"] [data-testid="stHorizontalBlock"],
        div[class*="_answercard"] [class*="_copy_answer"],
        div[class*="_chartbox_"] [class*="_dlchart_"] {
            opacity: 1;
        }
    }

    /* The 400px sidebar swallows a tablet viewport, and on phones Streamlit
       turns it into an overlay drawer that must stay narrower than the page. */
    @media (max-width: 900px) {
        [data-testid="stSidebar"] {
            min-width: 0 !important; width: min(85vw, 320px) !important;
        }
    }

    @media (max-width: 640px) {
        .block-container {
            padding-top: 0.8rem; padding-left: 0.75rem; padding-right: 0.75rem;
        }

        /* Stacked chat page: the conversation leads, history and evidence
           follow it rather than pushing it below the fold. */
        CHAT_COLUMNS:nth-child(1) { order: 2; }
        CHAT_COLUMNS:nth-child(2) { order: 1; }
        CHAT_COLUMNS:nth-child(3) { order: 3; }

        .rr-slide { padding: 1rem 1rem 0.8rem 1rem; }
        .rr-slide-title { font-size: 1.15rem; }
        .rr-slide-headline { font-size: 0.92rem; }
        .rr-metric { min-width: 0; flex: 1 1 45%; }
        .rr-tablewrap { -webkit-overflow-scrolling: touch; }
        table.rr-table { font-size: 0.78rem; }
        table.rr-table th, table.rr-table td { padding: 0.35rem 0.5rem; }

        /* iOS Safari zooms the whole page in when a focused input is
           smaller than 16px. */
        .stTextInput input, .stTextArea textarea,
        [data-testid="stChatInput"] textarea { font-size: 16px; }
    }
    """.replace("CHAT_COLUMNS", chat_columns)


def inject_css() -> None:
    t = tokens()
    theme = current_theme()
    css = f"""
    <style>
    :root {{
      --page: {t['page']}; --surface: {t['surface']}; --raised: {t['raised']};
      --ink: {t['ink']}; --ink2: {t['ink2']}; --muted: {t['muted']};
      --hairline: {t['hairline']}; --border: {t['border']};
      --accent: {t['accent']}; --accent-soft: {t['accent_soft']};
      --negative: {t['negative']}; --positive: {t['positive']};
      --badge-bg: {t['badge_bg']}; --code-bg: {t['code_bg']};
      --input-bg: {t['input_bg']}; --sidebar-bg: {t['sidebar']};
      --font-stack: {FONTS.get(theme, FONT_STACK)};
      --w-body: {t['weight_body']}; --w-medium: {t['weight_medium']};
      --w-strong: {t['weight_strong']}; --w-heading: {t['weight_heading']};
      --tracking: {t['letter_spacing']};
    }}

    /* ---- Application chrome -------------------------------------- */
    .stApp {{ background: var(--page); }}
    .stApp, .stApp p, .stApp li, .stApp label, .stApp span,
    .stApp div, .stApp input, .stApp textarea, .stApp button {{
        font-family: var(--font-stack);
    }}
    /* Material icon glyphs are ligatures: they must keep the icon font, or
       the ligature name renders as literal text. Restore it after the
       blanket family rule above. */
    [data-testid="stIconMaterial"],
    span[class*="material"], i[class*="material"] {{
        font-family: "Material Symbols Rounded", "Material Symbols Outlined",
                     "Material Icons" !important;
        font-weight: normal !important; letter-spacing: normal !important;
    }}
    .stApp, .stApp p, .stApp li, .stApp label, .stApp span {{
        color: var(--ink); font-weight: var(--w-body);
        letter-spacing: var(--tracking);
    }}
    [data-testid="stHeader"] {{ background: transparent; }}
    [data-testid="stSidebar"] {{
        background: var(--sidebar-bg); border-right: 1px solid var(--hairline);
        min-width: 380px; width: 400px;
    }}
    [data-testid="stSidebar"] * {{ color: var(--ink); }}
    .block-container {{ padding-top: 1.4rem; max-width: 100%; }}

    h1, h2, h3, h4 {{
        color: var(--ink) !important; font-weight: var(--w-heading);
        letter-spacing: -0.01em;
    }}
    strong, b {{ font-weight: var(--w-strong); }}
    a {{ color: var(--accent); }}
    hr {{ border-color: var(--hairline); }}

    /* ---- Widgets -------------------------------------------------- */
    .stButton > button, .stDownloadButton > button {{
        background: var(--raised); color: var(--ink);
        border: 1px solid var(--border); border-radius: 6px;
        box-shadow: none; font-size: 0.86rem; padding: 0.3rem 0.8rem;
        font-weight: var(--w-medium);
    }}

    /* Table CSV download and Save-as-artifact buttons sit right-aligned
       under their content instead of the default left edge. Streamlit's
       vertical block containers default to flex-direction: column, so
       horizontal placement is controlled by align-items, not justify-content. */
    div[class*="_rowend"], div[class*="_artifactrow"] {{
        align-items: flex-end;
    }}
    .stButton > button:hover {{
        border-color: var(--accent); color: var(--accent); background: var(--raised);
    }}
    .stButton > button[kind="primary"] {{
        background: var(--accent); color: #ffffff; border-color: var(--accent);
    }}
    .stButton > button[kind="primary"]:hover {{ color: #ffffff; opacity: 0.92; }}

    div[data-baseweb="select"] > div {{
        background: var(--input-bg); border-color: var(--border);
        color: var(--ink); border-radius: 6px; min-height: 38px;
        font-weight: var(--w-body);
    }}
    [data-testid="stSelectbox"] > div > div {{
        background-color: var(--input-bg) !important;
        border-color: var(--border) !important;
        color: var(--ink) !important; border-radius: 6px;
    }}
    [data-testid="stSelectbox"] svg {{ fill: var(--muted); }}
    div[data-baseweb="select"] svg {{ fill: var(--muted); }}
    div[data-baseweb="popover"] ul, ul[data-testid="stSelectboxVirtualDropdown"] {{
        background: var(--raised) !important;
    }}
    div[data-baseweb="popover"] li, div[data-baseweb="menu"] li {{
        background: var(--raised) !important; color: var(--ink) !important;
        font-weight: var(--w-body);
    }}
    div[data-baseweb="popover"] li:hover, div[data-baseweb="menu"] li:hover,
    li[aria-selected="true"] {{ background: var(--accent-soft) !important; }}

    .stTextInput input, .stNumberInput input, .stTextArea textarea {{
        background: var(--input-bg); color: var(--ink);
        border: 1px solid var(--border); border-radius: 6px;
        font-weight: var(--w-body); font-family: var(--font-stack);
    }}

    /* Chat bar: same family and lighter weight as the rest of the app. */
    [data-testid="stChatInput"] {{
        background: var(--input-bg); border: 1px solid var(--border);
        border-radius: 8px;
    }}
    [data-testid="stChatInput"] > div {{ background: var(--input-bg) !important; }}
    [data-testid="stChatInput"] textarea {{
        background: transparent; color: var(--ink);
        font-family: var(--font-stack); font-weight: var(--w-body);
        letter-spacing: var(--tracking); font-size: 0.95rem;
    }}
    [data-testid="stChatInput"] textarea::placeholder {{
        color: var(--muted); font-weight: var(--w-body); opacity: 1;
    }}
    [data-testid="stChatInput"] button svg {{ fill: var(--accent); }}
    [data-testid="stBottomBlockContainer"], [data-testid="stBottom"] > div {{
        background: var(--page);
    }}

    [data-testid="stExpander"] details {{
        background: var(--surface); border: 1px solid var(--hairline);
        border-radius: 8px;
    }}
    [data-testid="stExpander"] summary {{
        color: var(--ink2); font-size: 0.86rem; font-weight: var(--w-medium);
    }}
    [data-testid="stExpander"] summary:hover {{ color: var(--accent); }}

    .stTabs [data-baseweb="tab-list"] {{
        gap: 2px; border-bottom: 1px solid var(--hairline); background: transparent;
    }}
    .stTabs [data-baseweb="tab"] {{
        background: transparent; color: var(--muted);
        font-size: 0.84rem; padding: 0.35rem 0.7rem; font-weight: var(--w-medium);
    }}
    .stTabs [aria-selected="true"] {{
        color: var(--accent) !important; border-bottom: 2px solid var(--accent);
    }}
    .stTabs [data-baseweb="tab-highlight"] {{ background-color: var(--accent); }}
    .stTabs [data-baseweb="tab-border"] {{ background-color: var(--hairline); }}

    [data-testid="stMetric"] {{
        background: var(--surface); border: 1px solid var(--hairline);
        border-radius: 8px; padding: 0.6rem 0.9rem;
    }}
    [data-testid="stMetricLabel"] {{ color: var(--muted); }}
    [data-testid="stMetricValue"] {{
        color: var(--ink); font-variant-numeric: tabular-nums;
        font-weight: var(--w-strong);
    }}

    .stAlert {{ border-radius: 8px; }}
    [data-testid="stChatMessage"] {{ background: transparent; }}
    .stCode, pre {{ background: var(--code-bg) !important; border-radius: 6px; }}
    code {{ color: var(--ink2); font-weight: var(--w-body); }}
    [data-testid="stCaptionContainer"], .stCaption, small {{ color: var(--muted); }}
    [data-testid="stToggle"] label p {{ color: var(--ink2); font-size: 0.84rem; }}
    [data-testid="stRadio"] label p, [role="radiogroup"] label p {{
        color: var(--ink2); font-size: 0.84rem; font-weight: var(--w-body);
    }}

    [data-testid="stPageLink"] a {{
        border-radius: 6px; padding: 0.28rem 0.6rem; color: var(--ink2);
    }}
    [data-testid="stPageLink"] a:hover {{ background: var(--accent-soft); }}
    [data-testid="stPageLink"] a[aria-current="page"] {{
        background: var(--accent-soft); color: var(--accent);
    }}
    [data-testid="stPageLink"] a[aria-current="page"] p {{
        color: var(--accent); font-weight: var(--w-strong);
    }}

    /* ---- Application components ----------------------------------- */
    .rr-brand {{
        font-size: 1.02rem; font-weight: var(--w-heading); letter-spacing: -0.01em;
        color: var(--ink); padding-bottom: 0.1rem;
    }}
    .rr-brand small {{
        display: block; color: var(--muted); font-weight: var(--w-medium);
        font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase;
        margin-top: 2px;
    }}
    .rr-sectionlabel {{
        font-size: 0.7rem; letter-spacing: 0.09em; text-transform: uppercase;
        color: var(--muted); margin: 0.9rem 0 0.25rem 0;
        font-weight: var(--w-strong);
    }}

    .rr-card {{
        background: var(--surface); border: 1px solid var(--hairline);
        border-radius: 10px; padding: 1rem 1.15rem 0.9rem 1.15rem;
        box-shadow: {t['shadow']};
    }}
    .rr-headline {{
        font-size: 1.06rem; font-weight: var(--w-strong); color: var(--ink);
        line-height: 1.42; margin-bottom: 0.25rem; letter-spacing: -0.005em;
    }}
    .rr-meta {{ font-size: 0.78rem; color: var(--muted); margin-bottom: 0.55rem; }}
    .rr-obs {{ margin: 0.35rem 0 0.2rem 0; padding-left: 1.05rem; }}
    .rr-obs li {{
        font-size: 0.9rem; color: var(--ink2); margin-bottom: 0.28rem;
        line-height: 1.5; font-weight: var(--w-body);
    }}
    .rr-limit {{ font-size: 0.8rem; color: var(--muted); font-style: italic;
                 margin-top: 0.4rem; }}

    /* ---- Answer card copy button: top-right overlay, hidden until hover -- */
    div[class*="_answercard"] {{ position: relative; }}
    div[class*="_answercard"] .rr-card {{ padding-right: 2.6rem; }}
    div[class*="_answercard"] [class*="_copy_answer"] {{
        position: absolute; top: 0.6rem; right: 0.65rem; z-index: 2;
        opacity: 0; transition: opacity 0.15s; margin: 0;
    }}
    div[class*="_answercard"]:hover [class*="_copy_answer"] {{ opacity: 1; }}
    div[class*="_answercard"] [class*="_copy_answer"] button {{
        padding: 0.2rem 0.55rem !important; min-height: 0 !important;
        font-size: 0.72rem !important; border: 1px solid var(--hairline) !important;
        background: var(--surface) !important; color: var(--muted) !important;
        border-radius: 5px !important; box-shadow: 0 1px 3px rgba(0,0,0,0.15);
    }}
    div[class*="_answercard"] [class*="_copy_answer"] button:hover {{
        color: var(--accent) !important; background: var(--accent-soft) !important;
        transform: none !important;
    }}

    /* ---- Chart download button: top-right overlay, hidden until hover ---- */
    div[class*="_chartbox_"] {{ position: relative; margin-bottom: 0.5rem; }}
    .rr-chart-title {{
        font-size: 0.86rem; font-weight: var(--w-strong); color: var(--ink2);
        margin-bottom: 0.35rem; padding-right: 2.6rem;
    }}
    div[class*="_chartbox_"] [class*="_dlchart_"] {{
        position: absolute; top: 0.1rem; right: 0.1rem; z-index: 2;
        opacity: 0; transition: opacity 0.15s; margin: 0;
    }}
    div[class*="_chartbox_"]:hover [class*="_dlchart_"] {{ opacity: 1; }}
    div[class*="_chartbox_"] [class*="_dlchart_"] button {{
        padding: 0.2rem 0.55rem !important; min-height: 0 !important;
        font-size: 0.72rem !important; border: 1px solid var(--hairline) !important;
        background: var(--surface) !important; color: var(--muted) !important;
        border-radius: 5px !important; box-shadow: 0 1px 3px rgba(0,0,0,0.15);
    }}
    div[class*="_chartbox_"] [class*="_dlchart_"] button:hover {{
        color: var(--accent) !important; background: var(--accent-soft) !important;
        transform: none !important;
    }}

    .rr-analysis-section {{
        margin-top: 0.85rem; padding-top: 0.65rem;
        border-top: 1px solid var(--hairline);
    }}
    .rr-analysis-title {{
        font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase;
        color: var(--accent); font-weight: var(--w-strong);
        margin-bottom: 0.15rem;
    }}

    .rr-badge {{
        display: inline-block; font-size: 0.66rem; font-weight: var(--w-strong);
        letter-spacing: 0.07em; text-transform: uppercase;
        color: var(--ink2); background: var(--badge-bg);
        border: 1px solid var(--hairline); border-radius: 4px;
        padding: 0.1rem 0.42rem; margin-right: 0.3rem;
    }}
    .rr-badge.accent {{ color: var(--accent); border-color: var(--accent);
                        background: transparent; }}

    .rr-chip {{
        display: inline-block; font-size: 0.76rem; color: var(--ink2);
        background: var(--badge-bg); border: 1px solid var(--hairline);
        border-radius: 999px; padding: 0.12rem 0.6rem; margin: 0 0.3rem 0.3rem 0;
    }}

    /* ---- Tables ---------------------------------------------------- */
    .rr-tablewrap {{ overflow-x: auto; margin: 0.5rem 0 0.25rem 0;
                     border: 1px solid var(--hairline); border-radius: 8px; }}
    table.rr-table {{
        width: 100%; border-collapse: collapse; font-size: 0.86rem;
        background: var(--surface);
    }}
    table.rr-table th {{
        text-align: left; font-weight: var(--w-strong); color: var(--muted);
        font-size: 0.74rem; letter-spacing: 0.04em; text-transform: uppercase;
        padding: 0.5rem 0.8rem; border-bottom: 1px solid var(--hairline);
        white-space: nowrap; background: var(--surface);
    }}
    table.rr-table td {{
        padding: 0.42rem 0.8rem; color: var(--ink); font-weight: var(--w-body);
        border-bottom: 1px solid var(--hairline); white-space: nowrap;
    }}
    table.rr-table tr:last-child td {{ border-bottom: none; }}
    table.rr-table td.num, table.rr-table th.num {{
        text-align: right; font-variant-numeric: tabular-nums;
    }}
    table.rr-table td.neg {{ color: var(--negative); }}
    table.rr-table tr.total td {{
        font-weight: var(--w-strong); border-top: 1.5px solid var(--border);
    }}

    /* ---- Report slides --------------------------------------------- */
    .rr-slide {{
        background: var(--surface); border: 1px solid var(--hairline);
        border-radius: 12px; padding: 1.6rem 2rem 1.1rem 2rem;
        box-shadow: {t['shadow']};
    }}
    .rr-slide-section {{
        font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase;
        color: var(--accent); font-weight: var(--w-strong); margin-bottom: 0.3rem;
    }}
    .rr-slide-title {{
        font-size: 1.45rem; font-weight: var(--w-heading); color: var(--ink);
        letter-spacing: -0.015em; margin-bottom: 0.2rem;
    }}
    .rr-slide-headline {{
        font-size: 1.0rem; color: var(--ink2); margin-bottom: 0.9rem;
        font-weight: var(--w-body);
    }}
    .rr-slide-footer {{
        margin-top: 1.1rem; padding-top: 0.55rem;
        border-top: 1px solid var(--hairline);
        font-size: 0.74rem; color: var(--muted);
        display: flex; justify-content: space-between;
    }}
    .rr-metricrow {{ display: flex; gap: 0.8rem; flex-wrap: wrap;
                     margin: 0.4rem 0 0.8rem 0; }}
    .rr-metric {{
        border: 1px solid var(--hairline); border-radius: 8px;
        padding: 0.55rem 0.95rem; min-width: 150px; background: var(--raised);
    }}
    .rr-metric .label {{ font-size: 0.7rem; color: var(--muted);
        text-transform: uppercase; letter-spacing: 0.06em;
        font-weight: var(--w-strong); }}
    .rr-metric .value {{ font-size: 1.25rem; font-weight: var(--w-strong);
        color: var(--ink); font-variant-numeric: tabular-nums; margin-top: 2px; }}
    .rr-slide ul, .rr-slide ol {{ margin: 0.2rem 0 0.6rem 1.1rem; padding: 0; }}
    .rr-slide ul li, .rr-slide ol li {{
        font-size: 0.92rem; color: var(--ink2); margin-bottom: 0.32rem;
        line-height: 1.52; font-weight: var(--w-body);
    }}

    .rr-evidence-item {{
        border: 1px solid var(--hairline); border-radius: 8px;
        padding: 0.6rem 0.8rem; margin-bottom: 0.6rem; background: var(--surface);
    }}
    .rr-evidence-item .title {{ font-size: 0.86rem; font-weight: var(--w-strong);
        color: var(--ink); }}
    .rr-evidence-item .src {{ font-size: 0.72rem; color: var(--muted);
        margin-bottom: 0.25rem; }}
    .rr-evidence-item .excerpt {{ font-size: 0.8rem; color: var(--ink2);
        line-height: 1.45; }}

    .rr-kv {{ font-size: 0.82rem; color: var(--ink2); margin-bottom: 0.2rem; }}
    .rr-kv b {{ color: var(--muted); font-weight: var(--w-strong);
        font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.04em;
        margin-right: 0.3rem; }}

    /* ---- Chat history tiles ---------------------------------------- */
    div[class*="st-key-tile_"] {{
        position: relative; margin-bottom: 0.35rem;
    }}
    div[class*="st-key-tile_"] .rr-chat-tile {{
        background: var(--surface); border: 1px solid var(--hairline);
        border-radius: 8px; padding: 0.6rem 0.75rem;
        transition: border-color 0.15s;
    }}
    div[class*="st-key-tile_"]:hover .rr-chat-tile {{ border-color: var(--accent); }}
    div[class*="st-key-tile_"] .rr-chat-tile.active {{
        border-color: var(--accent); background: var(--accent-soft);
    }}
    div[class*="st-key-tile_"] .tile-title {{
        font-size: 0.88rem; font-weight: var(--w-strong); color: var(--ink);
        margin-bottom: 0.15rem; line-height: 1.3;
    }}
    div[class*="st-key-tile_"] .tile-preview {{
        font-size: 0.76rem; color: var(--muted); line-height: 1.35;
    }}

    /* The "Open" button (matched by its key prefix) becomes an invisible full overlay.
       Note: :first-of-type cannot be used here — each Streamlit button lives inside its
       own unique wrapper div, so :first-of-type matches every button independently. */
    div[class*="st-key-tile_"] [class*="st-key-sess_"],
    div[class*="st-key-tile_"] [class*="st-key-artbtn_"] {{
        position: absolute; inset: 0; z-index: 1; margin: 0;
    }}
    div[class*="st-key-tile_"] [class*="st-key-sess_"] button,
    div[class*="st-key-tile_"] [class*="st-key-artbtn_"] button {{
        position: absolute; inset: 0; width: 100%; height: 100%;
        opacity: 0 !important; border: none !important;
        background: transparent !important; padding: 0 !important;
        min-height: 0 !important;
    }}

    /* Edit/delete row: float top-right over the tile, hidden until hover. */
    div[class*="st-key-tile_"] [data-testid="stHorizontalBlock"] {{
        position: absolute; top: 0.3rem; right: 0.35rem; z-index: 2;
        width: auto; height: 1.6rem; gap: 0.1rem;
        opacity: 0; transition: opacity 0.15s;
    }}
    div[class*="st-key-tile_"]:hover [data-testid="stHorizontalBlock"] {{ opacity: 1; }}
    div[class*="st-key-tile_"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"] {{
        width: auto !important; flex: none !important; min-width: 0 !important;
        height: 100% !important;
    }}
    div[class*="st-key-tile_"] [data-testid="stHorizontalBlock"] [data-testid="stColumn"] [data-testid="stVerticalBlock"] {{
        height: 100% !important;
    }}
    div[class*="st-key-tile_"] [data-testid="stHorizontalBlock"] [data-testid="stElementContainer"] {{
        height: 100% !important;
    }}
    div[class*="st-key-tile_"] [data-testid="stHorizontalBlock"] [data-testid="stButton"] {{
        height: 100% !important;
    }}
    div[class*="st-key-tile_"] [data-testid="stHorizontalBlock"] button {{
        height: 100% !important;
        padding: 0.15rem 0.3rem !important; min-height: 0 !important;
        font-size: 0.75rem !important; border: none !important;
        background: var(--surface) !important; color: var(--muted) !important;
        border-radius: 4px !important; line-height: 1 !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.15);
    }}
    div[class*="st-key-tile_"] [data-testid="stHorizontalBlock"] button:hover {{
        color: var(--accent) !important; background: var(--accent-soft) !important;
    }}

    {_rainbow_rules() if theme == "rainbow" else ""}
    {_responsive_rules()}
    </style>
    """

    if theme == "dark":
        css += """
    <style>
    /* Dark mode explicit fixes: ensure no text is invisible */
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] div,
    [data-testid="stRadio"] label p,
    [role="radiogroup"] label p,
    [data-testid="stToggle"] label p,
    [data-testid="stCaptionContainer"] p,
    .stCaption,
    [data-testid="stSelectbox"] label,
    [data-testid="stSelectbox"] div[data-baseweb="select"] span,
    [data-baseweb="select"] [data-testid="stMarkdownContainer"] p,
    .stMarkdown p, .stMarkdown li, .stMarkdown span {
        color: var(--ink) !important;
    }
    [data-testid="stPageLink"] a { color: var(--ink2) !important; }
    [data-testid="stPageLink"] a:hover { color: var(--accent) !important; }
    [data-testid="stPageLink"] a[aria-current="page"],
    [data-testid="stPageLink"] a[aria-current="page"] p {
        color: var(--accent) !important;
    }
    .rr-brand { color: var(--ink) !important; }
    .rr-brand small { color: var(--muted) !important; }
    [data-testid="stStatusWidget"] p,
    [data-testid="stStatusWidget"] span,
    [data-testid="stStatusWidget"] div { color: var(--ink) !important; }
    .stAlert p, .stAlert span { color: var(--ink) !important; }
    </style>
    """

    st.markdown(css, unsafe_allow_html=True)
