"""Pure text preparation for privacy-safe Kira/Robert dialogue TTS.

The helpers in this module deliberately do not import a speech model.  That
lets the renderer and the non-playing review path prove that every public
SPOKEN word was queued, apart from explicitly omitted dialogue names, without
loading Chatterbox or an audio device.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any


_DIALOGUE_NAME_RE = re.compile(
    r"\b(?:Robert(?:\s+McMurrer)?|Kira)(?:['\u2019]s)?\b",
    flags=re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019][A-Za-z0-9]+)*")
_SENTENCE_RE = re.compile(r".+?(?:[.!?]+(?=\s|$)|$)", flags=re.DOTALL)


def spoken_words(text: str) -> list[str]:
    """Return normalized spoken words in their original order."""

    return [match.group(0).casefold() for match in _WORD_RE.finditer(str(text or ""))]


def clean_spoken_text(text: str) -> str:
    """Remove markup while retaining the public words and their order."""

    cleaned = str(text or "").strip()
    # Remove Markdown fence syntax, not the public words inside the fence.  A
    # conventional opening language tag is markup and is removed only when it
    # appears immediately after the opening fence and before a newline.
    cleaned = re.sub(r"```[A-Za-z0-9_+.-]*\r?\n", " ", cleaned)
    cleaned = cleaned.replace("```", " ")
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_#>~]+", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def omit_dialogue_names(text: str) -> tuple[str, int]:
    """Remove only Kira/Robert name tokens from a public spoken turn.

    Voices already identify the two speakers.  The transform intentionally
    leaves every non-name word untouched, even when a resulting sentence is a
    little terse, so the renderer can make an exact word-coverage assertion.
    """

    removed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal removed
        removed += 1
        return ""

    value = _DIALOGUE_NAME_RE.sub(replace, str(text or ""))
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r",\s*,+", ",", value)
    value = re.sub(r"(^|[.!?]\s+),\s*", r"\1", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value, removed


def prepare_tts_turns(
    turns: list[dict[str, Any]],
    *,
    omit_names: bool = True,
    prefix_speaker_names: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Prepare turns and assert exact non-name public-word coverage."""

    prepared: list[dict[str, Any]] = []
    removed_name_occurrences = 0
    public_word_count = 0
    queued_word_count = 0
    for index, item in enumerate(turns, 1):
        speaker = str(item.get("speaker") or "").strip()
        public_text = clean_spoken_text(str(item.get("text") or ""))
        if not public_text:
            raise ValueError(f"Turn {index} has no public spoken text")
        queued_text, removed = (
            omit_dialogue_names(public_text) if omit_names else (public_text, 0)
        )
        if not queued_text:
            raise ValueError(f"Turn {index} contains only omitted dialogue names")

        expected_text = _DIALOGUE_NAME_RE.sub("", public_text) if omit_names else public_text
        expected_words = spoken_words(expected_text)
        base_queued_words = spoken_words(queued_text)
        if expected_words != base_queued_words:
            raise ValueError(f"Turn {index} failed exact non-name word coverage")
        if omit_names and _DIALOGUE_NAME_RE.search(queued_text):
            raise ValueError(f"Turn {index} still contains a dialogue name")
        if prefix_speaker_names:
            queued_text = f"{speaker}. {queued_text}"
        queued_words = spoken_words(queued_text)

        public_word_count += len(spoken_words(public_text))
        queued_word_count += len(queued_words)
        removed_name_occurrences += removed
        prepared.append(
            {
                "speaker": speaker,
                "text": queued_text,
                "public_text_sha256": hashlib.sha256(public_text.encode("utf-8")).hexdigest(),
                "tts_text_sha256": hashlib.sha256(queued_text.encode("utf-8")).hexdigest(),
                "removed_dialogue_name_occurrences": removed,
                "non_name_word_coverage_exact": True,
            }
        )

    combined = "\n".join(f"{item['speaker']}\t{item['text']}" for item in prepared)
    return prepared, {
        "schema_version": 1,
        "transform": "public_spoken_words_with_dialogue_names_omitted" if omit_names else "public_spoken_words_unchanged",
        "dialogue_names_spoken": not omit_names,
        "speaker_labels_spoken": prefix_speaker_names,
        "turn_count": len(prepared),
        "public_word_count_before_name_omission": public_word_count,
        "queued_word_count": queued_word_count,
        "removed_dialogue_name_occurrences": removed_name_occurrences,
        "non_name_word_coverage_exact": True,
        "tts_payload_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
    }


