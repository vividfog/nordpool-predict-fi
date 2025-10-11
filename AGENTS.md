# AGENT PLAYBOOK

## Environment & Tooling
- Python app; activate local env with `source .venv/bin/activate`, install deps via `uv pip install -r requirements.txt`.
- Primary entrypoint `nordpool_predict_fi.py` (CLI flags: `--predict`, `--deploy`, `--narrate`, `--commit`, `--dump`).
- Data stored in SQLite (`data/prediction.db`, `data/archive.db`); helper utilities live in `util/`.
- Tests: `pytest tests -q` (no live API calls; heavy I/O mocked). Pytest pinned in `requirements.txt`.
- Logging handled by `util/logger.py` (Rich console + rotating files under `logs/`).

## Core Workflow
1. Load env vars from `.env.local` (critical: `DATA_FOLDER_PATH`, `DEPLOY_FOLDER_PATH`, `DB_PATH`, API keys, FMI station lists).
2. `nordpool_predict_fi.py --predict` pipeline:
   - Query DB (`util/sql.py`), prune to recent window.
   - Enrich via chain: `update_wind_speed`, `update_temperature`, `update_nuclear`, `update_import_capacity`, `update_eu_ws`, `update_windpower`, `entso_e_nuclear`, `update_spot`, `update_holidays`, `update_solar`.
   - Train volatility model (`util/volatility_xgb.py`), annotate data.
   - Train price model (`util/train_xgb.py`, XGBoost regressor with cyclic features).
   - Scale spike hours (`util/scaler.py`), emit debug summaries.
   - Optional commit ⇒ `db_update` + snapshot archive; deploy ⇒ JSON dumps in `deploy/`.
   - Narration via `util/llm.py` (LLM API required; uses `util/llm_prompts.py`).

## Data Enrichment Patterns
- All API fetchers convert to UTC timestamps; merges cleaned by `util.dataframes.coalesce_merged_columns`.
- FMI helpers: `_update_station_series` fetches forecast/history, linear interpolation, deduped index.
- Fingrid nuclear: fetch in 3-min cadence, resample hourly, forward-fill gaps.
- Wind model (`util/fingrid_windpower_xgb.py`) blends Fingrid measurements, forecasts, capacity, then infers missing hours with an in-memory XGB regressor (training artifacts generated only by offline experiments in `data/create/91_model_experiments`).
- Import capacity uses JAO API; merges border lines into `SE1_FI`, `SE3_FI`, `EE_FI`, total column `ImportCapacityMW`.
- Spot prices from sahkotin.fi with cubic interpolation; scaler highlights low-wind, high-price hours for frontend.

## Modeling Notes
- Price model trained fresh in-memory each run (`util/train_xgb.py`); no model files written. Hyperparams tracked there; GPU auto-enabled via `util/xgb_utils.configure_cuda`.
- Wind-power gap filler also retrains in-memory before inference; persisting models is handled only by experimental scripts under `data/create/`.
- Feature sets include weather station temps (`t_*`), wind speeds (`ws_*`), irradiance summary stats, transmission caps, wind power, holiday flags.
- Volatility classifier (XGB) aggregates daily stats; outputs `volatile_likelihood` (currently optional in feature set, always present in DF).

## Deploy & Frontend
- `deploy/` hosts Firebase-ready static site; predictions published as `prediction.json`, `prediction_full.json`, `averages.json`, `windpower.json`.
- JS (`deploy/scripts.js`) selects data source based on hostname, offers Home Assistant configs in YAML.
- Historical snapshots rotated via `util.eval.rotate_snapshots`; evaluation tooling in `nordpool_eval_fi.py` writes reports to `deploy/evals/`.

## Testing & Validation Targets
- Unit coverage focuses on merge helpers, FMI/Fingrid update logic, price scaling, and spot integration (see `tests/`).
- Typical smoke test: run `nordpool_predict_fi.py --predict` with sanctioned API keys; verify deploy outputs and log for warnings.
- When adding data sources: extend enrichment chain, create corresponding tests mocking API responses, ensure new columns seeded in SQLite before training.

## Styling & Conventions
- Prefer pandas pipelining with explicit timezone handling (`tz='UTC'`); use `pd.to_datetime(..., utc=True)` everywhere.
- API clients incorporate cautious rate limiting (`time.sleep` between requests).
- Logs via `logger.info`/`warning`; avoid bare prints outside Rich context.
- Shared helpers live in `util/` and should stay dependency-light; reuse `coalesce_merged_columns` after merges.
- JSON outputs keep `ensure_ascii=False`; timestamps serialized as UNIX ms for frontend consumption.
- Structure long code blocks with lightweight folding anchors: `# region title` (single word or two_word, up to 3; keep terse for minimap scan). For deep sections inside a large function use escalating underscores: `# region _subtopic`, `# region __subpart`. No closing marker (omit `endregion`), rely on start tags only; keep them sparse, semantic, and consistent.
