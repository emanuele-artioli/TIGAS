"""Evaluation-only quality metrics."""

from __future__ import annotations

import numpy as np


def rgb_to_luma(image_rgb: np.ndarray) -> np.ndarray:
    """Convert uint8 RGB image to float32 luma in [0, 1]."""
    rgb = image_rgb.astype(np.float32) / 255.0
    return 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]


def ssim_proxy(reference_rgb: np.ndarray, test_rgb: np.ndarray) -> float:
    """Compute a global SSIM proxy between two RGB images.

    This metric is intentionally lightweight for repeated experiment sweeps.
    """
    if reference_rgb.shape != test_rgb.shape:
        raise ValueError("SSIM proxy requires equal image shapes.")

    x = rgb_to_luma(reference_rgb)
    y = rgb_to_luma(test_rgb)

    mu_x = float(np.mean(x))
    mu_y = float(np.mean(y))
    sigma_x2 = float(np.var(x))
    sigma_y2 = float(np.var(y))
    sigma_xy = float(np.mean((x - mu_x) * (y - mu_y)))

    c1 = 0.01 * 0.01
    c2 = 0.03 * 0.03
    numerator = (2.0 * mu_x * mu_y + c1) * (2.0 * sigma_xy + c2)
    denominator = (mu_x * mu_x + mu_y * mu_y + c1) * (sigma_x2 + sigma_y2 + c2)

    if denominator <= 1e-12:
        return 1.0
    value = numerator / denominator
    return float(np.clip(value, -1.0, 1.0))
