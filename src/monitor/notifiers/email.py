from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from monitor.models import Alert

log = logging.getLogger(__name__)


class EmailNotifier:
    name = "email"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        recipient: str,
        use_tls: bool,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._recipient = recipient
        self._use_tls = use_tls

    async def send(self, alert: Alert) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = self._recipient
        message["Subject"] = f"[{alert.severity.upper()}] {alert.title}"
        body = alert.detail or ""
        if alert.source:
            body = f"{body}\n\nsource: {alert.source}".strip()
        message.set_content(body)

        await aiosmtplib.send(
            message,
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            start_tls=self._use_tls,
        )
