"""Vertex AI: an OpenAI-compatible endpoint that has no API key at all.

The whole of this module is the difference between a static key and a rotating
one. Vertex serves the same `/chat/completions` shape as every other provider
here, so `OpenAICompatProvider` already does the work; what it cannot do is
`Authorization: Bearer <thing that expires in an hour>`.

Why bother, when a Gemini key is one click away: an API key is a durable
credential that has to be created, stored, mounted, rotated, kept out of a
public repository, and kept in the right project — and a key in the wrong
project is billed at a different tier, which is invisible until the invoice.
A token minted per hour from the instance's own identity has none of those
properties. Nothing is stored, so nothing leaks; `sage-run` either has
`roles/aiplatform.user` or it does not.

It is also the only route that spends Google Cloud credit. The Gemini Developer
API (`generativelanguage.googleapis.com`) bills against an AI Studio prepayment
balance, which a Cloud Billing account and its $300 are simply not connected to
— measured, as `Your prepayment credits are depleted` from a key minted inside a
project with billing enabled and the credit unspent.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from ..profile import ProviderEntry
from .openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)

# Present on every Google compute surface and nowhere else, which is the point:
# off Google infrastructure this provider is simply unavailable, and says so once
# in the log rather than failing per request.
_METADATA = "http://metadata.google.internal/computeMetadata/v1"
_TOKEN_URL = f"{_METADATA}/instance/service-accounts/default/token"
_PROJECT_URL = f"{_METADATA}/project/project-id"
_HEADERS = {"Metadata-Flavor": "Google"}
# Refresh this far before expiry. A token that dies mid-stream is a failed turn,
# and the cost of refreshing early is one HTTP call to a link-local address.
_SKEW_SECONDS = 300

# `global` rather than a region, and it is not a default worth changing lightly:
# `us-central1` publishes gemini-2.5-flash and returns `Publisher model ... not
# found` for 3.5, 3.6 and 3.8. The newest models are only on the global endpoint.
_LOCATION = "global"


class VertexProvider(OpenAICompatProvider):
    """OpenAI-compatible Vertex, authenticated by the instance, not by a secret."""

    def __init__(self, entry: ProviderEntry, api_key: str) -> None:
        super().__init__(entry, api_key)
        self._token = ""
        self._expires_at = 0.0
        self._lock = threading.Lock()
        self._resolved_base = ""

    # -- identity ----------------------------------------------------------
    def _access_token(self) -> str:
        """The instance's own token, cached until shortly before it expires.

        `SAGE_VERTEX_TOKEN` wins if set, so a laptop can export
        `gcloud auth print-access-token` and exercise this path without deploying.
        """
        # NOT `self._key`. `key_env` is `SAGE_VERTEX`, an enablement switch whose value
        # is "1" — sending that as a bearer token would be a 401 on every turn with a
        # cause nothing in the log points at. A real token can still be supplied for a
        # local run, under a name that says it is one.
        override = os.getenv("SAGE_VERTEX_TOKEN", "")
        if override:
            return override
        with self._lock:
            if self._token and time.time() < self._expires_at:
                return self._token
            try:
                import httpx  # noqa: PLC0415

                response = httpx.get(_TOKEN_URL, headers=_HEADERS, timeout=5)
                response.raise_for_status()
                payload = response.json()
                self._token = str(payload.get("access_token", ""))
                self._expires_at = time.time() + max(
                    0.0, float(payload.get("expires_in", 0)) - _SKEW_SECONDS
                )
            except Exception as exc:
                # Not an error: off Google infrastructure there is no metadata
                # server, and a provider that cannot authenticate should drop out
                # of the lineup quietly rather than take the turn down.
                logger.info("Vertex is unavailable here (%s)", exc)
                self._token, self._expires_at = "", 0.0
            return self._token

    def _headers(self) -> dict:
        token = self._access_token()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if self.entry.user_agent:
            headers["User-Agent"] = self.entry.user_agent
        return headers

    # -- endpoint ----------------------------------------------------------
    @property
    def _base(self) -> str:
        """The URL carries the project id, so it cannot be a profile literal.

        `profiles/rcc.toml` is the subject, not the deployment, and a project id is
        neither. So it is read from the instance — which means this provider needs
        no configuration at all on Cloud Run — and `base_url` in the profile still
        overrides, for a local run pointed at someone else's project.
        """
        if self._configured_base:
            return self._configured_base
        if self._resolved_base:
            return self._resolved_base
        try:
            import httpx  # noqa: PLC0415

            response = httpx.get(_PROJECT_URL, headers=_HEADERS, timeout=5)
            response.raise_for_status()
            project = response.text.strip()
        except Exception as exc:
            logger.info("Vertex: no project id available here (%s)", exc)
            return ""
        if project:
            self._resolved_base = (
                f"https://aiplatform.googleapis.com/v1/projects/{project}"
                f"/locations/{_LOCATION}/endpoints/openapi"
            )
        return self._resolved_base

    @_base.setter
    def _base(self, value: str) -> None:
        # `OpenAICompatProvider.__init__` assigns to `self._base`; catching it here
        # keeps the profile's value as an override without duplicating the parent's
        # constructor, which would then need keeping in step with it.
        self._configured_base = value
