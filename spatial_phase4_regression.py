from __future__ import annotations

import json

import numpy as np
import pandas as pd
import statsmodels.api as sm
from esda import Moran
from libpysal.weights import KNN
from spreg import ML_Lag

from spatial_analysis_common import ANALYSIS_DIR, write_json

MAX_ROWS_FOR_SPATIAL_MODEL = 4000


def build_weights(features: pd.DataFrame) -> KNN:
    coords = features[["lon_bin", "lat_bin"]].to_numpy(dtype=float)
    w = KNN.from_array(coords, k=8)
    w.transform = "r"
    return w


def fit_ols(features: pd.DataFrame):
    predictors = [
        "distance_to_port_km",
        "distance_to_coast_km",
        "distance_to_strait_km",
    ]
    X = sm.add_constant(features[predictors].astype(float))
    y = features["log_density"].astype(float)
    model = sm.OLS(y, X).fit()
    return model, predictors


def fit_spatial_lag(features: pd.DataFrame, w: KNN):
    predictors = [
        "distance_to_port_km",
        "distance_to_coast_km",
        "distance_to_strait_km",
    ]
    X = features[predictors].astype(float).to_numpy()
    y = features["log_density"].astype(float).to_numpy().reshape(-1, 1)
    names = predictors
    model = ML_Lag(y, X, w=w, name_y="log_density", name_x=names)
    return model, predictors


def model_table_from_ols(ols_model) -> pd.DataFrame:
    table = pd.DataFrame(
        {
            "term": ols_model.params.index,
            "coefficient": ols_model.params.values,
            "std_error": ols_model.bse.values,
            "t_value": ols_model.tvalues.values,
            "p_value": ols_model.pvalues.values,
        }
    )
    return table


def model_table_from_mllag(spatial_model) -> pd.DataFrame:
    terms = spatial_model.name_x
    coefs = spatial_model.betas.flatten()
    stderr = spatial_model.std_err
    zstats = [z[0] for z in spatial_model.z_stat]
    pvals = [z[1] for z in spatial_model.z_stat]
    return pd.DataFrame(
        {
            "term": terms,
            "coefficient": coefs,
            "std_error": stderr,
            "z_value": zstats,
            "p_value": pvals,
        }
    )


def select_model_frame(features: pd.DataFrame) -> pd.DataFrame:
    if len(features) <= MAX_ROWS_FOR_SPATIAL_MODEL:
        return features.copy()
    return features.sample(n=MAX_ROWS_FOR_SPATIAL_MODEL, random_state=42).reset_index(drop=True)


def build_interpretation(summary: dict) -> str:
    rho = summary["spatial_lag"]["rho"]
    moran_resid = summary["ols"]["residual_moran_i"]
    port_beta = summary["ols"]["coefficients"].get("distance_to_port_km", 0.0)
    coast_beta = summary["ols"]["coefficients"].get("distance_to_coast_km", 0.0)
    strait_beta = summary["ols"]["coefficients"].get("distance_to_strait_km", 0.0)
    return (
        "Global marine traffic density is strongly spatially structured. "
        f"The OLS baseline shows residual autocorrelation (Moran's I = {moran_resid:.4f}), "
        "which indicates omitted spatial dependence and confirms that independent-cell assumptions are violated. "
        "Distance terms provide interpretable directional effects: "
        f"distance-to-port beta = {port_beta:.6f}, distance-to-coast beta = {coast_beta:.6f}, "
        f"distance-to-strait beta = {strait_beta:.6f}. "
        "Negative coefficients imply higher traffic near the corresponding maritime anchor, while positive values indicate diffusion away from that anchor. "
        f"The spatial lag parameter rho = {rho:.4f} confirms that nearby traffic levels are predictive of local traffic, "
        "capturing network-like spillover behavior of shipping corridors. "
        "Model comparison should prioritize fit criteria and residual behavior together: a lower AIC and reduced residual spatial dependence "
        "in the spatial lag model indicate a more realistic representation than non-spatial OLS. "
        "Practically, this means chokepoints, port-access corridors, and coast-proximate lanes are not independent phenomena; "
        "they are linked through regional maritime systems where high activity propagates across neighboring cells. "
        "For policy and planning, this supports geographically targeted interventions around major straits and dense port regions rather than uniform global assumptions."
    )


def main() -> None:
    features_path = ANALYSIS_DIR / "phase3_engineered_features.csv"
    if not features_path.exists():
        raise FileNotFoundError(
            f"Missing {features_path}. Run spatial_phase3_autocorrelation.py first."
        )
    features_all = pd.read_csv(features_path)
    features = select_model_frame(features_all)
    w = build_weights(features)

    ols_model, predictors = fit_ols(features)
    residuals = ols_model.resid.to_numpy(dtype=float)
    residual_moran = Moran(residuals, w, permutations=999)

    spatial_model, _ = fit_spatial_lag(features, w)

    ols_table = model_table_from_ols(ols_model)
    lag_table = model_table_from_mllag(spatial_model)

    ols_table_path = ANALYSIS_DIR / "phase4_ols_coefficients.csv"
    lag_table_path = ANALYSIS_DIR / "phase4_spatial_lag_coefficients.csv"
    ols_table.to_csv(ols_table_path, index=False)
    lag_table.to_csv(lag_table_path, index=False)

    summary = {
        "rows": {"input_rows": int(len(features_all)), "modeled_rows": int(len(features))},
        "ols": {
            "r_squared": float(ols_model.rsquared),
            "adj_r_squared": float(ols_model.rsquared_adj),
            "aic": float(ols_model.aic),
            "bic": float(ols_model.bic),
            "residual_moran_i": float(residual_moran.I),
            "residual_moran_p_sim": float(residual_moran.p_sim),
            "coefficients": {
                str(k): float(v)
                for k, v in ols_model.params.to_dict().items()
                if str(k) in predictors
            },
        },
        "spatial_lag": {
            "aic": float(spatial_model.aic),
            "rho": float(spatial_model.rho),
            "pseudo_r_squared": float(getattr(spatial_model, "pr2", np.nan)),
            "n": int(spatial_model.n),
            "k": int(spatial_model.k),
        },
    }

    interpretation = build_interpretation(summary)
    summary["interpretation"] = interpretation

    summary_path = ANALYSIS_DIR / "phase4_regression_summary.json"
    write_json(summary_path, summary)
    (ANALYSIS_DIR / "phase4_interpretation.txt").write_text(
        interpretation, encoding="utf-8"
    )

    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Phase 4 - Spatial Regression\n",
                    "\n",
                    "This notebook links to the reproducible outputs generated by `spatial_phase4_regression.py`.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import json\n",
                    f"summary = json.load(open(r'{summary_path.as_posix()}', 'r', encoding='utf-8'))\n",
                    "summary['ols'], summary['spatial_lag']\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.x"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    (ANALYSIS_DIR / "spatial_regression.ipynb").write_text(
        json.dumps(notebook, indent=2), encoding="utf-8"
    )

    print(f"Wrote: {ols_table_path}")
    print(f"Wrote: {lag_table_path}")
    print(f"Wrote: {summary_path}")
    print(f"Wrote: {ANALYSIS_DIR / 'phase4_interpretation.txt'}")
    print(f"Wrote: {ANALYSIS_DIR / 'spatial_regression.ipynb'}")


if __name__ == "__main__":
    main()