def _split_long_unit(unit: str, max_chars: int) -> list[str]:
    """Split an oversized sentence without dropping or reordering words."""

    if len(unit) <= max_chars:
        return [unit.strip()]

    # Prefer a natural clause boundary.  Punctuation stays in the same chunk
    # as the words before it, preserving the exact original word sequence.
    clauses = [part.strip() for part in re.split(r"(?<=[,;:\u2014\u2013])\s+", unit) if part.strip()]
    if len(clauses) > 1:
        chunks: list[str] = []
        current = ""
        for clause in clauses:
            candidate = f"{current} {clause}".strip()
            if current and len(candidate) > max_chars:
                chunks.extend(_split_long_unit(current, max_chars))
                current = clause
            else:
                current = candidate
        if current:
            chunks.extend(_split_long_unit(current, max_chars) if len(current) > max_chars else [current])
        return chunks

    # A model can produce a single very long punctuation-free sentence.  In
    # that case split only at whitespace.  No word is truncated or discarded.
    chunks = []
    current = ""
    for word in unit.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _rebalance_short_chunks(
    chunks: list[str],
    max_chars: int,
    *,
    min_chars: int = 32,
    first_min_chars: int = 56,
) -> list[str]:
    """Avoid tiny audible fragments without changing the spoken word order.

    Clause-first splitting can otherwise produce pieces such as ``In my
    mind,`` or ``romantic.`` as standalone audio jobs.  Those pieces sound
    like cut-offs and make a slow synthesizer insert a long silent gap around
    only one or two words.  Rebalancing moves whole whitespace-delimited
    tokens across the adjacent boundary; it never drops or reorders words and
    never exceeds ``max_chars``.
    """

    balanced = [part.strip() for part in chunks if part.strip()]
    if len(balanced) < 2:
        return balanced

    # The first waveform begins playing as soon as it is ready while the next
    # waveform is synthesized.  A very short opening can finish before the
    # producer has made chunk two, causing a visible continuation stall.  A
    # modestly larger first floor preserves low time-to-first-audio while
    # giving the existing producer/consumer prefetch useful playback runway.
    first_floor = min(max_chars, max(min_chars, first_min_chars))
    index = 0
    while index < len(balanced):
        current = balanced[index]
        current_floor = first_floor if index == 0 else min_chars
        if len(current) >= current_floor:
            index += 1
            continue

        # Prefer joining a short tail to the preceding thought.
        if index > 0:
            previous = balanced[index - 1]
            joined = f"{previous} {current}".strip()
            if len(joined) <= max_chars:
                balanced[index - 1] = joined
                del balanced[index]
                index = max(0, index - 1)
                continue

            previous_words = previous.split()
            current_words = current.split()
            while (
                len(" ".join(current_words)) < current_floor
                and len(previous_words) > 1
            ):
                candidate_previous = " ".join(previous_words[:-1])
                candidate_current = " ".join([previous_words[-1], *current_words])
                if len(candidate_current) > max_chars or len(candidate_previous) < min_chars:
                    break
                current_words.insert(0, previous_words.pop())
            balanced[index - 1] = " ".join(previous_words)
            balanced[index] = " ".join(current_words)
            current = balanced[index]
            if len(current) >= current_floor:
                index += 1
                continue

        # A short opening fragment can borrow leading words from the next
        # chunk.  This keeps phrases such as "In my mind," attached to the
        # thought they introduce.
        if index + 1 < len(balanced):
            following = balanced[index + 1]
            joined = f"{current} {following}".strip()
            if len(joined) <= max_chars:
                balanced[index] = joined
                del balanced[index + 1]
                continue

            current_words = current.split()
            following_words = following.split()
            while (
                len(" ".join(current_words)) < current_floor
                and len(following_words) > 1
            ):
                candidate_current = " ".join([*current_words, following_words[0]])
                candidate_following = " ".join(following_words[1:])
                if len(candidate_current) > max_chars or len(candidate_following) < min_chars:
                    break
                current_words.append(following_words.pop(0))
            balanced[index] = " ".join(current_words)
            balanced[index + 1] = " ".join(following_words)

        index += 1

    return balanced


def split_for_tts(text: str, max_chars: int = 180) -> tuple[list[str], dict[str, Any]]:
    """Create short, sentence/clause-aware chunks with exact word coverage."""

    value = str(text or "").strip()
    if not value:
        raise ValueError("Cannot split empty TTS text")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 80:
        raise ValueError("max_chars must be an integer of at least 80")

    sentences = [match.group(0).strip() for match in _SENTENCE_RE.finditer(value) if match.group(0).strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences or [value]:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_unit(sentence, max_chars))
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)

    chunks = _rebalance_short_chunks(chunks, max_chars)

    # A whitespace fallback can otherwise hand Chatterbox a fragment with no
    # prosodic boundary, which sounds like an abrupt cutoff.  A comma adds no
    # spoken word and signals that another chunk follows.
    for index in range(len(chunks) - 1):
        if not re.search(r"[,;:.!?\u2014\u2013-]$", chunks[index]) and len(chunks[index]) < max_chars:
            chunks[index] += ","

    if not chunks or spoken_words(value) != spoken_words(" ".join(chunks)):
        raise ValueError("TTS chunking failed exact word coverage")
    if any(len(chunk) > max_chars and len(chunk.split()) > 1 for chunk in chunks):
        raise ValueError("TTS chunk exceeds the requested bound")
    return chunks, {
        "chunk_count": len(chunks),
        "max_chunk_chars": max(len(chunk) for chunk in chunks),
        "word_count": len(spoken_words(value)),
        "word_coverage_exact": True,
        "chunk_payload_sha256": hashlib.sha256("\n".join(chunks).encode("utf-8")).hexdigest(),
    }
