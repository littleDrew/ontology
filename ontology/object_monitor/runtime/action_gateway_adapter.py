from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict
from urllib import error, request

from .thin_action_executor import ActionGateway, ActionGatewayResponse


@dataclass
class OntologyActionApiAdapter(ActionGateway):
    """HTTP adapter for ontology action apply endpoint."""

    base_url: str
    submitter_prefix: str = "monitor"
    timeout_seconds: float = 5.0

    def apply_action(self, *, action_id: str, endpoint: str, payload: dict, idempotency_key: str) -> ActionGatewayResponse:
        request_body: Dict[str, Any] = {
            "submitter": f"{self.submitter_prefix}:{action_id}",
            "input_payload": payload,
            "client_request_id": idempotency_key,
        }
        url = f"{self.base_url.rstrip('/')}/api/v1/actions/{action_id}/apply"
        req = request.Request(
            url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status_code = resp.getcode()
                raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            status_code = exc.code
            raw = exc.read().decode("utf-8") if exc.fp is not None else ""
        except TimeoutError:
            raise
        except Exception as exc:  # noqa: BLE001
            return ActionGatewayResponse(status_code=599, error_code="network_error", error_message=str(exc))

        payload_data: Dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    payload_data = parsed
            except Exception:  # noqa: BLE001
                payload_data = {}

        if status_code < 300:
            return ActionGatewayResponse(status_code=status_code, execution_id=payload_data.get("execution_id"))

        return ActionGatewayResponse(
            status_code=status_code,
            error_code=f"http_{status_code}",
            error_message=str(payload_data.get("detail") or payload_data.get("message") or "request_failed"),
        )
