"""Realistic mock telemetry for demo mode.

Purpose
-------
When no Arduino is connected, the serial worker falls back to mock packets. Those
packets must look like a real godown, otherwise the demo is a flat line and the
dashboard cannot be judged. This module produces a physically plausible stream
for a rough-rice bin in a Tamil Nadu concrete godown.

What is modelled
----------------
* ambient diurnal temperature swing (peak ~15:00, minimum ~05:00 IST)
* bin thermal mass: stored grain damps and delays the swing
* RH moving inversely with temperature, plus a slow synoptic drift
* weather episodes (damp ingress after rain) that raise RH, lower temperature
  and admit light at the shutter
* sensor reality: ADC quantisation and read noise on the raw channels

Deliberate limits
-----------------
* The generator never fabricates a hazard to make the demo look exciting. The
  ambient baseline sits below the configured ingress limit, so the resting state
  is S0/S3. Risk is only ever produced by the deterministic engine reading this
  stream, exactly as it would for real hardware.
* It knows nothing about engine thresholds or states. It emits numbers only.

Performs no I/O and holds no global state: callers own an instance.
"""
from __future__ import annotations

import math
import random
import time
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

# Baseline a healthy, well-sealed bin settles at. Deliberately below the facility
# RH limit so the resting demo state is "safe" / "aeration window".
BASE = {
    "temp": 27.2,          # bin interior
    "rh": 61.0,
    "fork_raw": 900,       # grain surface present and loaded
    "ldr_raw": 22,         # shutter closed, bin dark
    "distance_cm": 15.0,   # matches baseline_distance_cm in the profile
}

# Ambient swing -> bin swing. Thermal mass shrinks the swing and lags it.
AMBIENT_SWING_C = 6.0
BIN_SWING_C = 1.6
BIN_LAG_H = 2.5
PEAK_HOUR = 15.0

# Relative humidity baseline at the daily temperature minimum.
RH_BASE = 63.0
RH_TEMP_COUPLING = -1.15     # RH % per deg C against the ambient swing
RH_DRIFT_PCT = 2.5           # slow multi-hour synoptic wander

# A damp-ingress episode: a shutter or roof gap admits moist outside air.
EPISODE_START_CHANCE = 0.0016   # per step (~1 episode per 10 min of demo time)
EPISODE_RAMP_S = 90.0
EPISODE_HOLD_MIN_S = 150.0
EPISODE_HOLD_MAX_S = 420.0
EPISODE_DECAY_S = 240.0
EPISODE_RH_GAIN = (18.0, 28.0)   # RH % above baseline at full strength
EPISODE_TEMP_DROP = (1.4, 3.0)   # deg C below baseline at full strength
EPISODE_LDR_GAIN = (450, 860)    # raw light rise: an open shutter admits light


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _hour_of_day(now: float) -> float:
    d = datetime.fromtimestamp(now, IST)
    return d.hour + d.minute / 60.0


def _diurnal(hour: float, lag_h: float = 0.0) -> float:
    """-1.0 at the daily minimum, +1.0 at the daily peak."""
    return math.cos(2.0 * math.pi * (hour - PEAK_HOUR + lag_h) / 24.0)


def _gain(ep, key):
    """Read an episode gain, tolerating a None episode."""
    return ep[key] if ep else 0.0


