from __future__ import annotations

import argparse

import uvicorn

from ontology.service_factory import build_ontology_main_server_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(build_ontology_main_server_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
