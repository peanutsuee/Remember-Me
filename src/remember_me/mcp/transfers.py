# SPDX-License-Identifier: CPAL-1.0
"""Short-lived signed upload and download authorization tickets."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from urllib.parse import quote


DEFAULT_TICKET_TTL_SECONDS = 5 * 60
MAX_ACTIVE_TICKETS = 1024
MAX_DOWNLOAD_GETS = 3


class TransferError(Exception):
    code = "transfer_unavailable"


class TransferInvalid(TransferError):
    code = "transfer_invalid"


class TransferExpired(TransferError):
    code = "transfer_expired"


class TransferConflict(TransferError):
    code = "transfer_conflict"


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _expires_at(timestamp: float) -> str:
    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    ).isoformat(timespec="seconds")


def _signed_url(
    base_url: str,
    path: str,
    ticket_token: str,
) -> str:
    return "{}{}?ticket={}".format(
        base_url,
        path,
        quote(ticket_token, safe=""),
    )


@dataclass
class UploadTicket:
    upload_id: str
    token_digest: bytes
    expected_bytes: int
    filename: str
    mime_type: str
    expires_timestamp: float
    status: str = "pending"
    asset: object = None
    deduplicated: Optional[bool] = None
    error_code: str = ""

    @property
    def expires_at(self) -> str:
        return _expires_at(self.expires_timestamp)


class UploadTicketStore:
    def __init__(
        self,
        base_url: Optional[str],
        *,
        ttl_seconds: int = DEFAULT_TICKET_TTL_SECONDS,
        max_tickets: int = MAX_ACTIVE_TICKETS,
        now=None,
    ):
        self.base_url = base_url
        self.ttl_seconds = ttl_seconds
        self.max_tickets = max_tickets
        self._now = now or time.time
        self._tickets: Dict[str, UploadTicket] = {}
        self._lock = threading.Lock()

    def create(
        self,
        expected_bytes: int,
        filename: str,
        mime_type: str,
    ) -> Tuple[UploadTicket, str]:
        with self._lock:
            if self.base_url is None:
                raise TransferInvalid()
            self._purge_locked()
            if len(self._tickets) >= self.max_tickets:
                raise TransferConflict()
            upload_id = secrets.token_hex(16)
            token = secrets.token_urlsafe(32)
            ticket = UploadTicket(
                upload_id=upload_id,
                token_digest=_digest(token),
                expected_bytes=expected_bytes,
                filename=filename,
                mime_type=mime_type,
                expires_timestamp=self._now() + self.ttl_seconds,
            )
            self._tickets[upload_id] = ticket
            return ticket, _signed_url(
                self.base_url,
                "/transfers/uploads/{}".format(upload_id),
                token,
            )

    def inspect(self, upload_id: str) -> UploadTicket:
        with self._lock:
            ticket = self._lookup_locked(upload_id)
            if (
                ticket.status in {"pending", "processing"}
                and self._now() >= ticket.expires_timestamp
            ):
                ticket.status = "expired"
            return ticket

    def authorize_pending(
        self,
        upload_id: str,
        token: str,
        *,
        consume: bool,
    ) -> UploadTicket:
        with self._lock:
            ticket = self._lookup_locked(upload_id)
            self._expire_locked(ticket)
            if not secrets.compare_digest(
                ticket.token_digest,
                _digest(token),
            ):
                raise TransferInvalid()
            if ticket.status != "pending":
                raise TransferConflict()
            if consume:
                ticket.status = "processing"
            return ticket

    def complete(self, upload_id: str, asset, deduplicated: bool) -> None:
        with self._lock:
            ticket = self._lookup_locked(upload_id)
            if ticket.status != "processing":
                raise TransferConflict()
            ticket.asset = asset
            ticket.deduplicated = bool(deduplicated)
            ticket.status = "completed"

    def fail(self, upload_id: str, code: str = "upload_failed") -> None:
        with self._lock:
            ticket = self._tickets.get(upload_id)
            if ticket is not None:
                ticket.status = "failed"
                ticket.error_code = code

    def _lookup_locked(self, upload_id: str) -> UploadTicket:
        ticket = self._tickets.get(upload_id)
        if ticket is None:
            raise TransferInvalid()
        return ticket

    def _expire_locked(self, ticket: UploadTicket) -> None:
        if (
            ticket.status in {"pending", "processing"}
            and self._now() >= ticket.expires_timestamp
        ):
            ticket.status = "expired"
        if ticket.status == "expired":
            raise TransferExpired()

    def _purge_locked(self) -> None:
        now = self._now()
        removable = [
            ticket_id
            for ticket_id, ticket in self._tickets.items()
            if now >= ticket.expires_timestamp
        ]
        for ticket_id in removable:
            self._tickets.pop(ticket_id, None)


@dataclass
class DownloadTicket:
    download_id: str
    token_digest: bytes
    asset_id: str
    expires_timestamp: float
    remaining_gets: int = MAX_DOWNLOAD_GETS
    valid: bool = True

    @property
    def expires_at(self) -> str:
        return _expires_at(self.expires_timestamp)


class DownloadTicketStore:
    def __init__(
        self,
        base_url: Optional[str],
        *,
        ttl_seconds: int = DEFAULT_TICKET_TTL_SECONDS,
        max_tickets: int = MAX_ACTIVE_TICKETS,
        now=None,
    ):
        self.base_url = base_url
        self.ttl_seconds = ttl_seconds
        self.max_tickets = max_tickets
        self._now = now or time.time
        self._tickets: Dict[str, DownloadTicket] = {}
        self._lock = threading.Lock()

    def create(self, asset_id: str) -> Tuple[DownloadTicket, str]:
        with self._lock:
            if self.base_url is None:
                raise TransferInvalid()
            self._purge_locked()
            if len(self._tickets) >= self.max_tickets:
                raise TransferConflict()
            download_id = secrets.token_hex(16)
            token = secrets.token_urlsafe(32)
            ticket = DownloadTicket(
                download_id=download_id,
                token_digest=_digest(token),
                asset_id=asset_id,
                expires_timestamp=self._now() + self.ttl_seconds,
            )
            self._tickets[download_id] = ticket
            return ticket, _signed_url(
                self.base_url,
                "/transfers/downloads/{}".format(download_id),
                token,
            )

    def authorize(
        self,
        download_id: str,
        token: str,
        *,
        consume: bool,
    ) -> DownloadTicket:
        with self._lock:
            ticket = self._tickets.get(download_id)
            if ticket is None or not ticket.valid:
                raise TransferInvalid()
            if self._now() >= ticket.expires_timestamp:
                ticket.valid = False
                raise TransferExpired()
            if not secrets.compare_digest(
                ticket.token_digest,
                _digest(token),
            ):
                raise TransferInvalid()
            if ticket.remaining_gets <= 0:
                ticket.valid = False
                raise TransferConflict()
            if consume:
                ticket.remaining_gets -= 1
                if ticket.remaining_gets == 0:
                    ticket.valid = False
            return ticket

    def invalidate(self, download_id: str) -> None:
        with self._lock:
            ticket = self._tickets.get(download_id)
            if ticket is not None:
                ticket.valid = False

    def _purge_locked(self) -> None:
        now = self._now()
        removable = [
            ticket_id
            for ticket_id, ticket in self._tickets.items()
            if not ticket.valid or now >= ticket.expires_timestamp
        ]
        for ticket_id in removable:
            self._tickets.pop(ticket_id, None)
