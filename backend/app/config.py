"""Réglages de l'application (variables d'environnement / fichier .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # live = sources réelles uniquement ; mock = fixtures + météo synthétique ;
    # auto = live avec repli automatique sur mock en cas d'erreur réseau.
    data_mode: Literal["auto", "live", "mock"] = "auto"

    http_timeout_s: float = 5.0
    # après un échec live en mode auto, on ne retente pas la source pendant ce délai
    live_retry_after_s: float = 120.0

    # --- Open-Meteo (libre, sans clé) ---
    open_meteo_base_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_elevation_url: str = "https://api.open-meteo.com/v1/elevation"
    open_meteo_models: str = "meteofrance_arome_france_hd,icon_d2,ecmwf_ifs025"
    open_meteo_grid_model: str = "best_match"
    open_meteo_api_key: str | None = None  # uniquement pour l'offre commerciale (customer-api)

    # --- FFVL (optionnel, clé à demander à la FFVL) ---
    ffvl_api_key: str | None = None
    ffvl_api_url: str = "https://data.ffvl.fr/api"

    # --- ParaglidingEarth (libre) ---
    paraglidingearth_url: str = "https://www.paraglidingearth.com/api/geojson"

    # --- Pioupiou / OpenWindMap (libre) ---
    pioupiou_url: str = "https://api.pioupiou.fr/v1/live/all"

    # --- OpenAIP (optionnel, clé gratuite) ---
    openaip_api_key: str | None = None
    openaip_url: str = "https://api.core.openaip.net/api"

    # --- Biodiv'Sports (zones sensibles faune, libre) ---
    biodivsports_url: str = "https://biodiv-sports.fr/api/v2"

    # --- Fichiers OpenAir locaux (espaces aériens sans clé) ---
    airspace_openair_dir: Path = BACKEND_DIR / "data" / "airspaces"

    # --- SpotAir / Météo-Parapente : pas d'API publique, nécessitent un accord ---
    spotair_api_url: str | None = None
    spotair_api_key: str | None = None
    meteo_parapente_api_url: str | None = None
    meteo_parapente_api_key: str | None = None

    # --- Cache mémoire (secondes) ---
    cache_ttl_forecast_s: int = 30 * 60
    cache_ttl_sites_s: int = 24 * 3600
    cache_ttl_beacons_s: int = 2 * 60
    cache_ttl_plans_s: int = 6 * 3600
    cache_ttl_airspaces_s: int = 24 * 3600
    cache_ttl_sensitive_s: int = 24 * 3600
    cache_ttl_elevation_s: int = 7 * 24 * 3600

    # --- Météo synthétique (mode mock) ---
    # Force un scénario pour toutes les dates (ex. "thermal_good", "afternoon_storms"…), vide = cycle auto.
    synthetic_scenario: str | None = None

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    log_level: str = "INFO"

    @property
    def open_meteo_model_list(self) -> list[str]:
        return [m.strip() for m in self.open_meteo_models.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
