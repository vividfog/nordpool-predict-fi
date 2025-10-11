from datetime import datetime, timedelta, timezone

import pandas as pd

from util import sahkotin


def test_update_spot_merges_latest_prices(monkeypatch):
    base_ts = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    price_df = pd.DataFrame(
        {
            "timestamp": [
                base_ts + timedelta(hours=offset)
                for offset in range(3)
            ],
            "Price_cpkWh": [4.5, 5.0, 6.0],
        }
    )

    def fake_fetch(start, end):
        return price_df

    monkeypatch.setattr(sahkotin, "fetch_electricity_price_data", fake_fetch)

    df = pd.DataFrame({"timestamp": pd.to_datetime([base_ts + timedelta(hours=i) for i in range(3)], utc=True)})

    result = sahkotin.update_spot(df.copy())

    assert list(result["Price_cpkWh"]) == [4.5, 5.0, 6.0]
    assert not any(col.endswith(("_x", "_y")) for col in result.columns)
