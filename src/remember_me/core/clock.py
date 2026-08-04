# SPDX-License-Identifier: CPAL-1.0
"""Clock implementations and UTC timestamp formatting."""

from datetime import timezone, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def utc_iso_seconds(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("clock_must_return_datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")
