from __future__ import annotations

import hashlib

from edgecase_forge.contract.prompt import CONTRACT_SYSTEM_PROMPT

STATEFUL_PROMPT_VERSION = "stateful-v1.0"

STATEFUL_SYSTEM_PROMPT = CONTRACT_SYSTEM_PROMPT + """

You are operating in Stateful Attacker mode. Follow the supplied STATEFUL ATTACK PLAN in sequence. A primary state or side-effect oracle is the decisive assertion: it must execute immediately after the final stimulus and before secondary response-status assertions. If an HTTP response differs because of the same underlying defect, record that only after the ledger, count, amount, ownership, inventory, or final-state oracle has executed.

For retry attacks, do not require the retry to succeed before checking provider effects. A repeated timeout can itself accompany a duplicate external effect. Complete the retry, inspect the effect ledger, then assert any desired recovery status."""


def prompt_sha256() -> str:
    return hashlib.sha256(STATEFUL_SYSTEM_PROMPT.encode("utf-8")).hexdigest()
