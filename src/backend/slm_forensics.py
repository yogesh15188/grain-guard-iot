"""Optional SLM narrative adapter.

HARD RULE: this module only writes WORDS. It receives the deterministic engine
output and returns prose. It cannot and does not change state, risk, thresholds,
cause, action or actuator permission. If the SLM is slow, absent or broken, the
deterministic template below is used and the rest of the app is unaffected.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TIMEOUT = 2.0                      # hard budget in seconds
SLM_URL = os.environ.get("GRAINGUARD_SLM_URL", "http://localhost:11434/api/generate")
SLM_ENABLED = os.environ.get("GRAINGUARD_SLM", "1") not in ("0", "false", "no")

PROMPT = """You explain sensor readings to Indian grain-store operators.

Use ONLY the facts given below. Never invent a cause. Never claim that sensors
detect pests, fungus, rodents, groundwater, or actual grain moisture. The EMC
value is an ESTIMATE of air moisture, not a measurement of grain moisture.
Use hedged words: "consistent with", "possible", "inspect and verify".

Write 2 to 4 short sentences in plain English. Structure: what the evidence is,
what it implies, and what a person should physically check.

DETERMINISTIC ENGINE OUTPUT (authoritative):
{summary}
"""


def deterministic_text(result: dict) -> str:
    """Always-available fallback narrative built from the engine output."""
    facts = result.get("facts", {}) or {}
    risk = result.get("risk", "UNKNOWN")
    plain = result.get("plain_summary") or ""
    first = (result.get("checks") or ["Verify the bin physically and record what you saw"])[0]
    hedge = {
        "LOW": "Conditions are consistent with safe storage.",
        "MEDIUM": "This is a possible early warning, not confirmed damage.",
        "MEDIUM-HIGH": "This is consistent with a real change that needs a physical check.",
        "HIGH": "This is a probable storage risk if it continues. Do not treat it as confirmed.",
        "CRITICAL": "This needs manager attention now. It is not a confirmed loss.",
    }.get(risk, "")

    parts = [hedge, plain] if plain else [hedge]
    if facts.get("rh") is not None and risk in ("HIGH", "MEDIUM-HIGH", "CRITICAL"):
        parts.append(f"Humidity is reading {facts['rh']:.0f} percent.")
    return " ".join(p for p in parts if p).strip() + " Next step: " + first


def _strip(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    return text.strip()


def explain(result: dict) -> dict:
    """Return {'text':..., 'source': 'slm'|'template'}.

    Any failure, timeout or missing model silently degrades to the template.
    """
    fallback = deterministic_text(result)
    if not SLM_ENABLED:
        return {"text": fallback, "source": "template", "reason": "slm disabled"}

    body = json.dumps({
        "model": os.environ.get("GRAINGUARD_SLM_MODEL", "llama3.1"),
        "prompt": PROMPT.format(summary=json.dumps({
            "state": result.get("state"),
            "risk": result.get("risk"),
            "headline": result.get("headline"),
            "rule": result.get("rule"),
            "evidence": result.get("evidence"),
            "checks": result.get("checks"),
            "facts": result.get("facts"),
        }, default=str)),
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 180},
    }).encode("utf-8")

    req = urllib.request.Request(
        SLM_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = _strip(data.get("response", ""))
        if not text:
            return {"text": fallback, "source": "template", "reason": "empty slm response"}
        # Hard guarantee: the narrative must not be longer than the brief allows.
        sentences = [s for s in text.replace("\n", " ").split(". ") if s][:4]
        return {"text": ". ".join(sentences).strip() + ".", "source": "slm"}
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return {"text": fallback, "source": "template", "reason": str(exc)[:120]}