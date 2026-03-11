from __future__ import annotations

import argparse
import uvicorn

from ontology.service_factory import build_change_capture_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--data-plane-base-url", default="http://127.0.0.1:8771")
    args = parser.parse_args()
    uvicorn.run(build_change_capture_app(data_plane_base_url=args.data_plane_base_url), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
