from __future__ import annotations

"""Lazy distillation pipeline: raw transcripts → memories + instincts.

Key components:
- gemma.py: HTTP client for local Gemma + OpenAI-compatible providers
- extraction.py: Single-call unified extraction (memories + instincts)
- prefilter.py: Heuristic gate at ingest time (no LLM)
- backlog.py: FIFO drop policy when pending exceeds ceiling
- scheduler.py: Idle window / temp / load / overflow gating
- budget.py: Monthly USD cap for external LLM
- distillation_worker.py: The single lazy worker
- profile.py: Periodic user-profile summarizer
"""
