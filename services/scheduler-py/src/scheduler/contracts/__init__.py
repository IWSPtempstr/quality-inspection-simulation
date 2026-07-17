"""Validated immutable data contracts shared by later scheduler adapters."""

from scheduler.contracts.candidate import ScheduleCandidate, parse_schedule_candidate
from scheduler.contracts.snapshot import SchedulingSnapshot, parse_scheduling_snapshot

__all__ = [
    "ScheduleCandidate",
    "SchedulingSnapshot",
    "parse_schedule_candidate",
    "parse_scheduling_snapshot",
]
