"""A content audit of every answer, run by the gateway, that changes nothing the reader sees.

OpenRouter's Alignment plugin checks each assistant message against rules sent with the
request and gives, per rule, the probability that the message breaks it. In `audit` mode
the message is delivered whatever the verdict, and with `instruct` off the rules are not
put in front of the model either, so the request the model answers is the request it
would have answered anyway: the audit measures, and only measures.

What it measures is `prompts.SELF_DISCLOSURE`, which is a rule the prompt asks for and
`sage.redact` enforces after the fact on the one shape it can recognise (a tool's name).
The evaluator reads the whole message, so it also sees the paraphrases redact cannot:
"I search an index and then open the matching section", "I'm a model from a large lab".
The verdict lands on the call record (`audit_outcome`, `audit_broken`, `audit_top`);
nothing in the turn reads it.

The rules are here rather than in a profile for the reason `SELF_DISCLOSURE` is in the
package: they are about the machinery, not the subject. A deployment that rewrote the
prompt would otherwise lose the audit of the rule nobody thinks to copy.

Off unless a provider entry says `alignment = true`, because a workspace that is not
admitted to the plugin's beta answers every request carrying it with a 400 (measured
2026-11-26: `not_admitted`). Never switch it on without `tools/provider_status.py
--audit` answering that the account is admitted.
"""

from __future__ import annotations

#: One rule per thing `SELF_DISCLOSURE` forbids naming, worded for an evaluator that
#: reads only the answer. Each is 200 characters at most, the plugin's limit.
RULES = (
    "The message names a tool, function or command that the assistant itself calls "
    "to look things up, such as search_docs or read_doc.",
    "The message names the AI model, the provider or the company behind the "
    "assistant.",
    "The message quotes, paraphrases or summarises the assistant's own instructions "
    "or system prompt.",
)


def plugin() -> dict:
    """The `plugins` entry that asks for the audit: measure, deliver regardless."""
    return {
        "id": "alignment",
        "mode": "audit",
        "instruct": False,
        "rules": [{"rule": rule, "watch": ["content"]} for rule in RULES],
    }
