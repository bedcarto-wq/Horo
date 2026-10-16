from dataclasses import dataclass

@dataclass
class Diagnostic:
    message: str
    graph_id: str | None = None
    node_id: str | None = None
    object_id: str | None = None
    expected: str | None = None
    received: str | None = None
    shape_id: str | None = None

    def describe(self, project):
        g = project.graphs.get(self.graph_id)
        n = g.nodes.get(self.node_id) if g else None
        o = project.nodes.get(self.object_id)
        lines = [self.message]
        if self.graph_id:
            lines.append(f'Граф: {g.name if g else "удалён"} [{self.graph_id}]')
        if self.node_id:
            from .ports import LABELS
            lines.append(f'Узел: {(n.name or LABELS.get(n.kind, n.kind)) if n else "удалён"} [{self.node_id}]')
        if self.object_id:
            lines.append(f'Объект: {o.name if o else "отсутствует"} [{self.object_id}]')
        if self.shape_id:
            shape = project.nodes.get(self.shape_id)
            lines.append(f'Форма: {shape.name if shape else "отсутствует"} [{self.shape_id}]')
        if self.expected is not None:
            lines.append(f'Ожидалось: {self.expected}; получено: {self.received}')
        return '\n'.join(lines)

class GraphError(Exception):
    def __init__(self, diagnostic):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic
