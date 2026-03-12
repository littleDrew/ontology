from __future__ import annotations

import argparse

import uvicorn

from scripts.object_monitor.service_factory import build_object_monitor_server_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--action-base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--data-plane-base-url", default=None)
    args = parser.parse_args()

    data_plane_base_url = args.data_plane_base_url or f"http://{args.host}:{args.port}"
    uvicorn.run(
        build_object_monitor_server_app(
            action_base_url=args.action_base_url,
            data_plane_base_url=data_plane_base_url,
        ),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
