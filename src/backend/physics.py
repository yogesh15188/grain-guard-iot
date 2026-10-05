"""GrainGuard physics layer.

Pure functions only. No I/O, no globals. Standard library only.

IMPORTANT: EMC here is an ESTIMATE of the equilibrium moisture content the
air would reach at the current temperature/RH. It is NOT a measurement of the
actual moisture content of the stored grain.
"""
from __future__ import annotations

import math

# --- Rough rice EMC approximation -----------------------------------------
# Linearised ASAE-style fit for rough rice:
#   EMC(% wb) = A + B*RH + C*(T - Tref)
# Coefficients anchored to the usual rough-rice sorption table
# (T=25C: 65%RH -> ~13.3%, 75%RH -> ~14.6%, 85%RH -> ~15.9%)
# and to the ~0.05 %/C temperature sensitivity of cereal EMC.
EMC_A = 4.85
EMC_B = 0.13
EMC_C = -0.05
EMC_TREF = 25.0
EMC_MIN = 5.0
EMC_MAX = 20.0


def _valid(v, lo, hi):
    return v is not None and isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(v) and lo <= v <= hi


def calculate_emc(temp_c: float, rh_pct: float):
    """Estimated equilibrium moisture content (%) for rough rice.

    Returns None when inputs are out of range rather than raising, so a bad
    sensor packet can never crash the pipeline.
    """
    if not _valid(temp_c, -10.0, 70.0) or not _valid(rh_pct, 0.0, 100.0):
        return None
    emc = EMC_A + EMC_B * rh_pct + EMC_C * (temp_c - EMC_TREF)
    return round(min(max(emc, EMC_MIN), EMC_MAX), 2)


def calculate_dew_point(temp_c: float, rh_pct: float):
    """Dew point (C) via the Magnus-Tetens approximation. None if invalid."""
    if not _valid(temp_c, -10.0, 70.0) or not _valid(rh_pct, 1.0, 100.0):
        return None
    a, b = 17.27, 237.7
    gamma = (a * temp_c) / (b + temp_c) + math.log(rh_pct / 100.0)
    return round((b * gamma) / (a - gamma), 2)


def calculate_delta_height(current_cm, baseline_cm):
    """Headspace change (cm). Positive = grain level dropped. None if invalid."""
    if not _valid(current_cm, 0.0, 1000.0) or not _valid(baseline_cm, 0.0, 1000.0):
        return None
    return round(current_cm - baseline_cm, 2)


def update_stress(moisture_hours, thermal_hours, temp_c, rh_pct, emc,
                  dt_seconds, rh_limit=65.0, temp_limit=28.0, emc_limit=14.0):
    """Accumulate time-at-risk hours.

    Hours only accrue while the local environment sits on the wrong side of
    the configured limit, which keeps them meaningful rather than decorative.
    Returns (moisture_hours, thermal_hours) rounded to 2 dp.
    """
    dt_h = max(0.0, (dt_seconds or 0.0)) / 3600.0
    m = max(0.0, float(moisture_hours or 0.0))
    t = max(0.0, float(thermal_hours or 0.0))
    moist_risk = (_valid(rh_pct, 0, 100) and rh_pct > rh_limit) or \
                 (_valid(emc, EMC_MIN, EMC_MAX) and emc > emc_limit)
    if moist_risk:
        m += dt_h

    if _valid(temp_c, -10.0, 70.0) and temp_c > temp_limit:
        t += dt_h

    return round(m, 2), round(t, 2)


def describe_interlock(aeration_allowed: bool) -> str:
    """Plain label for the aeration interlock, used by API and UI."""
    return "AVAILABLE - HUMAN VERIFICATION REQUIRED" if aeration_allowed \
        else "LOCKED"
