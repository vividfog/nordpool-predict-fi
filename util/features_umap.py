import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from umap import UMAP

from .logger import logger
from .holidays import update_holidays


GROUP_DEFS = {
    'calendar': {
        'fi': 'Kalenteri- ja kellomuuttujat',
        'en': 'Calendar and time features',
        'color': '#6c757d',
    },
    'generation': {
        'fi': 'Tuotanto',
        'en': 'Generation',
        'color': '#1f77b4',
    },
    'transmission': {
        'fi': 'Siirtokapasiteetit',
        'en': 'Transmission capacity',
        'color': '#ff7f0e',
    },
    'solar': {
        'fi': 'Aurinko',
        'en': 'Solar irradiance',
        'color': '#f1c40f',
    },
    'temperature': {
        'fi': 'Lämpötila (FMI)',
        'en': 'Temperature (FMI)',
        'color': '#d62728',
    },
    'wind_speed': {
        'fi': 'Tuulen nopeus (FMI)',
        'en': 'Wind speed (FMI)',
        'color': '#17becf',
    },
    'baltic_wind': {
        'fi': 'Itämeren tuuli (Open-Meteo)',
        'en': 'Baltic wind (Open-Meteo)',
        'color': '#2ca02c',
    },
}


def _categorize_feature(name: str) -> str:
    if name in {'year', 'day_of_week_sin', 'day_of_week_cos', 'hour_sin', 'hour_cos', 'holiday'}:
        return 'calendar'
    if name in {'NuclearPowerMW', 'WindPowerMW'}:
        return 'generation'
    if name in {'ImportCapacityMW', 'SE1_FI', 'SE3_FI', 'EE_FI'}:
        return 'transmission'
    if name in {'sum_irradiance', 'mean_irradiance', 'std_irradiance', 'min_irradiance', 'max_irradiance'}:
        return 'solar'
    if name.startswith('t_') or name in {'temp_mean', 'temp_variance'}:
        return 'temperature'
    if name.startswith('ws_'):
        return 'wind_speed'
    if name.startswith('eu_ws_'):
        return 'baltic_wind'
    return 'calendar'


def _value_to_float(value):
    if pd.isna(value):
        return None
    try:
        return float(value)
    except Exception:
        return None


def build_feature_embedding(df: pd.DataFrame, fmisid_ws, fmisid_t, deploy_folder_path: str,
                            output_filename: str = 'feature_embedding.json') -> str | None:
    if df.empty:
        logger.warning("Feature embedding skipped: dataframe empty")
        return None

    frame = df.copy()
    frame['timestamp'] = pd.to_datetime(frame['timestamp'], utc=True, errors='coerce')
    frame = frame.dropna(subset=['timestamp'])
    if frame.empty:
        logger.warning("Feature embedding skipped: timestamps missing after cleanup")
        return None

    frame.sort_values('timestamp', inplace=True)
    frame = update_holidays(frame)

    frame['year'] = frame['timestamp'].dt.year
    frame['day_of_week'] = frame['timestamp'].dt.dayofweek + 1
    frame['hour'] = frame['timestamp'].dt.hour
    frame['day_of_week_sin'] = np.sin(2 * np.pi * frame['day_of_week'] / 7)
    frame['day_of_week_cos'] = np.cos(2 * np.pi * frame['day_of_week'] / 7)
    frame['hour_sin'] = np.sin(2 * np.pi * frame['hour'] / 24)
    frame['hour_cos'] = np.cos(2 * np.pi * frame['hour'] / 24)

    available_t = [col for col in fmisid_t if col in frame.columns]
    available_ws = [col for col in fmisid_ws if col in frame.columns]

    if available_t:
        frame['temp_mean'] = frame[available_t].mean(axis=1)
        frame['temp_variance'] = frame[available_t].var(axis=1)
    else:
        frame['temp_mean'] = np.nan
        frame['temp_variance'] = np.nan

    feature_columns = [
        'year', 'day_of_week_sin', 'day_of_week_cos', 'hour_sin', 'hour_cos',
        'NuclearPowerMW', 'ImportCapacityMW', 'WindPowerMW',
        'temp_mean', 'temp_variance', 'holiday',
        'sum_irradiance', 'mean_irradiance', 'std_irradiance', 'min_irradiance', 'max_irradiance',
        'SE1_FI', 'SE3_FI', 'EE_FI',
    ] + available_t + available_ws + [col for col in frame.columns if col.startswith('eu_ws_')]

    # Remove duplicates while preserving order
    seen = set()
    ordered_features = []
    for col in feature_columns:
        if col not in seen:
            ordered_features.append(col)
            seen.add(col)

    available_features = [col for col in ordered_features if col in frame.columns]
    missing_features = sorted(set(ordered_features) - set(available_features))
    if missing_features:
        logger.info("Feature embedding missing columns skipped: %s", ", ".join(missing_features))

    if 'Price_cpkWh' not in frame.columns:
        logger.warning("Feature embedding skipped: Price_cpkWh missing")
        return None

    use_columns = available_features + ['Price_cpkWh']
    subset = frame[use_columns].apply(pd.to_numeric, errors='coerce')
    subset = subset.dropna()
    if subset.empty:
        logger.warning("Feature embedding skipped: insufficient clean data")
        return None

    feature_matrix = subset[available_features]
    stds = feature_matrix.std(axis=0, ddof=0)
    non_constant = stds[stds > 0].index.tolist()
    if len(non_constant) < 3:
        logger.warning("Feature embedding skipped: <3 non-constant features")
        return None

    feature_matrix = feature_matrix[non_constant]
    zscore = (feature_matrix - feature_matrix.mean(axis=0)) / feature_matrix.std(axis=0, ddof=0)
    zscore = zscore.fillna(0.0)

    transpose_matrix = zscore.T.values
    n_neighbors = min(10, max(2, transpose_matrix.shape[0] - 1))
    reducer = UMAP(
        n_components=3,
        metric='correlation',
        n_neighbors=n_neighbors,
        min_dist=0.15,
        random_state=42,
    )
    embedding = reducer.fit_transform(transpose_matrix)

    min_vals = embedding.min(axis=0)
    max_vals = embedding.max(axis=0)
    ranges = np.where((max_vals - min_vals) == 0, 1.0, max_vals - min_vals)
    normalized = (embedding - min_vals) / ranges

    correlations = subset[non_constant].corrwith(subset['Price_cpkWh']).fillna(0.0)
    latest_row = subset.iloc[-1]

    features_payload = []
    for idx, name in enumerate(non_constant):
        group = _categorize_feature(name)
        features_payload.append({
            'id': name,
            'label': name,
            'group': group,
            'x': float(normalized[idx, 0]),
            'y': float(normalized[idx, 1]),
            'z': float(normalized[idx, 2]),
            'corr_price': float(correlations.get(name, 0.0)),
            'mean': _value_to_float(feature_matrix[name].mean()),
            'std': _value_to_float(feature_matrix[name].std(ddof=0)),
            'latest': _value_to_float(latest_row.get(name)),
        })

    payload = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'umap': {
            'n_neighbors': n_neighbors,
            'metric': 'correlation',
            'min_dist': 0.15,
            'random_state': 42,
        },
        'groups': GROUP_DEFS,
        'features': features_payload,
        'samples': len(subset),
    }

    os.makedirs(deploy_folder_path, exist_ok=True)
    output_path = os.path.join(deploy_folder_path, output_filename)
    with open(output_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    logger.info("Feature embedding saved to %s (%d features)", output_path, len(features_payload))
    return output_path


__all__ = ['build_feature_embedding']
