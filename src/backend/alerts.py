"""
GrainGuard environmental event / alert detection.

Separate from engine.py on purpose:
  engine.py  decides storage RISK and state (S0..S7) - the safety decision.
  alerts.py  decides WHEN A HUMAN SHOULD BE TURNED AND TOLD, and about what.

An alert is not a risk. A bin can be MEDIUM risk and still deserve a
notification, and a rapid humidity climb deserves a notification even before
the risk state escalates.

HARD RULES
  * Deterministic only. No SLM, no guessing, no network.
  * Never claims to detect rain, pests, fungus or groundwater. These sensors
    measure air temperature, relative humidity, light and surface distance.
    Every finding is phrased "consistent with" / "possible" / "verify".
  * Degrades quietly on bad input. Never raises.
  * Latching: an alert re-fires only after it clears, so the operator is not
    spammed once per second while a condition persists.
"""
from __future__ import annotations

from collections import deque

INFO = "info"
WARNING = "warning"
DANGER = "danger"
CRITICAL = "critical"

SEVERITY_RANK = {INFO: 0, WARNING: 1, DANGER: 2, CRITICAL: 3}

# overridden by data/facility_profile.json -> "alerts"
DEFAULTS = {
    "rh_warn": 65.0,
    "rh_danger": 80.0,
    "rh_critical": 90.0,
    "temp_warn": 28.0,
    "temp_danger": 32.0,
    "temp_critical": 38.0,
    "dew_margin_warn": 3.0,
    "dew_margin_critical": 1.0,
    "rain_rise_pct": 8.0,
    "rain_window_min": 15.0,
    "rain_abs_rh": 70.0,
    "drop_rise_pct": 6.0,
    "offline_after_s": 45.0,
}

WINDOW_SECONDS = 900.0


def _num(v, lo, hi):
    return (v is not None and isinstance(v, (int, float))
            and not isinstance(v, bool) and v == v and lo <= v <= hi)


def _a(key, severity, title, evidence, consistency, actions):
    return {"key": key, "severity": severity, "title": title,
            "evidence": evidence, "consistency": consistency,
            "actions": list(actions)}


