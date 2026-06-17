from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping, Any


def sla_status(finish_time: datetime, promised_finish_time: datetime | None) -> str:
    if promised_finish_time is None:
        return "not_applicable"
    return "on_time" if finish_time <= promised_finish_time else "delayed"


def delay_minutes(finish_time: datetime, promised_finish_time: datetime | None) -> int:
    if promised_finish_time is None or finish_time <= promised_finish_time:
        return 0
    return int((finish_time - promised_finish_time).total_seconds() // 60)


def rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def sla_rate(orders: Iterable[Mapping[str, Any]]) -> float:
    order_list = list(orders)
    if not order_list:
        return 1.0
    return rate(sum(1 for order in order_list if order.get("sla_status") == "on_time"), len(order_list))


def delay_rate(orders: Iterable[Mapping[str, Any]]) -> float:
    order_list = list(orders)
    return rate(sum(1 for order in order_list if order.get("sla_status") == "delayed"), len(order_list))
