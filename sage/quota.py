"""What a provider says about this key's limits, as warnings before a limit bites.

Two limits end a deployment without making it slower first. A free tier's daily request
counter, which is account-wide: when it runs out every free model refuses until it
resets, and on 2026-09-12 that, together with two other providers refusing the same
afternoon, left the app with nothing that would answer. And a key's own spending limit,
which an operator sets precisely so that a runaway turn loop cannot spend the account.

Neither announces itself before it is reached, and the only thing that saw the
2026-09-12 cap coming was a log nobody was reading. So the hourly model refresh asks the
provider for its counters (`OpenAICompatProvider.status`), and this module decides what
is worth a WARNING line: one that Cloud Logging lifts out with its severity, and that a
log-based alert can watch for. It takes the numbers as an argument and knows nothing
about where they came from.
"""

from __future__ import annotations


def warnings(provider: str, status: dict | None, fraction: float) -> list[str]:
    """The warning lines `status` deserves, given the share of a limit worth warning at.

    `fraction` is `config.LIMIT_WARNING_FRACTION`: 0.1 warns once a tenth or less of a
    limit is left. 0 switches the warnings off. A counter the provider did not report is
    skipped rather than guessed at.
    """
    if not status or fraction <= 0:
        return []
    found = []
    limit = status.get("free_limit")
    left = status.get("free_remaining")
    used = status.get("free_used")
    if _positive(limit) and _number(left) and left <= limit * fraction:
        spent = used if _number(used) else limit - left
        found.append(
            f"{provider}: {spent:g} of {limit:g} free-model requests used today. The "
            "count resets at 00:00 UTC, and every free model is refused once it runs out."
        )
    cap = status.get("limit_usd")
    remaining = status.get("limit_remaining_usd")
    if _positive(cap) and _number(remaining) and remaining <= cap * fraction:
        window = status.get("limit_reset") or "lifetime"
        found.append(
            f"{provider}: ${max(remaining, 0):.2f} of this key's ${cap:.2f} {window} "
            "spending limit is left. Requests on the key are refused once it is spent."
        )
    return found


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive(value) -> bool:
    return _number(value) and value > 0
