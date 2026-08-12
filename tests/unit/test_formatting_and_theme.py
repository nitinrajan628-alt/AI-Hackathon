"""Year/ordinal formatting and appearance-mode token coverage."""
import pandas as pd
import pytest

from services.chart_service import PALETTES, build_chart_spec, build_figure
from services.formatting import fmt_year, is_integer_field, is_year_field
from ui.theme import THEMES, TOKENS


@pytest.mark.parametrize("value,expected", [
    (2026, "2026"), (2026.0, "2026"), ("2026", "2026"),
    (2024.4, "2024"), (1999, "1999"),
])
def test_years_render_without_separators_or_decimals(value, expected):
    out = fmt_year(value)
    assert out == expected
    assert "," not in out and "." not in out


def test_year_field_detection():
    assert is_year_field("accident_year")
    assert is_integer_field("accident_year")
    assert is_integer_field("development_period_quarters")
    assert not is_year_field("total_reserve")
    assert not is_integer_field("finance_class")


def test_chart_year_axis_labels_are_bare_strings():
    """A year grouping must reach Plotly as category labels, so the axis can
    never render 2,026 or 2026.0."""
    from services.diagnostics import ShapedResult
    df = pd.DataFrame({"accident_year": [2024, 2025, 2026],
                       "total_reserve": [117e6, 178e6, 121e6]})
    shaped = ShapedResult(df=df, operation="aggregate", dataset="results",
                          measures=["total_reserve"], group_by=["accident_year"],
                          periods=["2026-Q2"], period_labels=["2026 Q2"],
                          unit="GBP", total_row_count=3)
    spec = build_chart_spec(shaped, "auto")
    assert spec is not None
    fig = build_figure(spec, "light")
    xs = list(fig.data[0].x)
    assert xs == ["2024", "2025", "2026"]
    assert all(isinstance(x, str) for x in xs)


def test_every_theme_has_a_complete_token_set():
    required = set(TOKENS["light"])
    for theme in THEMES:
        assert theme in TOKENS, theme
        missing = required - set(TOKENS[theme])
        assert not missing, f"{theme} missing tokens: {missing}"


def test_dark_mode_uses_lighter_type_weights():
    light, dark = TOKENS["light"], TOKENS["dark"]
    for role in ("weight_body", "weight_medium", "weight_strong", "weight_heading"):
        assert int(dark[role]) < int(light[role]), role


def test_every_theme_has_a_chart_palette():
    for theme in THEMES:
        assert theme in PALETTES, theme
        palette = PALETTES[theme]
        assert len(palette["categorical"]) == 8
        for key in ("current", "prior", "positive", "negative", "grid", "ink"):
            assert palette[key].startswith("#")


def test_rainbow_is_a_distinct_meme_palette():
    """Rainbow deliberately abandons the restrained palette; it must not be
    mistaken for, or silently reuse, the serious light theme."""
    assert PALETTES["rainbow"]["categorical"] != PALETTES["light"]["categorical"]
    assert len(set(PALETTES["rainbow"]["categorical"])) == 8


def test_rainbow_chart_surface_stays_readable():
    """The page animates behind the chart, so the plotting surface must stay
    near-opaque or the axes become unreadable."""
    surface = PALETTES["rainbow"]["surface"]
    assert surface.startswith("rgba(255,255,255")
    alpha = float(surface.rstrip(")").split(",")[-1])
    assert alpha >= 0.9


def test_rainbow_movement_colours_remain_opposed():
    """Even in meme mode, positive and negative must not be the same hue."""
    palette = PALETTES["rainbow"]
    assert palette["positive"] != palette["negative"]


def test_only_rainbow_uses_the_joke_typeface():
    from ui.theme import FONTS
    assert "Comic Sans" in FONTS["rainbow"]
    assert "Comic Sans" not in FONTS["light"]
    assert "Comic Sans" not in FONTS["dark"]
