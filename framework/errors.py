"""Exceptions for the graph-governed credibility framework."""

from __future__ import annotations


class GraphValidationError(ValueError):
    """Raised when the standalone graph violates the declared schema."""
