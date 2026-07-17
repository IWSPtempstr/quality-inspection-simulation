"""Deterministic, solver-free fallback for explicit CP-SAT failures only."""

from scheduler.sla_fallback.fallback import FallbackRejectedError, build_fallback_candidate

__all__ = ["FallbackRejectedError", "build_fallback_candidate"]
