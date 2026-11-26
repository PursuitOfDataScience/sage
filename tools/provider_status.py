#!/usr/bin/env python3
"""What each configured provider says about this deployment's key and lineup, now.

For every provider in the profile that has a key in the environment:

* the key's own spending limit and the account's free-model request counter, for an
  entry that declares `status_path` (OpenRouter's `GET /key`, which spends nothing
  against the free cap); the same numbers the app checks hourly (`sage/quota.py`);
* for each id in the entry's `models` list, whether the catalogue still serves it, the
  model an alias (`~vendor/family-latest`) resolves to today, and any retirement date
  (`expiration_date`), which is the notice worth having before the day;
* how many free (`:free`) models the catalogue lists, the pool `openrouter/free` draws
  from.

`--audit` also asks whether the account is admitted to the Alignment plugin's beta, by
sending one small request with the audit attached to the entry's first model. That is
the check `sage/alignment.py` requires before `alignment = true`, and it is the only
part of this tool that makes a model request.

Informational only: it exits 0 whatever it finds, and it never edits the profile.

    python tools/provider_status.py
    python tools/provider_status.py --audit
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from sage import alignment, profile, providers  # noqa: E402


def catalogue(entry) -> list[dict]:
    """The provider's `GET /models` listing, or [] if it serves none."""
    try:
        import httpx  # noqa: PLC0415

        response = httpx.get(f"{entry.base_url.rstrip('/')}/models", timeout=20)
        response.raise_for_status()
        data = response.json().get("data")
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 (an endpoint that lists nothing is reported as such)
        return []


def lineup_lines(entry, listed: list[dict]) -> list[str]:
    """One line per id in the entry's `models`: served, resolves to, retires."""
    by_id = {str(item.get("id")): item for item in listed}
    by_slug = {str(item.get("canonical_slug")): item for item in listed
               if item.get("canonical_slug")}
    lines = []
    for model_id in entry.models:
        item = by_id.get(model_id)
        if item is None:
            lines.append(f"  {model_id}: NOT in the catalogue")
            continue
        parts = [f"  {model_id}: served"]
        target = item.get("alias_target")
        slug = target.get("slug") if isinstance(target, dict) else None
        if slug:
            parts.append(f"resolves to {slug}")
        dates = [item.get("expiration_date")]
        resolved = by_slug.get(slug) or by_id.get(slug) if slug else None
        if resolved:
            dates.append(resolved.get("expiration_date"))
        dated = [str(when) for when in dates if when]
        parts.append(f"may be removed after {dated[0]}" if dated else "no retirement date")
        lines.append(", ".join(parts))
    return lines


def status_lines(name: str, adapter) -> list[str]:
    status = adapter.status() if hasattr(adapter, "status") else None
    if not status:
        return ["  key status: not reported"]
    lines = []
    if status.get("free_limit") is not None:
        lines.append(
            f"  free-model requests today: {status.get('free_used')} of "
            f"{status.get('free_limit')} used ({status.get('free_remaining')} left, resets "
            "00:00 UTC)"
        )
    if status.get("limit_usd") is not None:
        lines.append(
            f"  key spending limit: ${status.get('limit_remaining_usd') or 0:.2f} of "
            f"${status['limit_usd']:.2f} left ({status.get('limit_reset') or 'lifetime'})"
        )
    else:
        lines.append("  key spending limit: none set")
    if status.get("spent_today_usd") is not None:
        lines.append(f"  spent today on this key: ${status['spent_today_usd']:.4f}")
    return lines


def audit_line(entry, key: str) -> str:
    """Whether a request carrying the audit is accepted: the beta admission check."""
    model = entry.models[0] if entry.models else ""
    if not model:
        return "  audit: no model to ask"
    try:
        import httpx  # noqa: PLC0415

        response = httpx.post(
            f"{entry.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"}, timeout=120,
            json={"model": model, "max_tokens": 300, "messages": [
                {"role": "user", "content": "Reply with the single word: ready"}],
                "plugins": [alignment.plugin()]},
        )
    except Exception as exc:  # noqa: BLE001
        return f"  audit: could not ask ({exc})"
    if response.status_code == 200:
        return "  audit: ADMITTED (a request carrying it came back 200)"
    return f"  audit: not usable, HTTP {response.status_code}: {response.text[:200]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--audit", action="store_true",
                        help="also ask whether the Alignment beta accepts this account")
    args = parser.parse_args()
    shown = 0
    for entry in profile.active().providers:
        key = providers.api_key(entry.name)
        if not key or not entry.base_url:
            continue
        shown += 1
        print(f"{entry.name} ({entry.base_url})")
        adapter = providers.build(entry.name, key)
        print("\n".join(status_lines(entry.name, adapter)))
        listed = catalogue(entry)
        if listed:
            free = sum(1 for item in listed if str(item.get("id", "")).endswith(":free"))
            print(f"  catalogue: {len(listed)} models, {free} of them free")
            print("\n".join(lineup_lines(entry, listed)))
        else:
            print("  catalogue: not listed")
        if args.audit:
            print(audit_line(entry, key))
    if not shown:
        print("No provider in the profile has a key and a base URL in this environment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
