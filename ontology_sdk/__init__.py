"""Generic ontology SDK facade."""

from .client import FoundryClient
from .edits import OntologyEdits

__all__ = ["FoundryClient", "OntologyEdits"]
