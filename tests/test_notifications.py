import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from ontology import NotificationDispatcher, NotificationMessage, WebhookDispatcher


def test_notification_dispatcher_records() -> None:
    dispatcher = NotificationDispatcher()
    dispatcher.send(
        NotificationMessage(channel="email", subject="Hello", body="World", metadata={"k": "v"})
    )
    assert dispatcher.sent[0].subject == "Hello"


def test_webhook_dispatcher_posts() -> None:
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            data = self.rfile.read(length)
            received["payload"] = json.loads(data.decode("utf-8"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A002
            return

    server = HTTPServer(("localhost", 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    dispatcher = WebhookDispatcher(timeout_s=2.0, secret="secret")
    status = dispatcher.post(f"http://localhost:{server.server_port}", {"ok": True})

    thread.join(timeout=2.0)
    server.server_close()

    assert status == 200
    assert received["payload"] == {"ok": True}
