"""Small runtime-only ownership records. No Qt or project serialization here."""
from dataclasses import dataclass, field

@dataclass
class Scope:
    id: int
    kind: str
    frame: object
    parent: object = None
    on_complete: object = None
    children: set = field(default_factory=set)  # membership only; never used for service order
    sealed: bool = False
    done: bool = False
    cancelled: bool = False
    returned: bool = False
    results: dict = field(default_factory=dict)
    outcome: str | None = None
    loop_task: int | None = None

@dataclass
class Task:
    id: int
    frame: object
    node: object
    scope: Scope
    origin: object
    waiting: bool = False
    state: dict = field(default_factory=dict)
