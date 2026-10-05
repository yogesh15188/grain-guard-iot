# GrainGuard

**Protect the Grain. See the Risk Before the Loss.**
Offline-first early warning for Indian grain storage.

Sensors provide evidence → Physics calculates → Rules determine risk →
**Human decides** → SLM explains.

---

## Run it

```bash
pip install -r requirements.txt
python run.py
```

Open <http://127.0.0.1:8000>. That is the whole setup.

Works with **no hardware**, **no internet** and **no SLM**. When the Arduino is
not connected the console shows `HARDWARE OFFLINE — SIMULATION MODE` and keeps
running on mock telemetry.

```bash
python run.py --no-open     # server only
python tests_check.py       # verify engine against all scenarios
```

---

## 3-minute pitch

> A farmer stores paddy in a concrete godown for six months. If damp air gets in
> through a roof gap, the grain spoils. The problem is that nobody notices until
> it is too late, because nobody is inside the bin at 3 AM.
>
> GrainGuard puts four cheap sensors in one bin: temperature, humidity, light at
> the shutter, and grain surface height. Physics turns those readings into an EMC
> estimate and a dew point. Fixed rules then decide the risk — no guessing, and
> the exact rule that fired is always on screen.
>
> Two things make it trustworthy. First, the machine never overclaims: it will
> tell you conditions are *consistent with* damp air, never that it detected
> fungus or rodents, because it cannot. Second, the aeration fan stays locked
> unless conditions are genuinely safe, and unlocking it needs a human.
>
> Every alert is written to a tamper-evident local ledger. If someone marks an
> alert done without going to look, that is recorded as an unverified
> acknowledgment and escalated to the manager — we do not delete the original
> alert.
>
> It runs on a low-cost board with no internet. If the network or the hardware
> dies, the last reading and full history stay on screen.

---

## Live demo walkthrough

Open **Launch Console**, then click the scenario buttons. Each one is pushed
through the *same* physics and engine pipeline as live telemetry — the UI only
renders what the deterministic engine returns.

| Step | Click | Expected result |
|---|---|---|
| 1 | `Normal` | `S0_IDLE_SAFE`, LOW, aeration LOCKED |
| 2 | `Humidity Intrusion` | `S1_ATMOSPHERIC_INGRESS`, HIGH, aeration LOCKED |
| 3 | `Dunnage Seepage` | `S2_DUNNAGE_SEEPAGE`, HIGH, aeration LOCKED |
| 4 | `Stock Anomaly` | `S4_PHYSICAL_ANOMALY`, MEDIUM-HIGH |
| 5 | `Offline` | `S6_OFFLINE`, last reading retained |
| 6 | `Unverified Acknowledgment` | `S7_AUDIT_ANOMALY`, CRITICAL |

Watch the **pipeline indicator** light up Telemetry → Physics → Deterministic
Engine → SLM Explanation. That is the proof for judges that the same code path
handles both live and simulated data.

Also try: switch **Operator Mode / Manager Mode**, toggle the light/dark theme,
and use the Ack buttons to show the audit trail.

A scenario result is held on screen for 60 s so judges can read it; live mock
telemetry then resumes automatically.

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| GET  | `/api/status` | current state, risk, evidence, mode |
| POST | `/api/telemetry` | push one live telemetry packet |
| GET  | `/api/history` | recent telemetry rows |
| GET  | `/api/events` | event log, acks, ledger chain check |
| POST | `/api/simulate/{id}` | run a scenario through the live pipeline |
| POST | `/api/acknowledge` | record a verified / unverified ack |

Telemetry shape:

```json
{"timestamp":"ISO-8601","temp":28.5,"rh":78.0,"fork_raw":1023,"ldr_raw":12,"distance_cm":15.0}
```

Missing or invalid fields are reported, never guessed, and never crash the app.
---

## How the decision is made

States: `S0_IDLE_SAFE`, `S1_ATMOSPHERIC_INGRESS`, `S2_DUNNAGE_SEEPAGE`,
`S3_PERMISSIBLE_AERATION`, `S4_PHYSICAL_ANOMALY`, `S5_CUMULATIVE_STRESS`,
`S6_OFFLINE`, `S7_AUDIT_ANOMALY`.

Rules are evaluated in a fixed order (thresholds live in
`data/facility_profile.json`):

1. cumulative moisture stress over limit → **S5 / CRITICAL**
2. `fork_raw < 300` → **S2 / HIGH**, aeration locked
3. headspace change > 5 cm → **S4 / MEDIUM-HIGH**, aeration locked
4. `ldr_raw >= 700` with RH still normal → **S4 / MEDIUM-HIGH**
5. `RH > 65%` or `EMC > 14%` → **S1 / HIGH**, aeration locked
6. `T > 28°C` and RH low and EMC safe and fork loaded → **S3 / MEDIUM**, aeration available
7. otherwise → **S0 / LOW**

> Note on ordering: a high-RH reading *explains* high light readings (an open
> shutter admits both light and damp air), so rule 4 is skipped when rule 5
> fires. A headspace movement is not explained by damp air, so rule 3 keeps
> priority.

**The SLM never decides risk, state, thresholds, cause, action or actuator
permission.** It only rewords the engine's output. If it is slow (>2 s),
missing or broken, a deterministic template is used and the UI is unaffected.

---

## What GrainGuard will never claim

- that a rodent, pest, fungus or groundwater was detected
- that it measured actual grain moisture content

EMC is an **estimate of the moisture the air would reach**, not a measurement of
the grain. Findings are phrased as *consistent with*, *possible*,
*inspect/verify*.

---

## Project layout

```
grain-guard/
├── firmware/            # Arduino sketch — NOT touched by this build
├── src/backend/
│   ├── main.py          # FastAPI: 6 endpoints, one shared pipeline
│   ├── physics.py       # EMC, dew point, Δheight, stress hours
│   ├── engine.py        # ordered rule engine -> state/risk/facts/interlock
│   ├── database.py      # SQLite WAL + hash-chained ledger
│   ├── slm_forensics.py # optional narrative, 2s timeout, hard fallback
│   └── serial_worker.py # serial reader -> automatic mock fallback
├── src/frontend/        # index.html, styles.css, app.js (no frameworks)
├── data/                # scenarios, facility profile, SQLite ledger
├── run.py               # one-command boot
└── tests_check.py       # engine verification
```

## Config (optional)

| Variable | Default | Meaning |
|---|---|---|
| `GRAINGUARD_PORT` | `8000` | server port |
| `GRAINGUARD_SERIAL_PORT` | auto | e.g. `COM5` |
| `GRAINGUARD_SLM` | `1` | set `0` to disable the SLM entirely |
| `GRAINGUARD_SLM_URL` | Ollama | local SLM endpoint |