class MockGenerator:
    """Stateful mock sensor stream. Call step() to get the next packet."""

    def __init__(self, base: dict = None, seed=None, start_ts: float = None):
        self.base = dict(BASE)
        if base:
            self.base.update({k: float(v) for k, v in base.items() if k in BASE})
        self.rng = random.Random(seed)
        self.start_ts = time.time() if start_ts is None else start_ts
        self.steps = 0
        self._phase = self.rng.uniform(0.0, 6.28)
        self._drift = 0.0
        # episode: None, or a dict of gains plus its envelope timers
        self._episode = None

    @property
    def in_episode(self) -> bool:
        return self._episode is not None

    # -- episode state machine ------------------------------------------
    def _maybe_start_episode(self):
        if self._episode is not None:
            return
        if self.rng.random() >= EPISODE_START_CHANCE:
            return
        self._episode = {
            "rh_gain": self.rng.uniform(*EPISODE_RH_GAIN),
            "temp_drop": self.rng.uniform(*EPISODE_TEMP_DROP),
            "ldr_gain": self.rng.uniform(*EPISODE_LDR_GAIN),
            "t_ramp": 0.0,
            "t_hold": self.rng.uniform(EPISODE_HOLD_MIN_S, EPISODE_HOLD_MAX_S),
            "t_decay": 0.0,
        }

    def _episode_strength(self, dt: float) -> float:
        """Advance the envelope and return its 0..1 strength."""
        ep = self._episode
        if ep is None:
            return 0.0
        ep["t_ramp"] += dt
        if ep["t_ramp"] < EPISODE_RAMP_S:
            return ep["t_ramp"] / EPISODE_RAMP_S
        ep["t_hold"] -= dt
        if ep["t_hold"] > 0:
            return 1.0
        ep["t_decay"] += dt
        if ep["t_decay"] < EPISODE_DECAY_S:
            return 1.0 - (ep["t_decay"] / EPISODE_DECAY_S)
        self._episode = None
        return 0.0

    # -- channel models ------------------------------------------------
    def _temp(self, hour: float, strength: float) -> float:
        """Bin temperature: damped, lagged diurnal swing minus ingress cooling."""
        t = self.base["temp"] + BIN_SWING_C * _diurnal(hour, -BIN_LAG_H)
        t += 0.12 * math.sin(self._phase)
        return t - _gain(self._episode, "temp_drop") * strength

    def _rh(self, temp: float, strength: float) -> float:
        """RH rises as temperature falls, plus slow drift and any ingress."""
        rh = RH_BASE + RH_TEMP_COUPLING * (temp - self.base["temp"]) + self._drift
        return rh + _gain(self._episode, "rh_gain") * strength

    # -- main ----------------------------------------------------------
    def step(self, dt: float = 1.0, now: float = None) -> dict:
        """Advance the simulation by dt seconds and return one telemetry packet."""
        dt = max(0.0, float(dt))
        self.steps += 1
        now = time.time() if now is None else now
        self._phase += dt / 90.0

        # Slow synoptic wander, clamped so it cannot run away.
        self._drift = _clamp(
            self._drift + self.rng.uniform(-0.25, 0.25) * dt / 60.0,
            -RH_DRIFT_PCT, RH_DRIFT_PCT)

        self._maybe_start_episode()
        strength = self._episode_strength(dt)
        temp = self._temp(_hour_of_day(now), strength)
        rh = self._rh(temp, strength)

        # Raw channels behave like real ADC reads: quantised, with read noise.
        # During an episode the shutter gap admits light, so ldr climbs too.
        fork = self.base["fork_raw"] + self.rng.gauss(0.0, 6.0)
        ldr = (self.base["ldr_raw"] + abs(self.rng.gauss(0.0, 3.0))
               + _gain(self._episode, "ldr_gain") * strength)
        dist = self.base["distance_cm"] + self.rng.gauss(0.0, 0.06) - 0.9 * strength

        return {
            "timestamp": datetime.fromtimestamp(now, timezone.utc)
                          .astimezone(IST).isoformat(timespec="seconds"),
            "temp": round(_clamp(temp, -10.0, 70.0), 2),
            "rh": round(_clamp(rh, 0.0, 100.0), 2),
            "fork_raw": int(_clamp(round(fork), 0, 1023)),
            "ldr_raw": int(_clamp(round(ldr), 0, 1023)),
            "distance_cm": round(_clamp(dist, 0.0, 1000.0), 2),
        }

