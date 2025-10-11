# FMI Backfill Toolkit

Utilities for keeping Finnish Meteorological Institute (FMI) station data complete in `data/prediction.db`. When FMI swaps stations or leaves gaps, use this toolkit to validate candidates, backfill history, and sanity‑check coverage before adding new FMISIDs to `.env.local`.

> Historical domain (as of 2025‑10‑11): `2023-01-01T00:00:00+00:00` → `2025-10-17T23:00:00+00:00` (truncated to the current UTC hour when commands run).  
> Logs and study artefacts: `data/create/10_weather_fetch_history/validation_logs/`.

## CLI Overview: `manage_fmi_station.py`

Rich-enabled CLI with three workflows.

### Common Behaviour

- Always run from the repository root with `PYTHONPATH=.` so Python imports the project `util` modules (this avoids the stub inside `data/create/10_weather_fetch_history/util/`).
- Reads `DB_PATH` and FMISIDs from `.env.local` (override with `--env-file` or `--db-path`).
- Operations auto-clamp to available history (no future timestamps).
- Uses throttled FMI calls (`util.fmi.get_history`) and writes via `util.sql.db_update`.
- Automatically creates timestamped backups (`*.bak`) before any write unless `--no-backup` is set.

### Subcommands

| Command | Purpose | Typical Flags |
| --- | --- | --- |
| `validate` | Inspect a specific window, without writing. | `--fmisid`, `--start`, `--end` |
| `backfill` | Fetch history + update DB (with backups & SQL preview options). | `--fmisid`, `--start`, `--end`, `--dry-run`, `--keep-sql`, `--no-backup` |
| `audit` | Sample random windows from the full historical range; ideal for coverage studies. | `--fmisid`, `--all`, `--samples`, `--window-days`, `--seed`, `--ensure-columns` |

All commands accept `--chunk-days` to control FMI window size (default 7).

### Example Usage

All commands below assume the repo root as the working directory.

```bash
# Audit five 7-day windows sampled across the DB span (first step for every candidate).
PYTHONPATH=. .venv/bin/python -m data.create.10_weather_fetch_history.manage_fmi_station \
  --env-file .env.local \
  audit \
  --fmisid 101786 \
  --samples 5 \
  --window-days 7 \
  --seed 42

# Audit every FMISID currently configured in .env.local and print a combined summary.
PYTHONPATH=. .venv/bin/python -m data.create.10_weather_fetch_history.manage_fmi_station \
  --env-file .env.local \
  audit \
  --all \
  --samples 3 \
  --window-days 7

# Validate a specific window after audit, without touching the DB.
PYTHONPATH=. .venv/bin/python -m data.create.10_weather_fetch_history.manage_fmi_station \
  --env-file .env.local \
  validate \
  --fmisid 101783 \
  --start 2024-10-01T00:00:00 \
  --end   2024-10-31T23:00:00

# Backfill after validation (dry-run first, then real update with optional SQL dump).
PYTHONPATH=. .venv/bin/python -m data.create.10_weather_fetch_history.manage_fmi_station \
  --env-file .env.local \
  backfill \
  --fmisid 101783 \
  --start 2024-10-01T00:00:00 \
  --end   2024-10-31T23:00:00 \
  --dry-run

PYTHONPATH=. .venv/bin/python -m data.create.10_weather_fetch_history.manage_fmi_station \
  --env-file .env.local \
  backfill \
  --fmisid 101783 \
  --start 2024-10-01T00:00:00 \
  --end   2024-10-31T23:00:00 \
  --keep-sql data/create/10_weather_fetch_history/101783_backfill.sql
```

Audit output includes per-sample tables plus aggregate coverage (`sampled hours`, `missing hours`, `% coverage`). When `--all` is enabled you also get a per-station summary (worst coverage first) and combined coverage table, making it easy to verify that `.env.local` only references healthy stations.

### Exit Artefacts

| Artefact | Location | Description |
| --- | --- | --- |
| SQL preview | `--keep-sql <path>` | Bulk update script for review/commit. |
| Backups | `<db>.YYYYMMDD-HHMMSS.bak` | Auto-created unless `--no-backup`. |
| Logs | `validation_logs/` | Raw Rich output for each run (`validate_*`, `audit_*`). |
| Studies | `2025-10-11-backfill.md` | Latest curated coverage study. |

## Suggested Workflow

1. **Discover candidates** via the [FMI observation directory](https://www.ilmatieteenlaitos.fi/havaintoasemat) and confirm they report both `TA_PT1H_AVG` and `WS_PT1H_AVG`.
2. **Audit first** (mandatory): run the module form `audit` command shown above. Review aggregate coverage and warnings. Skip the station if wind coverage is patchy (< 95 %) or FMI returns empty history.
3. **Decide & prepare**: for promising stations, capture the audit log (`validation_logs/`) and note any residual gaps.
4. **Back up the DB manually** (e.g. `cp data/prediction.db data/prediction.db.$(date -u +%Y%m%d-%H%M%S).pre_fmi.bak`) before any write.
5. **Backfill** using the module invocation. Run once with `--dry-run`, then without it (optionally `--keep-sql` for review). The CLI will also create its own timestamped `.bak`.
6. **Verify schema**: run a quick `PRAGMA table_info` snippet to ensure `t_<FMISID>` and `ws_<FMISID>` now exist. Only continue when the columns are visible.
7. **Update `.env.local`** to append the FMISID to both `FMISID_WS` and `FMISID_T`.
8. **Run the pipeline** (`nordpool_predict_fi.py --predict`, add `--commit/--deploy` as needed) and monitor Rich logs for any lingering FMI warnings.
9. **Optional**: rerun `audit` post-backfill to confirm coverage across the extended history.

## Safety & Tips

- Prefer Rich output for situational awareness; pipelines still log to rotating files via `util.logger`.
- Sampling uses the current DB range; if the DB grows, re-run the audit to include new history.
- Keep old SQL previews and backup files—they’re handy to revert manual mistakes.
- `fmi_fetch_history.py` remains for quick SQL dumps, but the Rich CLI supersedes it for most tasks.
