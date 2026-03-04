from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MetricConfig:
    name: str
    entity: str
    places: list[int]
    unit_hint: str
    extra_filter: str = ""


SYKE_ODATA_BASE = "https://rajapinnat.ymparisto.fi/api/Hydrologiarajapinta/1.1/odata"


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def cache_dir() -> Path:
    return Path(__file__).resolve().parent / "cache"


def results_dir() -> Path:
    return Path(__file__).resolve().parent / "results"


def plots_dir() -> Path:
    return Path(__file__).resolve().parent / "plots"


def prediction_db_path() -> Path:
    return project_root() / "data" / "prediction.db"


def metrics() -> list[MetricConfig]:
    # 10 places per metric, picked to have data since 2026-02-21 in earlier checks.
    # Keep this list stable while researching; later we can lock to basin-balanced sets.
    return [
        MetricConfig(
            name="HydroDischarge",
            entity="Virtaama",
            unit_hint="m3/s",
            places=[1351, 1352, 1270, 1271, 1323, 1326, 1389, 1390, 1414, 1415],
        ),
        MetricConfig(
            name="HydroLevel",
            entity="Vedenkorkeus",
            unit_hint="cm (mixed scales across places; treat with care)",
            places=[2458, 2460, 2367, 2368, 2423, 2425, 2521, 2522, 2555, 2556],
        ),
        MetricConfig(
            name="HydroSWE",
            entity="LumiAlue",
            unit_hint="mm",
            places=[196, 200, 159, 160, 183, 185, 226, 228, 232, 233],
        ),
        MetricConfig(
            name="HydroPrecip_5d",
            entity="SadantaAlue",
            extra_filter="Jakso_Id eq 2",
            unit_hint="mm (5-day accumulation)",
            places=[848, 852, 810, 811, 834, 837, 879, 881, 885, 886],
        ),
    ]

