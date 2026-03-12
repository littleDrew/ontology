from __future__ import annotations

import argparse

import uvicorn

from scripts.object_monitor.service_factory import build_object_monitor_server_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--action-base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--kafka-bootstrap-servers", default=None)
    parser.add_argument("--kafka-topic", default="object_change_raw")
    parser.add_argument("--kafka-group-id", default="object-monitor-runtime")
    args = parser.parse_args()

    uvicorn.run(
        build_object_monitor_server_app(
            action_base_url=args.action_base_url,
            kafka_bootstrap_servers=args.kafka_bootstrap_servers,
            kafka_topic=args.kafka_topic,
            kafka_group_id=args.kafka_group_id,
        ),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
