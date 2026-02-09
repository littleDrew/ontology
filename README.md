# ontology
The Ontology Repository is a robust framework designed to manage, maintain, and execute complex data models for enterprise applications. Similar to Palantir’s Ontology. Key features include: Ontology Model Management, Function & Action Execution, Event Monitoring & Rule Engine, Transaction Guarantees, Role-Based Access Control (RBAC).

## Prerequisites
- Python 3.10+
- (Optional) Neo4j if you want to run the graph-backed store integration

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install fastapi uvicorn sqlalchemy pytest httpx
```

> **Optional:** If you want Neo4j integration, also install the `neo4j` driver:
```bash
pip install neo4j
```

## Run the API (in-memory demo)
The API factory expects a `GraphStore` instance. For a quick local demo, you can boot the service with an in-memory store:
```bash
python - <<'PY'
from ontology import InMemoryGraphStore
from ontology.api import create_app
import uvicorn

store = InMemoryGraphStore()
app = create_app(store)
uvicorn.run(app, host="0.0.0.0", port=8000)
PY
```

Example calls:
```bash
curl http://localhost:8000/objects/Employee/emp-1
```

If you want Action submission endpoints, pass an `ActionService` and repository:
```bash
python - <<'PY'
from ontology import ActionRunner, ActionService, InMemoryActionRepository, InMemoryGraphStore, DataFunnelService
from ontology.api import create_app
import uvicorn

store = InMemoryGraphStore()
repo = InMemoryActionRepository()
service = ActionService(repo, ActionRunner(), DataFunnelService(store))
app = create_app(store, action_service=service, repository=repo)
uvicorn.run(app, host="0.0.0.0", port=8000)
PY
```

## Run tests
```bash
pytest -q
```
