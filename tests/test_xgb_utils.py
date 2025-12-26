"""
Tests for util/xgb_utils.py - XGBoost utility functions.
"""
import numpy as np
import pandas as pd
import xgboost as xgb

from util import xgb_utils


class TestHasCudaSupport:
    """Tests for _has_cuda_support function."""

    def test_returns_boolean(self):
        """Verify _has_cuda_support returns a boolean."""
        result = xgb_utils._has_cuda_support()
        assert isinstance(result, bool)


class TestConfigureCuda:
    """Tests for configure_cuda function."""

    def test_returns_dict(self):
        """Verify configure_cuda returns a dictionary."""
        params = {"max_depth": 6, "learning_rate": 0.1}
        result = xgb_utils.configure_cuda(params)
        assert isinstance(result, dict)

    def test_adds_cuda_settings_when_supported(self, monkeypatch):
        """Verify CUDA settings are added when supported."""
        # Mock CUDA as supported
        monkeypatch.setattr(xgb_utils, "_has_cuda_support", lambda: True)

        params = {"max_depth": 6, "learning_rate": 0.1}
        result = xgb_utils.configure_cuda(params)

        # Should add CUDA-specific settings
        assert "tree_method" in result
        assert "device" in result
        assert result["device"] == "cuda"

    def test_preserves_original_params_when_cuda_not_supported(self, monkeypatch):
        """Verify original params are preserved when CUDA not available."""
        # Mock CUDA as not supported
        monkeypatch.setattr(xgb_utils, "_has_cuda_support", lambda: False)

        params = {"max_depth": 6, "learning_rate": 0.1, "predictor": "cpu_predictor"}
        result = xgb_utils.configure_cuda(params)

        # Should preserve original params (predictor stays when CUDA not available)
        assert result["max_depth"] == 6
        assert result["learning_rate"] == 0.1
        # predictor should be preserved when CUDA is not supported
        assert "predictor" in result

    def test_returns_copy_not_original(self, monkeypatch):
        """Verify configure_cuda returns a copy, not the original."""
        monkeypatch.setattr(xgb_utils, "_has_cuda_support", lambda: True)

        params = {"max_depth": 6}
        result = xgb_utils.configure_cuda(params)

        # Modifying result should not affect original
        result["max_depth"] = 10
        assert params["max_depth"] == 6


class TestToDmatrix:
    """Tests for _to_dmatrix function."""

    def test_returns_dmatrix_for_dataframe(self):
        """Verify _to_dmatrix converts DataFrame to DMatrix."""
        df = pd.DataFrame({
            "feature1": [1.0, 2.0, 3.0],
            "feature2": [4.0, 5.0, 6.0]
        })

        result = xgb_utils._to_dmatrix(df)

        assert isinstance(result, xgb.DMatrix)

    def test_returns_dmatrix_for_numpy_array(self):
        """Verify _to_dmatrix converts numpy array to DMatrix."""
        arr = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])

        result = xgb_utils._to_dmatrix(arr)

        assert isinstance(result, xgb.DMatrix)

    def test_passes_through_existing_dmatrix(self):
        """Verify _to_dmatrix passes through existing DMatrix."""
        arr = np.array([[1.0, 2.0], [3.0, 4.0]])
        original = xgb.DMatrix(arr)

        result = xgb_utils._to_dmatrix(original)

        assert result is original

    def test_preserves_feature_names(self):
        """Verify feature names are preserved from DataFrame."""
        df = pd.DataFrame({
            "temperature": [1.0, 2.0, 3.0],
            "wind_speed": [4.0, 5.0, 6.0]
        })

        dmatrix = xgb_utils._to_dmatrix(df)

        # XGBoost stores feature names internally
        assert dmatrix.feature_names == ["temperature", "wind_speed"]

    def test_handles_custom_feature_names(self):
        """Verify custom feature names are applied."""
        arr = np.array([[1.0, 2.0], [3.0, 4.0]])

        dmatrix = xgb_utils._to_dmatrix(arr, feature_names=["t", "ws"])

        assert dmatrix.feature_names == ["t", "ws"]

    def test_handles_iterable(self):
        """Verify _to_dmatrix handles iterable inputs."""
        data = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]

        result = xgb_utils._to_dmatrix(data)

        assert isinstance(result, xgb.DMatrix)


class TestBoosterPredict:
    """Tests for booster_predict function."""

    def test_returns_predictions(self):
        """Verify booster_predict returns predictions."""
        # Create a simple model
        df = pd.DataFrame({
            "feature": [1.0, 2.0, 3.0, 4.0, 5.0]
        })
        labels = [1.0, 2.0, 3.0, 4.0, 5.0]

        model = xgb.XGBRegressor(n_estimators=2, max_depth=1, random_state=42)
        model.fit(df, labels)

        # Predict using booster_predict
        test_data = pd.DataFrame({"feature": [1.5, 2.5, 3.5]})
        result = xgb_utils.booster_predict(model, test_data)

        assert isinstance(result, np.ndarray)
        assert len(result) == 3

    def test_handles_feature_names(self):
        """Verify booster_predict respects feature_names parameter."""
        df = pd.DataFrame({
            "temp": [1.0, 2.0, 3.0, 4.0, 5.0]
        })
        labels = [1.0, 2.0, 3.0, 4.0, 5.0]

        model = xgb.XGBRegressor(n_estimators=2, max_depth=1, random_state=42)
        model.fit(df, labels)

        test_data = np.array([[1.5], [2.5], [3.5]])
        result = xgb_utils.booster_predict(model, test_data, feature_names=["temp"])

        assert isinstance(result, np.ndarray)

    def test_works_with_dmatrix_input(self):
        """Verify booster_predict works with DMatrix input."""
        df = pd.DataFrame({
            "feature": [1.0, 2.0, 3.0, 4.0, 5.0]
        })
        labels = [1.0, 2.0, 3.0, 4.0, 5.0]

        model = xgb.XGBRegressor(n_estimators=2, max_depth=1, random_state=42)
        model.fit(df, labels)

        dmatrix = xgb.DMatrix(df)
        result = xgb_utils.booster_predict(model, dmatrix)

        assert isinstance(result, np.ndarray)
        assert len(result) == 5
