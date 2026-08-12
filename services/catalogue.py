"""Catalogue and alias access. The catalogue (config/catalogue.yaml) is the
only source used to map plan identifiers to database tables and columns."""
from __future__ import annotations

from functools import lru_cache

from services.settings import load_yaml


class Catalogue:
    def __init__(self) -> None:
        self.raw = load_yaml("catalogue.yaml")
        self.aliases = load_yaml("aliases.yaml")
        self.datasets: dict = self.raw["datasets"]
        self.dimension_values: dict[str, list[str]] = self.raw["dimension_values"]
        self.ordered_fields: list[str] = self.raw["ordered_fields"]
        self.row_limit_default: int = self.raw["row_limits"]["default"]
        self.row_limit_max: int = self.raw["row_limits"]["max"]
        self.operations: list[str] = self.raw["operations"]

    # -- lookups ------------------------------------------------------------

    def dataset(self, name: str) -> dict:
        return self.datasets[name]

    def table(self, dataset: str) -> str:
        return self.datasets[dataset]["table"]

    def measures(self, dataset: str) -> dict:
        return self.datasets[dataset].get("measures", {})

    def dimensions(self, dataset: str) -> dict:
        return self.datasets[dataset].get("dimensions", {})

    def attributes(self, dataset: str) -> dict:
        return self.datasets[dataset].get("attributes", {})

    def grain(self, dataset: str) -> list[str]:
        return self.datasets[dataset].get("grain", [])

    def measure_label(self, dataset: str, measure: str) -> str:
        return self.measures(dataset).get(measure, {}).get("label", measure)

    def measure_unit(self, dataset: str, measure: str) -> str:
        return self.measures(dataset).get(measure, {}).get("unit", "")

    def dimension_label(self, dataset: str, dim: str) -> str:
        d = self.dimensions(dataset).get(dim) or self.attributes(dataset).get(dim) or {}
        return d.get("label", dim.replace("_", " ").title())

    # -- alias resolution ---------------------------------------------------

    def resolve_measure(self, term: str) -> str | None:
        t = term.strip().lower().replace(" ", "_")
        return self.aliases.get("measures", {}).get(t) or (
            t if any(t in self.measures(ds) for ds in self.datasets) else None)

    def resolve_dimension(self, term: str) -> str | None:
        t = term.strip().lower().replace(" ", "_")
        return self.aliases.get("dimensions", {}).get(t) or (
            t if any(t in self.dimensions(ds) or t in self.attributes(ds)
                     for ds in self.datasets) else None)

    def resolve_value(self, dimension: str, value):
        """Resolve a filter value to its canonical form; None if unknown."""
        if dimension in ("accident_year", "development_period_quarters"):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        if dimension == "review_id":
            return str(value)
        valid = self.dimension_values.get(dimension)
        if valid is None:
            return str(value)
        text = str(value).strip()
        for v in valid:
            if v.lower() == text.lower():
                return v
        alias = self.aliases.get("values", {}).get(dimension, {}).get(text.lower())
        return alias

    def _max_accident_year(self) -> int:
        from services.review_service import list_reviews
        years = [int(r["review_id"][:4]) for r in list_reviews()]
        return max(years) if years else 2026

    # -- condensed catalogue for the planning payload -----------------------

    def condensed(self) -> dict:
        datasets = {}
        for name, ds in self.datasets.items():
            datasets[name] = {
                "description": ds.get("description", ""),
                "measures": {m: spec.get("label", m) for m, spec in ds.get("measures", {}).items()},
                "dimensions": sorted(ds.get("dimensions", {}).keys()),
                "attributes": sorted(ds.get("attributes", {}).keys()),
            }
        # Bounded dimensions list their members; accident year is an ordered
        # numeric dimension, so the planner is given its range instead - without
        # it the model cannot tell that "accident year 2024" is a filter value.
        dimension_info: dict = {d: vals for d, vals in self.dimension_values.items()}
        dimension_info["accident_year"] = {
            "type": "integer year",
            "range": [2017, self._max_accident_year()],
            "note": ("A filterable dimension, not a review period. Review "
                     "periods are quarters such as 2026-Q2."),
        }
        return {
            "datasets": datasets,
            "dimensions": dimension_info,
            "measures": {},
            "operations": self.operations,
            "aliases": {
                "measures": self.aliases.get("measures", {}),
                "dimensions": self.aliases.get("dimensions", {}),
            },
        }


@lru_cache(maxsize=1)
def get_catalogue() -> Catalogue:
    return Catalogue()
