"""Object monitor package.

Use explicit domain imports in development mode:
- `ontology.object_monitor.define.*`
- `ontology.object_monitor.runtime.*`
"""

from . import define, runtime

__all__ = ["define", "runtime"]
