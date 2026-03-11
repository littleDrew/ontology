from __future__ import annotations

import argparse
import uvicorn

from ontology.service_factory import build_object_monitor_data_plane_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--action-base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    uvicorn.run(build_object_monitor_data_plane_app(action_base_url=args.action_base_url), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
