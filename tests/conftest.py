"""
tests/conftest.py — shared pytest fixtures.

Provides make_unit() helper so golden-example tests stay concise.
No external services required for annotator tests.
"""
from __future__ import annotations

import hashlib

import pytest

from annotators.base import TextUnit


def make_unit(text: str, role: str = "body") -> TextUnit:
    """
    Build a minimal TextUnit for annotator testing.
    All non-text fields are set to safe defaults.
    """
    tu_id = f"test:repo:1:{role}"
    return TextUnit(
        text_unit_id  = tu_id,
        parent_id     = "test:repo:1",
        parent_type   = "issue",
        repo          = "test/repo",
        parent_number = 1,
        role          = role,
        position      = 1,
        text          = text,
        lang          = "en",
        token_count   = len(text.split()),
        sha256        = hashlib.sha256(text.encode()).hexdigest(),
        author_login  = None,
        created_at    = None,
    )


@pytest.fixture
def unit_factory():
    """Fixture wrapping make_unit so test functions receive it as a dependency."""
    return make_unit
