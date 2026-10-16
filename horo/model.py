"""Serializable authoring model. No Qt imports; IDs, not names, are references."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import copy
import math
import uuid

FORMAT_VERSION = 1
TYPES = ('number', 'text', 'bool', 'object', 'vector')
TYPE_LABELS = dict(zip(TYPES, ('Число', 'Текст', 'Логическое', 'Объект', 'Вектор2')))

def uid() -> str:
    return uuid.uuid4().hex

def number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False

def valid_value(kind, value):
    if kind == 'number':
        return number(value)
    if kind == 'text':
        return isinstance(value, str)
    if kind == 'bool':
        return isinstance(value, bool)
    if kind == 'object':
        return value is None or isinstance(value, str)
    if kind == 'vector':
        return isinstance(value, (list, tuple)) and len(value) == 2 and all(number(x) for x in value)
    return False

def initial(kind):
    return {'number': 0, 'text': '', 'bool': False, 'object': None, 'vector': [0, 0]}[kind]

@dataclass
class Transform:
    x: float = 0
    y: float = 0
    sx: float = 1
    sy: float = 1
    rotation: float = 0

    def matrix(self):
        angle = math.radians(self.rotation)
        c, s = math.cos(angle), math.sin(angle)
        return (c*self.sx, s*self.sx, -s*self.sy, c*self.sy, self.x, self.y)


def multiply(a, b):
    """Affine matrices (a,b,c,d,tx,ty); result applies b first, then a."""
    return (a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
            a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
            a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5])

@dataclass
class SceneNode:
    id: str = field(default_factory=uid)
    name: str = 'Объект'
    kind: str = 'transform'
    parent: str | None = None
    transform: Transform = field(default_factory=Transform)
    image: str | None = None
    graph: str | None = None
    width: float = 64
    height: float = 64
    radius: float = 32
    points: list = field(default_factory=lambda: [[-32,-32],[32,-32],[32,32],[-32,32]])

@dataclass
class Variable:
    id: str = field(default_factory=uid)
    name: str = 'Переменная'
    type: str = 'number'
    scope: str = 'object'
    value: object = 0
    owner: str | None = None  # run variables belong to one graph

@dataclass
class Parameter:
    id: str = field(default_factory=uid)
    name: str = 'Параметр'
    type: str = 'number'

@dataclass
class GraphNode:
    id: str = field(default_factory=uid)
    kind: str = 'number'
    name: str = ''
    x: float = 0
    y: float = 0
    params: dict = field(default_factory=dict)
    region: str | None = None  # owner repeat node; None = root region
    expanded: bool = True
    outputs: list[str] = field(default_factory=list)  # ordered stable exec ports

@dataclass
class Edge:
    source: str
    output: str
    target: str
    input: str
    id: str = field(default_factory=uid)

@dataclass
class Graph:
    id: str = field(default_factory=uid)
    name: str = 'Граф'
    kind: str = 'behavior'
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    results: list[Parameter] = field(default_factory=list)

    def add(self, kind, pos_x=0, pos_y=0, region=None, outputs=None, **params):
        if outputs is None:
            outputs = [uid(), uid()] if kind in ('sequence', 'fork') else []
        node = GraphNode(kind=kind, x=pos_x, y=pos_y, region=region, params=params, outputs=outputs)
        self.nodes[node.id] = node
        return node

    def remove(self, node_id):
        removed = {node_id}
        while True:
            children = {n.id for n in self.nodes.values() if n.region in removed}
            if children <= removed:
                break
            removed |= children
        for key in removed:
            self.nodes.pop(key, None)
        self.edges[:] = [e for e in self.edges if e.source not in removed and e.target not in removed]

    def edit_output(self, node_id, action, output_id=None):
        node = self.nodes[node_id]
        if node.kind not in ('sequence', 'fork'):
            raise ValueError('Редактируемые выходы есть только у последовательности и разветвителя')
        if action == 'add':
            node.outputs.append(uid())
            return
        index = node.outputs.index(output_id)
        if action == 'remove':
            if len(node.outputs) <= 2:
                raise ValueError('Нужно минимум два выхода')
            node.outputs.pop(index)
            self.edges[:] = [e for e in self.edges if not (e.source == node.id and e.output == output_id)]
        elif action in ('up', 'down'):
            other = index + (-1 if action == 'up' else 1)
            if not 0 <= other < len(node.outputs):
                return
            node.outputs[index], node.outputs[other] = node.outputs[other], node.outputs[index]
        else:
            raise ValueError('Неизвестная операция выхода')

@dataclass
class Project:
    name: str = 'Новый проект'
    width: int = 800
    height: int = 600
    nodes: dict[str, SceneNode] = field(default_factory=dict)
    graphs: dict[str, Graph] = field(default_factory=dict)
    variables: dict[str, Variable] = field(default_factory=dict)
    format_version: int = FORMAT_VERSION

    def clone(self):
        return copy.deepcopy(self)

    def to_dict(self):
        return asdict(self)

    def world_matrix(self, node_id):
        chain = []
        while node_id is not None:
            node = self.nodes[node_id]
            chain.append(node.transform.matrix()); node_id = node.parent
        result = (1, 0, 0, 1, 0, 0)
        for local in reversed(chain):
            result = multiply(result, local)
        return result

    def remove_scene(self, node_id):
        removed = {node_id}
        while True:
            children = {n.id for n in self.nodes.values() if n.parent in removed}
            if children <= removed:
                break
            removed |= children
        for key in removed:
            self.nodes.pop(key)
        # Object constants/variables are deliberately NOT silently remapped.
        # Validation reports dangling references; undo restores original IDs.

    @classmethod
    def from_dict(cls, data):
        try:
            if not isinstance(data, dict) or type(data.get('format_version')) is not int or data.get('format_version') != FORMAT_VERSION:
                raise ValueError('Неподдерживаемая версия формата проекта')
            p = cls(name=data['name'], width=data['width'], height=data['height'])
            for key, raw in data['nodes'].items():
                raw = dict(raw)
                raw['transform'] = Transform(**raw['transform'])
                p.nodes[key] = SceneNode(**raw)
            for key, raw in data['graphs'].items():
                raw = dict(raw)
                raw['nodes'] = {k: GraphNode(**n) for k, n in raw['nodes'].items()}
                raw['edges'] = [Edge(**e) for e in raw['edges']]
                raw['parameters'] = [Parameter(**v) for v in raw['parameters']]
                raw['results'] = [Parameter(**v) for v in raw['results']]
                p.graphs[key] = Graph(**raw)
            p.variables = {key: Variable(**raw) for key, raw in data['variables'].items()}
            p.check_structure()
            return p
        except (KeyError, TypeError, AttributeError, RecursionError) as exc:
            raise ValueError(f'Повреждённая структура проекта: {exc}') from exc

    def check_structure(self):
        """Storage safety, distinct from graph diagnostics (unfinished graphs may be saved)."""
        if not isinstance(self.name, str) or not all(isinstance(v, int) and not isinstance(v, bool)
                                                  and 1 <= v <= 16384 for v in (self.width, self.height)):
            raise ValueError('Размер экрана должен быть целым числом от 1 до 16384')
        all_ids = set()
        def identity(key, item):
            if not isinstance(key, str) or not key or key != item.id or key in all_ids:
                raise ValueError('Повторяющийся или неверный ID')
            all_ids.add(key)
        for key, node in self.nodes.items():
            identity(key, node)
            if node.kind not in ('transform', 'sprite', 'static_body', 'controlled_body', 'rect_shape', 'circle_shape', 'polygon_shape') or not isinstance(node.name, str):
                raise ValueError('Неизвестный тип объекта сцены')
            if node.kind.endswith('_shape'):
                from .physics import shape_points, BODIES
                try:
                    shape_points(node)
                except ValueError as exc:
                    raise ValueError(f'Форма {node.name} [{key}]: {exc}') from exc
                if node.parent not in self.nodes or self.nodes[node.parent].kind not in BODIES:
                    raise ValueError('Форма должна быть непосредственным ребёнком физического тела')
            if not all(number(v) for v in asdict(node.transform).values()):
                raise ValueError('Преобразование содержит нечисловые значения')
            if node.transform.sx == 0 or node.transform.sy == 0:
                raise ValueError('Нулевой масштаб не поддерживается')
            if any(ref is not None and not isinstance(ref, str) for ref in (node.parent, node.graph, node.image)):
                raise ValueError('Ссылки объекта должны быть ID/путями либо пустыми')
            if node.parent is not None and node.parent not in self.nodes:
                raise ValueError('Не найден родитель объекта')
            if node.image is not None:
                from pathlib import PurePosixPath
                path = PurePosixPath(node.image)
                if not isinstance(node.image, str) or path.is_absolute() or '..' in path.parts or '\\' in node.image or ':' in node.image:
                    raise ValueError('Ресурс должен иметь безопасный относительный путь')
            seen = {key}
            parent = node.parent
            while parent:
                if parent in seen:
                    raise ValueError('Цикл в дереве сцены')
                seen.add(parent)
                if len(seen) > 128:
                    raise ValueError('Глубина дерева сцены больше 128: лимит прототипа')
                parent = self.nodes[parent].parent
        for key, graph in self.graphs.items():
            identity(key, graph)
            if graph.kind not in ('behavior', 'function') or not isinstance(graph.name, str):
                raise ValueError('Неизвестный тип графа')
            for nkey, node in graph.nodes.items():
                identity(nkey, node)
                if isinstance(node.params, dict):
                    for ref_key in ('variable', 'function'):
                        ref_value = node.params.get(ref_key)
                        if ref_value is not None and not isinstance(ref_value, str):
                            raise ValueError('Ссылка карточки должна быть строковым ID')
                if not isinstance(node.outputs, list):
                    raise ValueError('Порядок выходов должен быть списком ID')
                for output in node.outputs:
                    if not isinstance(output, str) or not output or output in all_ids:
                        raise ValueError('Повторяющийся или неверный ID выхода')
                    all_ids.add(output)
                if node.region is not None and not isinstance(node.region, str):
                    raise ValueError('ID области цикла должен быть строкой')
                if not isinstance(node.expanded, bool):
                    raise ValueError('Неверное состояние раскрытия карточки')
                if not isinstance(node.kind, str) or not isinstance(node.params, dict) or not number(node.x) or not number(node.y):
                    raise ValueError('Повреждённая карточка графа')
            for edge in graph.edges:
                identity(edge.id, edge)
                if not all(isinstance(v, str) for v in (edge.source, edge.output, edge.target, edge.input)):
                    raise ValueError('Повреждённая связь')
            for param in graph.parameters + graph.results:
                identity(param.id, param)
                if param.type not in TYPES or not isinstance(param.name, str):
                    raise ValueError('Неизвестный тип параметра функции')
        for key, var in self.variables.items():
            identity(key, var)
            if var.scope not in ('run', 'object', 'game') or not valid_value(var.type, var.value):
                raise ValueError('Неверный тип или начальное значение переменной')
            if var.owner is not None and not isinstance(var.owner, str):
                raise ValueError('ID владельца переменной должен быть строкой')
            if var.scope == 'run' and var.owner not in self.graphs:
                raise ValueError('Переменная запуска должна принадлежать графу')
            if not isinstance(var.name, str):
                raise ValueError('Неверное имя переменной')
