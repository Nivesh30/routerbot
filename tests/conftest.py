"""Shared test fixtures and configuration."""

import logging

import pytest

# aiosqlite's background worker thread logs a debug line after some tests'
# event loops (and pytest's captured log stream) have already closed,
# producing a spurious "ValueError: I/O operation on closed file" in output.
# Silence its debug logging so only warnings/errors surface.
logging.getLogger("aiosqlite").setLevel(logging.WARNING)


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio as the async backend for tests."""
    return "asyncio"
