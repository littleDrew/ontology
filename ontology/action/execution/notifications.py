from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, List, Optional
from urllib import request
import hmac
import hashlib


@dataclass
class NotificationMessage:
    channel: str
    subject: str
    body: str
    metadata: Optional[Dict[str, Any]] = None


class NotificationDispatcher:
    def __init__(self) -> None:
        self.sent: List[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> None:
        self.sent.append(message)


class WebhookDispatcher:
    def __init__(self, timeout_s: float = 3.0, secret: Optional[str] = None) -> None:
        self._timeout_s = timeout_s
        self._secret = secret

    def post(self, url: str, payload: Dict[str, Any]) -> int:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._secret:
            signature = hmac.new(self._secret.encode("utf-8"), data, hashlib.sha256).hexdigest()
            headers["X-Signature"] = signature
        req = request.Request(url, data=data, headers=headers)
        with request.urlopen(req, timeout=self._timeout_s) as resp:
            return resp.status
