"""Compact runtime dialogue records; source metadata lives in authoring-index.json."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DialogueRecord:
    default: Optional[str]
    variants: Dict[str, List[Dict[str, Any]]]
    branches: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


@dataclass
class FlatDialogueRecord:
    """The sole, selected standard-dialogue variant; entry conditions still apply."""

    steps: List[Dict[str, Any]]
    branches: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
