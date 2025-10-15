import json
from pathlib import Path

import numpy as np
import pandas as pd

from util.features_umap import build_feature_embedding


def _make_series(base: float, count: int):
    seed = int(abs(base) * 1000) % (2**32 - 1)
    rng = np.random.default_rng(seed=seed)
    return base + rng.standard_normal(count)


def test_build_feature_embedding(tmp_path: Path):
    hours = 96
    timestamps = pd.date_range('2024-01-01', periods=hours, freq='h', tz='UTC')
    frame = pd.DataFrame({
        'timestamp': timestamps,
        'Price_cpkWh': _make_series(12.0, hours),
        'NuclearPowerMW': _make_series(1300.0, hours),
        'ImportCapacityMW': _make_series(1500.0, hours),
        'WindPowerMW': _make_series(1800.0, hours),
        'holiday': np.zeros(hours),
        'sum_irradiance': _make_series(200.0, hours),
        'mean_irradiance': _make_series(100.0, hours),
        'std_irradiance': np.abs(_make_series(15.0, hours)),
        'min_irradiance': _make_series(10.0, hours),
        'max_irradiance': _make_series(250.0, hours),
        'SE1_FI': _make_series(500.0, hours),
        'SE3_FI': _make_series(700.0, hours),
        'EE_FI': _make_series(350.0, hours),
        't_100': _make_series(-3.0, hours),
        't_200': _make_series(1.0, hours),
        'ws_100': _make_series(5.0, hours),
        'eu_ws_DE01': _make_series(7.0, hours),
    })

    output_path = build_feature_embedding(
        frame,
        fmisid_ws=['ws_100'],
        fmisid_t=['t_100', 't_200'],
        deploy_folder_path=str(tmp_path),
    )

    assert output_path is not None
    payload_path = Path(output_path)
    assert payload_path.exists()

    data = json.loads(payload_path.read_text(encoding='utf-8'))
    assert 'features' in data and data['features']
    assert 'groups' in data and 'generation' in data['groups']

    for feature in data['features']:
        assert 0.0 <= feature['x'] <= 1.0
        assert 0.0 <= feature['y'] <= 1.0
        assert 0.0 <= feature['z'] <= 1.0
        assert feature['group'] in data['groups']
