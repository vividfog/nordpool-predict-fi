"""
Utility helpers for configuring XGBoost models with optional CUDA acceleration.
"""

from __future__ import annotations

import ctypes
import json
from typing import Dict


def _has_cuda_support() -> bool:
    """Return True when the installed XGBoost build can use CUDA."""
    try:
        from xgboost.core import _LIB  # type: ignore
    except ImportError:
        return False

    # Prefer the legacy helper when present.
    try:
        from xgboost.core import _has_cuda  # type: ignore
    except ImportError:
        _has_cuda = None  # type: ignore

    if callable(_has_cuda):
        try:
            return bool(_has_cuda())
        except Exception:
            return False

    try:
        info_ptr = ctypes.c_char_p()
        _LIB.XGBuildInfo(ctypes.byref(info_ptr))
        if info_ptr.value is None:
            return False
        info = json.loads(info_ptr.value.decode("utf-8"))
        return bool(info.get("USE_CUDA"))
    except Exception:
        return False


def configure_cuda(params: Dict[str, object], logger=None) -> Dict[str, object]:
    """
    Extend a parameter dictionary with CUDA-specific options when available.

    Args:
        params: Base parameter mapping for an XGBoost estimator.
        logger: Optional logger with .info for status messages.

    Returns:
        Updated parameter dictionary (a shallow copy) with CUDA settings added
        when supported; otherwise identical to the input mapping.
    """
    updated = dict(params)
    if _has_cuda_support():
        updated.pop("predictor", None)
        updated["tree_method"] = "hist"
        updated["device"] = "cuda"
        if logger is not None:
            logger.info("XGBoost: CUDA detected, using GPU acceleration.")
    else:
        if logger is not None:
            logger.info("XGBoost: CUDA not available, using CPU backend.")
    return updated
