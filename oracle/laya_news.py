"""Prospective headline annotations from Laya, a local open-source decision model.

Replaces the paid JEV evaluator. FinBERT results and earlier JEV annotations are never touched.
"""

import hashlib
import json
import math
import os
import time
from functools import lru_cache
from pathlib import Path

from .db import connect, digest, packed

REPO = "convaiinnovations/laya"
REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
PACKAGE = "laya==0.3.20"
MODEL = REPO + "@" + REVISION
# Every file the English checkpoint loads. A mismatch refuses the load before any weight is parsed.
DIGESTS = {
    "rl_agent_config.json": "ae287b56bbcf5f8c4f4541ae9dfd00c914c4c48b940b8398c3058af37ba92bbd",
    "model.safetensors": "891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c",
    "tokenizer/tokenizer.json": "6c8aaa9a542084f2457eab775d4eeb51f92a70c0fd9de28d5edb0ddec3c08d30",
    "tokenizer/tokenizer_config.json": "50044de60daaa73df97d262e15a40d4faf0160e7d742df64b377877a1320dd12",
    "encoder/config.json": "bf3ab80598fdccf414855a2ce80f22859e4492d06ca8a62ddd1cfb63972f8979",
}
# The same six questions JEV answered, so both annotation versions stay comparable.
QUESTIONS = json.loads(Path(__file__).with_name("news_questions.json").read_text())
# Laya calls a yes/no question "noul"; stored answers keep the model-neutral schema below.
LAYA_QUESTIONS = {
    name: {**q, "type": "noul" if q["type"] == "boolean" else q["type"]} for name, q in QUESTIONS.items()
}
STATE = "headline text only"
VERSION = "laya-headlines-v1-" + digest([MODEL, PACKAGE, DIGESTS, STATE, LAYA_QUESTIONS])[:12]


@lru_cache(maxsize=1)
def agent():
    from huggingface_hub import snapshot_download
    from laya import Agent

    from .models import configure_torch

    configure_torch()
    local = snapshot_download(REPO, revision=REVISION, allow_patterns=list(DIGESTS))
    for name, expected in DIGESTS.items():
        with open(os.path.join(local, name), "rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != expected:
                raise RuntimeError("Laya checkpoint digest mismatch: " + name)
    return Agent(local, device="cpu")


def request_for(row):
    return {"state": row["title"], "questions": LAYA_QUESTIONS}


def probability(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Laya invalid probability")
    return value


def normalize(result):
    """Check Laya's raw answers and map them to the schema the dashboard and newsletter read."""
    answers = result.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(QUESTIONS):
        raise ValueError("Laya incomplete answers")
    normalized = {}
    for name, question in QUESTIONS.items():
        answer = answers[name]
        if not isinstance(answer, dict) or answer.get("type") != LAYA_QUESTIONS[name]["type"]:
            raise ValueError("Laya answer type mismatch")
        if question["type"] == "boolean":
            normalized[name] = {"type": "boolean", "probability": probability(answer.get("noul"))}
            continue
        criteria = question["criteria"]
        probs = answer.get("probabilities")
        if answer.get("choice") not in criteria:
            raise ValueError("Laya unknown choice")
        if not isinstance(probs, dict) or set(probs) != set(criteria):
            raise ValueError("Laya incomplete distribution")
        for value in probs.values():
            probability(value)
        # Laya rounds each probability to four decimals.
        if abs(sum(probs.values()) - 1) > len(probs) * 0.5e-4 + 1e-9:
            raise ValueError("Laya invalid distribution sum")
        normalized[name] = {"type": "choice", "choice": answer["choice"], "probabilities": probs}
    # Reject NaN/Infinity anywhere before persisting model output.
    packed(result)
    return normalized


def collect(limit=8):
    if os.getenv("ORACLE_LAYA_ENABLED", "0") != "1":
        return {"state": "disabled", "model": MODEL, "version": VERSION}
    from .runner import process_lock

    with process_lock("laya"):
        return _collect(max(1, min(int(limit), 50)))


def _collect(limit):
    now = int(time.time())
    with connect() as db:
        rows = db.execute(
            "SELECT n.* FROM news n WHERE n.first_seen<=? AND n.first_seen>? "
            "AND n.published_at>=? AND n.published_at<=? AND NOT EXISTS "
            "(SELECT 1 FROM news_evaluations e WHERE e.news_id=n.id AND e.version=?) "
            "AND NOT EXISTS (SELECT 1 FROM news newer WHERE newer.url=n.url AND "
            "(newer.first_seen>n.first_seen OR (newer.first_seen=n.first_seen AND newer.rowid>n.rowid))) "
            "ORDER BY n.first_seen DESC,n.published_at DESC LIMIT ?",
            (now, now - 86400, now - 86400, now, VERSION, limit),
        ).fetchall()
    if not rows:
        return {"state": "active", "classified": 0, "model": MODEL, "version": VERSION}
    model = agent()
    classified = failed = 0
    for row in rows:
        payload = request_for(row)
        started = time.monotonic()
        try:
            result = model.predict(payload["state"], payload["questions"])
            answers = normalize(result)
        except (RuntimeError, ValueError, TypeError, KeyError):
            # No annotation is better than a guessed one; the job reports the gap below.
            failed += 1
            continue
        with connect() as db:
            db.execute(
                "INSERT INTO news_evaluations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    digest([row["id"], VERSION]),
                    row["id"],
                    MODEL,
                    VERSION,
                    int(time.time()),
                    digest(payload),
                    packed(payload),
                    packed(answers),
                    packed(result),
                    (time.monotonic() - started) * 1000,
                    PACKAGE,
                ),
            )
        classified += 1
    if failed:
        raise RuntimeError(f"Laya failed on {failed} of {len(rows)} headlines; existing annotations preserved")
    return {"state": "active", "classified": classified, "model": MODEL, "version": VERSION}
