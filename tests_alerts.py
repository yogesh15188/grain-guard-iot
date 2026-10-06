"""Verification for the alert layer. Run:  python tests_alerts.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src", "backend"))

import alerts  # noqa: E402

CALM = {"temp": 26.0, "rh": 58.0, "emc_estimate": 12.4, "dew_point": 16.5,
        "fork_raw": 880, "ldr_raw": 24, "delta_height_cm": 0.0}


def mk(state="S0_IDLE_SAFE", risk="LOW", **kw):
    f = dict(CALM)
    f.update(kw)
    return {"state": state, "risk": risk, "facts": f}


def keys(res):
    return [a["key"] for a in res["alerts"]]


def case(name, want, got):
    """`want` is an expected alert key, or the sentinel 'NONE'."""
    ok = (got == []) if want == "NONE" else (want in got)
    print(f"{'PASS' if ok else 'FAIL'}  {name:24s} -> {got}")
    return 0 if ok else 1


fails = 0

# 1. calm bin produces nothing at all
A = alerts.AlertEngine()
fails += case("calm", "NONE", keys(A.detect(mk(), 1000.0)))

# 2. rain surge needs TWO readings separated in time - single high RH is not a surge
A = alerts.AlertEngine()
A.detect(mk(rh=62.0), 0.0)
res = A.detect(mk(temp=27.5, rh=88.0, dew_point=25.3), 600.0)
fails += case("rain surge", "RAIN_SURGE", keys(res))
if res["top"] and res["top"]["key"] == "RAIN_SURGE":
    print("      top severity =", res["top"]["severity"])
fails += case("88% RH = danger band", "HUMIDITY_DANGER", keys(res))
no_surge = "RAIN_SURGE" not in keys(alerts.AlertEngine().detect(mk(rh=88.0), 600.0))
print(f"{'PASS' if no_surge else 'FAIL'}  single high RH is NOT a surge")
fails += 0 if no_surge else 1

# 3. latching: same condition must NOT re-fire while it persists
before = len(A.active)
res2 = A.detect(mk(temp=27.5, rh=88.0, dew_point=25.3), 700.0)
if [a["key"] for a in res2["new"]]:
    print("FAIL  latch re-fired:", [a["key"] for a in res2["new"]])
    fails += 1
else:
    print("PASS  latch suppresses re-fire")

# 4. clearing removes the alert
A.detect(mk(), 1000.0)
if A.active:
    print("FAIL  alerts did not clear:", list(A.active))
    fails += 1
else:
    print("PASS  alerts clear when condition goes")

# 5. condensation (dew point catches temperature)
fails += case("condensation critical", "CONDENSATION_CRITICAL",
              keys(alerts.AlertEngine().detect(mk(temp=26.0, rh=97.0, dew_point=25.6), 1.0)))

# 6. heat bands
fails += case("heat critical", "HEAT_CRITICAL",
              keys(alerts.AlertEngine().detect(mk(temp=39.0, rh=40.0, dew_point=20.0), 1.0)))
fails += case("heat warning", "HEAT_WARNING",
              keys(alerts.AlertEngine().detect(mk(temp=29.0, rh=45.0, dew_point=17.0), 1.0)))

# 7. physical channels
fails += case("water near wall", "WATER_NEAR_WALL",
              keys(alerts.AlertEngine().detect(mk(fork_raw=190), 1.0)))
fails += case("stock moved", "STOCK_MOVED",
              keys(alerts.AlertEngine().detect(mk(distance_cm=23.8, delta_height_cm=8.8), 1.0)))
fails += case("light ingress", "LIGHT_INGRESS",
              keys(alerts.AlertEngine().detect(mk(ldr_raw=840), 1.0)))
fails += case("device offline", "DEVICE_OFFLINE",
              keys(alerts.AlertEngine().detect(
                  {"state": "S6_OFFLINE", "risk": "MEDIUM-HIGH",
                   "facts": dict(CALM), "seconds_since_last": 300}, 1.0)))

# 8. audit anomaly
fails += case("unverified ack", "UNVERIFIED_ACK",
              keys(alerts.AlertEngine().detect(mk(state="S7_AUDIT_ANOMALY", risk="CRITICAL"), 1.0)))

# 9. garbage input must never raise
try:
    r = alerts.AlertEngine().detect({"facts": {"temp": "hot", "rh": None}}, 1.0)
    print("PASS  garbage input handled ->", keys(r))
except Exception as exc:  # noqa: BLE001
    print("FAIL  garbage input raised:", exc)
    fails += 1

try:
    r = alerts.AlertEngine().detect({}, 1.0)
    r = alerts.AlertEngine().detect(None, 1.0)
    print("PASS  empty/None result handled")
except Exception as exc:  # noqa: BLE001
    print("FAIL  empty result raised:", exc)
    fails += 1

# 10. severity ordering: critical must sort above warning
A = alerts.AlertEngine()
res = A.detect(mk(temp=39.0, rh=97.0, dew_point=25.9, fork_raw=190), 1.0)
sev = [a["severity"] for a in res["alerts"]]
if sev == sorted(sev, key=lambda s: -alerts.SEVERITY_RANK[s]):
    print("PASS  alerts sorted by severity ->", sev)
else:
    print("FAIL  severity order wrong:", sev)
    fails += 1

print("\n" + ("ALL ALERT CHECKS PASSED" if fails == 0 else f"{fails} ALERT CHECK(S) FAILED"))
sys.exit(1 if fails else 0)
