"""Constats (« findings ») évalués niveau par niveau.

Un constat porte une valeur et, selon le cas, des limites par niveau (§2 du cahier des charges) ou
un statut absolu (no-go §3, caution, info). À partir de la liste des constats d'un plan on obtient :
- pour un niveau donné : no-go / bande marginale (80-100 % du seuil) / sous-score 0..100 ;
- la difficulté du plan = plus petit niveau pour lequel aucun seuil n'est dépassé ;
- les `Risk` du plan pour le niveau du pilote.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.engine import rules
from app.models import Risk

LEVELS = rules.LEVELS


def ratio_subscore(ratio: float) -> float:
    """100 jusqu'à 50 % du seuil, 40 à 80 %, 0 au seuil (§9.2)."""
    if ratio <= 0.5:
        return 100.0
    if ratio <= rules.MARGINAL_BAND:
        return 100.0 - (ratio - 0.5) / (rules.MARGINAL_BAND - 0.5) * 60.0
    if ratio <= 1.0:
        return 40.0 * (1.0 - ratio) / (1.0 - rules.MARGINAL_BAND)
    return 0.0


@dataclass(slots=True)
class Finding:
    code: str
    title: str
    detail: str
    criterion: str | None = None  # critère de score concerné
    value: float | None = None
    limits: dict[str, float | None] | None = None  # seuil par niveau (None = interdit à ce niveau)
    kind: str = "max"  # "max" : échec si valeur > seuil ; "min" : échec si valeur < seuil
    absolute_nogo: bool = False  # danger pour tous les niveaux
    caution: bool = False  # caution fixe (indépendante du niveau)
    info: bool = False
    blocks_go: bool = True  # une caution qui empêche le « go »
    band: bool = True  # bande marginale 80-100 % applicable
    level_titles: dict[str, str] = field(default_factory=dict)

    # --- évaluation par niveau ------------------------------------------------------------------
    def limit(self, level: str) -> float | None:
        if self.limits is None:
            return None
        return self.limits.get(level)

    def fails(self, level: str) -> bool:
        if self.absolute_nogo:
            return True
        if self.limits is None or self.value is None:
            return False
        lim = self.limit(level)
        if lim is None:
            return True
        return self.value > lim if self.kind == "max" else self.value < lim

    def ratio(self, level: str) -> float | None:
        lim = self.limit(level)
        if self.value is None or lim is None:
            return None
        if self.kind == "max":
            return self.value / lim if lim > 0 else (0.0 if self.value <= 0 else 9.9)
        # min : ratio > 1 si sous le seuil
        return lim / self.value if self.value > 0 else 9.9

    def in_band(self, level: str) -> bool:
        if not self.band or self.limits is None:
            return False
        r = self.ratio(level)
        return r is not None and rules.MARGINAL_BAND <= r <= 1.0

    def subscore(self, level: str) -> float | None:
        if self.absolute_nogo:
            return 0.0
        if self.limits is None:
            return None
        if self.fails(level):
            return 0.0
        r = self.ratio(level)
        return None if r is None else ratio_subscore(r)

    def risk_level(self, level: str) -> str | None:
        if self.fails(level):
            return "danger"
        if self.caution or self.in_band(level):
            return "caution"
        if self.info:
            return "info"
        return None

    def to_risk(self, level: str) -> Risk | None:
        lvl = self.risk_level(level)
        if lvl is None:
            return None
        return Risk(code=self.code, level=lvl, title=self.level_titles.get(lvl, self.title), detail=self.detail)


def smallest_passing_level(findings: list[Finding]) -> str | None:
    for lvl in LEVELS:
        if not any(f.fails(lvl) for f in findings):
            return lvl
    return None


def failing(findings: list[Finding], level: str) -> list[Finding]:
    return [f for f in findings if f.fails(level)]


def max_level(*levels: str | None) -> str:
    idx = max(rules.level_index(lv) for lv in levels if lv)
    return LEVELS[idx]