class AlertEngine:
    """Rate tracker + latch. One instance for the server lifetime."""

    def __init__(self, limits=None):
        self.limits = dict(DEFAULTS)
        for k, v in (limits or {}).items():
            if k in self.limits and _num(v, -1e9, 1e9):
                self.limits[k] = v
        self._rh_hist = deque()
        self.active = {}

    def reset(self):
        self._rh_hist.clear()
        self.active.clear()

    def detect(self, result, now):
        """Return {'alerts': [...], 'new': [...], 'cleared': [...], 'top': {...}}."""
        result = result or {}
        f = result.get("facts") or {}
        temp, rh = f.get("temp"), f.get("rh")
        dew, emc = f.get("dew_point"), f.get("emc_estimate")
        fork, ldr = f.get("fork_raw"), f.get("ldr_raw")
        dh = f.get("delta_height_cm")
        state = result.get("state") or ""
        L = self.limits

        found = []
        self._push_rh(now, rh)
        surge = self._rh_surge(now)

        # ---- 1. rain / storm-driven damp-air surge ----
        # Sensors cannot detect rain. We detect the humidity signature heavy
        # rain produces: a fast RH climb to a high absolute value.
        if surge is not None and _num(rh, 0, 100) and rh >= L["rain_abs_rh"]:
            found.append(_a(
                "RAIN_SURGE", DANGER,
                "Rapid humidity climb consistent with rain or storm-driven damp air",
                f"Relative humidity rose {surge['delta']:.0f}% in about "
                f"{surge['minutes']:.0f} min (now {rh:.0f}%)",
                "Rain, a leaking roof or an open shutter could all cause this",
                ["Close shutters, roof gaps and vents before the air soaks in",
                 "Look for standing water or a drip above the bin",
                 "Re-check in 15 minutes - if it keeps rising, escalate"]))

        # ---- 2. dew / condensation ----
        if _num(temp, -10, 70) and _num(dew, -20, 70):
            margin = temp - dew
            if margin <= L["dew_margin_critical"]:
                found.append(_a(
                    "CONDENSATION_CRITICAL", CRITICAL,
                    "Dew point caught up with temperature - condensation forming",
                    f"Temperature {temp:.1f} C, dew point {dew:.1f} C "
                    f"(margin {margin:+.1f} C)",
                    "Surfaces in the bin can start getting wet; wet grain spoils fast",
                    ["Open the aeration path NOW if it is safe to do so",
                     "Check for a cold surface or a metal roof touching damp grain",
                     "Record the time - wet grain must be dried, not stored"]))
            elif margin <= L["dew_margin_warn"]:
                found.append(_a(
                    "CONDENSATION_WATCH", WARNING,
                    "Dew point is close to temperature - condensation possible",
                    f"Temperature {temp:.1f} C, dew point {dew:.1f} C "
                    f"(margin {margin:+.1f} C)",
                    "Cool night air can bring this margin down to zero",
                    ["Watch the trend overnight",
                     "Plan aeration for the next dry window",
                     "Inspect the roof and walls for damp patches"]))
            if surge is not None and surge["delta"] >= L["drop_rise_pct"]:
                found.append(_a(
                    "DEW_OR_FOG", WARNING,
                    "Humidity rising while temperature falls - possible dew or fog",
                    f"Humidity up {surge['delta']:.0f}% with a falling temperature",
                    "Consistent with night cooling or fog, not necessarily rain",
                    ["Re-check in 30 minutes and record whether it reverses",
                     "Do not aerate into rising humidity",
                     "Inspect for a roof or wall colder than the air"]))

        # ---- 3. humidity bands ----
        if _num(rh, 0, 100):
            if rh >= L["rh_critical"]:
                found.append(_a(
                    "HUMIDITY_CRITICAL", CRITICAL,
                    "Humidity in the range where grain damage is likely",
                    f"Relative humidity {rh:.0f}% (critical {L['rh_critical']:.0f}%)",
                    "Consistent with air that can keep grain damp for days",
                    ["Escalate to the manager now",
                     "Check shutters, roof gaps, drainage and the dunnage",
                     "Plan controlled drying or shifting once air improves"]))
            elif rh >= L["rh_danger"]:
                found.append(_a(
                    "HUMIDITY_DANGER", DANGER,
                    "High humidity - a spoilage risk is building",
                    f"Relative humidity {rh:.0f}% (danger {L['rh_danger']:.0f}%)",
                    "Consistent with damp air reaching the grain",
                    ["Walk the shed and look for gaps around shutters and roof",
                     "Verify the humidity sensor is not near an open window",
                     "Record the reading and the time"]))
            elif rh >= L["rh_warn"]:
                found.append(_a(
                    "HUMIDITY_WARNING", WARNING,
                    "Humidity above the configured limit",
                    f"Relative humidity {rh:.0f}% (limit {L['rh_warn']:.0f}%)",
                    "Air is getting damp; no damage implied yet",
                    ["Note the time and keep watching",
                     "Check that vents and louvres are closed"]))

        # ---- 4. temperature bands ----
        if _num(temp, -10, 70):
            if temp >= L["temp_critical"]:
                found.append(_a(
                    "HEAT_CRITICAL", CRITICAL,
                    "Extreme heat in the storage area",
                    f"Temperature {temp:.1f} C (critical {L['temp_critical']:.0f} C)",
                    "Very high heat can damage grain quality and dry it out",
                    ["Move or shade the bin if possible",
                     "Do not leave the fan running unattended",
                     "Record the reading - heat damage is not reversible"]))
            elif temp >= L["temp_danger"]:
                found.append(_a(
                    "HEAT_DANGER", DANGER,
                    "High temperature in the storage area",
                    f"Temperature {temp:.1f} C (danger {L['temp_danger']:.0f} C)",
                    "Heat plus humidity together drives spoilage much faster",
                    ["Check ventilation and whether the bin is in direct sun",
                     "Avoid leaving doors open at the hottest part of the day"]))
            elif temp >= L["temp_warn"]:
                found.append(_a(
                    "HEAT_WARNING", WARNING,
                    "Temperature above the configured limit",
                    f"Temperature {temp:.1f} C (limit {L['temp_warn']:.0f} C)",
                    "Mildly warm; normal in a closed shed for part of the day",
                    ["Keep the normal inspection round",
                     "Note the time for comparison"]))

        # ---- 5. moisture / EMC ----
        if _num(emc, 0, 100) and emc >= L["rh_danger"] * 0.14 + 4.0:
            found.append(_a(
                "EMC_HIGH", WARNING,
                "Air EMC estimate is high - air can hold a lot of moisture",
                f"EMC estimate {emc:.1f}%",
                "An ESTIMATE of air moisture, not a measurement of grain moisture",
                ["Treat as a warning, not a diagnosis",
                 "Correlate with humidity before acting"]))

        # ---- 6. physical channels ----
        if _num(fork, 0, 1023) and fork < 300:
            found.append(_a(
                "WATER_NEAR_WALL", DANGER,
                "Something is close to the bin wall or floor probe",
                f"Fork/proximity raw {fork:.0f}",
                "Consistent with water, a leak or an object at the wall",
                ["Go and look at the wall and the dunnage now",
                 "Check for a seep or standing water at floor level",
                 "Look for an animal entry hole by eye - this does not identify animals"]))

        if _num(dh, -999, 999) and dh > 5.0:
            found.append(_a(
                "STOCK_MOVED", WARNING,
                "Grain level or headspace changed unexpectedly",
                f"Headspace change {dh:+.1f} cm",
                "Consistent with stock settling, a moved probe or a shifted surface",
                ["Visually confirm the grain surface level",
                 "Confirm the distance probe has not been knocked"]))

        if _num(ldr, 0, 1023) and ldr >= 700:
            found.append(_a(
                "LIGHT_INGRESS", WARNING,
                "Sudden light at the shutter - something is open",
                f"Light sensor raw {ldr:.0f}",
                "Consistent with an open shutter or direct light on the sensor",
                ["Check shutters, doors and roof gaps",
                 "Note the time so you can compare it with humidity"]))

        # ---- 7. device / audit ----
        age = result.get("seconds_since_last")
        if _num(age, 0, 1e6) and age > L["offline_after_s"]:
            found.append(_a(
                "DEVICE_OFFLINE", WARNING,
                "The monitoring box has stopped sending readings",
                f"Last packet {age:.0f} s ago",
                "The numbers on screen are the LAST KNOWN values, not current",
                ["Check the power supply and the USB/serial cable",
                 "Readings shown are historical - do not rely on them"]))

        if state == "S7_AUDIT_ANOMALY":
            found.append(_a(
                "UNVERIFIED_ACK", CRITICAL,
                "An alert was marked handled without physical verification",
                "Acknowledgment recorded with no verification",
                "An audit gap, not an accusation of wrongdoing",
                ["A manager must physically inspect the bin",
                 "Record the verification time and the verifier's name",
                 "The original alert is preserved and was not deleted"]))

        # ---- latch / diff ----
        keys = {a["key"] for a in found}
        new_alerts, cleared = [], []
        for a in found:
            if a["key"] not in self.active:
                new_alerts.append(a)
            self.active[a["key"]] = a
        for key in list(self.active):
            if key not in keys:
                cleared.append(self.active.pop(key))

        alerts = sorted(self.active.values(),
                        key=lambda a: (-SEVERITY_RANK.get(a["severity"], 0),
                                       a["key"]))
        return {"alerts": alerts, "new": new_alerts, "cleared": cleared,
                "top": alerts[0] if alerts else None}

    # ---- internals ----
    def _push_rh(self, now, rh):
        if _num(rh, 0, 100):
            self._rh_hist.append((now, rh))
        while self._rh_hist and (now - self._rh_hist[0][0]) > WINDOW_SECONDS:
            self._rh_hist.popleft()

    def _rh_surge(self, now):
        """Largest RH climb inside the configured window, or None."""
        if len(self._rh_hist) < 2:
            return None
        window = self.limits["rain_window_min"] * 60.0
        oldest_ts, oldest_rh = self._rh_hist[0]
        newest_ts, newest_rh = self._rh_hist[-1]
        for ts, rh in self._rh_hist:
            if (now - ts) <= window:
                oldest_ts, oldest_rh = ts, rh
                break
        if (now - oldest_ts) < 30.0 or (newest_ts - oldest_ts) < 30.0:
            return None
        delta = newest_rh - oldest_rh
        if delta < self.limits["rain_rise_pct"]:
            return None
        return {"delta": delta,
                "minutes": max(0.5, (newest_ts - oldest_ts) / 60.0),
                "from": oldest_rh, "to": newest_rh}

