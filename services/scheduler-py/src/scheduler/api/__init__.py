"""Authenticated internal scheduler ingress for S4 only."""

from scheduler.api.app import create_app

__all__ = ["create_app"]
