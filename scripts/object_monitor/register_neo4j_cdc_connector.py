from __future__ import annotations

import argparse
import json

from ontology.object_monitor.runtime import KafkaConnectClient, Neo4jKafkaSourceConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Register Neo4j CDC source connector into Kafka Connect")
    parser.add_argument("--connect-url", required=True)
    parser.add_argument("--connector-name", default="objm-neo4j-cdc")
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", required=True)
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--kafka-topic", default="object_change_raw")
    parser.add_argument("--pattern", action="append", default=["(:Device)"])
    args = parser.parse_args()

    config = Neo4jKafkaSourceConfig(
        connector_name=args.connector_name,
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        neo4j_database=args.neo4j_database,
        kafka_topic=args.kafka_topic,
        cdc_patterns=args.pattern,
    )
    payload = config.to_connector_payload()
    client = KafkaConnectClient(args.connect_url)
    result = client.create_or_replace(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
