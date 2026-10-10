"""Conservative, shared classification of user-reported incident outcomes.

Only an unambiguous affirmative confirmation resolves an incident. Failure wins
over success anywhere in a mixed report; uncertainty leaves the state unchanged.
"""
from __future__ import annotations

import re

_SUCCESS = re.compile(
    r"\b(?:that fixed it|it works now|it is working now|it's working now|"
    r"working now|(?:the )?problem is fixed|(?:i )?solved it)\b"
)
_CONFIRMATION = re.compile(
    r"(?:yes[,! ]*|thanks[,! ]*|thank you[,! ]*)?"
    r"(?:that fixed it|it works now|it is working now|it's working now|"
    r"(?:the )?problem is fixed|(?:i )?solved it)"
    r"[.! ]*(?:(?:thanks|thank you)[.! ]*)?"
)
_FAILURE = re.compile(
    r"\b(?:not working|does not work|doesn't work|won't work|wont work|"
    r"(?:did not|didn't|does not|doesn't|has not|hasn't|not) (?:\w+ ){0,4}(?:work|fix|fixed|solve|solved)|"
    r"(?:don't|do not|didn't|did not) think (?:\w+ ){0,4}(?:fixed|works|working|solved)|"
    r"broken|crash(?:es|ed|ing)?|failing|failed|failure|error|stuck|jitter|"
    r"warping|binding|misaligned|overheat(?:ing)?|too hot|too large|"
    r"doesn't fit|does not fit|same error|no longer works|broke again|"
    r"(?:the |it |that )?(?:fix|repair) failed)\b"
)
_REOPEN = re.compile(r"\breopen (?:this |the |my )?(?:incident|issue|problem)\b")
_UNCERTAIN = re.compile(
    r"\b(?:if|unless|can|could|would|should|will|might|may|maybe|perhaps|"
    r"hope|hopefully|think|guess|unsure|uncertain|not|never|don't|didn't|"
    r"was|were|used to|yesterday|previously|earlier|before|last time|"
    r"said|says|say|quoted|claim|claimed|suppose|assuming|whether)\b"
)


def classify_outcome(text):
    """Return failed, reopen, resolved, uncertain, or none; never infer success."""
    raw = str(text)
    low = " ".join(raw.casefold().replace("’", "'").split())
    success = bool(_SUCCESS.search(low))
    failure = bool(_FAILURE.search(low))
    reopen = bool(_REOPEN.search(low))
    ambiguous = ("?" in raw or any(mark in raw for mark in ('"', '“', '”'))
                 or bool(_UNCERTAIN.search(low)))
    # Even a question about a failure cannot confirm success. Do not reopen on
    # hypothetical/question-only failures, but mixed success/failure stays open.
    if failure:
        if success or not ambiguous:
            return "failed"
        # Explicit negative current reports remain failures despite "not".
        if not ("?" in raw or re.search(r"\b(if|unless|could|would|should|might|may)\b", low)):
            return "failed"
        return "uncertain"
    if reopen:
        return "uncertain" if ambiguous else "reopen"
    if success:
        return "resolved" if not ambiguous and _CONFIRMATION.fullmatch(low) else "uncertain"
    return "none"
