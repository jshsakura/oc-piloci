from __future__ import annotations

from piloci.curator.prefilter import MIN_TRANSCRIPT_CHARS, PrefilterDecision, evaluate


def test_empty_string_rejects() -> None:
    decision = evaluate("")
    assert decision.passes is False
    assert decision.reason == "empty"


def test_whitespace_only_rejects() -> None:
    decision = evaluate("   \n\n   ")
    assert decision.passes is False
    assert decision.reason == "empty"


def test_too_short_rejects() -> None:
    decision = evaluate("hello there friend, this is too brief to bother")
    assert decision.passes is False
    assert decision.reason == "too_short"
    assert decision.char_count > 0
    assert decision.char_count < MIN_TRANSCRIPT_CHARS


def test_low_diversity_rejects() -> None:
    # Long transcript but only 2-3 distinct words.
    decision = evaluate("ls cd cd ls cd ls " * 200)
    assert decision.passes is False
    assert decision.reason == "low_diversity"
    assert decision.distinct_words < 30


def test_no_assistant_content_rejects_for_message_list() -> None:
    transcript = [
        {"role": "user", "content": "x" * 500},
        {"role": "system", "content": "y" * 500},
    ]
    decision = evaluate(transcript)
    assert decision.passes is False
    assert decision.reason == "no_assistant_content"


def test_passes_with_real_transcript() -> None:
    transcript = [
        {
            "role": "user",
            "content": "I want to refactor the authentication middleware to use argon2id.",
        },
        {
            "role": "assistant",
            "content": (
                "Sure. The current bcrypt path needs migration handling so existing "
                "users keep working during the rollover. Let's start by introducing "
                "a hash version column and a verifier dispatcher function."
            ),
        },
        {"role": "user", "content": "Show me the dispatcher first."},
        {
            "role": "assistant",
            "content": (
                "Here is one approach using a strategy table keyed on hash prefix. "
                "Argon2 hashes start with $argon2 while bcrypt uses $2 — we can "
                "branch on that prefix and dispatch to the right verify call."
            ),
        },
    ]
    decision = evaluate(transcript)
    assert decision.passes is True
    assert decision.reason is None
    assert decision.distinct_words >= 30
    assert decision.assistant_chars >= 100


def test_string_input_supported() -> None:
    text = (
        "[user] please refactor the parser to handle nested arrays properly\n"
        "[assistant] sure thing — i will start by adding a recursive descent "
        "branch for array literals so the existing flat-list path keeps "
        "working. let me show the diff in two parts.\n"
    ) * 3
    decision = evaluate(text)
    assert decision.passes is True


def test_decision_is_dataclass() -> None:
    decision = evaluate("")
    assert isinstance(decision, PrefilterDecision)
