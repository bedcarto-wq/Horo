"""Build editable checking projects, not special cases in the interpreter."""
import struct
import zlib
from pathlib import Path
from .model import Project, SceneNode, Graph, Variable, Parameter, Edge
from .storage import save_project


def link(g, a, out, b, inp):
    g.edges.append(Edge(a.id, out, b.id, inp))


def sprite(project):
    obj = SceneNode(name='Тестовое изображение', kind='sprite', image='assets/test.xpm')
    obj.transform.x = 80; obj.transform.y = 100
    project.nodes[obj.id] = obj
    return obj


def basic():
    p = Project(name='Клавиша → перемещение'); obj = sprite(p)
    g = Graph(name='Перемещение по пробелу'); p.graphs[g.id] = g; obj.graph = g.id
    key = g.add('key', 0, 0, key='Space')
    vector = g.add('vector', 0, 240, x=30, y=0)
    move = g.add('move', 420, 0)
    link(g, key, 'next', move, 'in'); link(g, key, 'object', move, 'object')
    link(g, vector, 'value', move, 'delta')
    return p


def counter():
    p = Project(name='A — Счётчик и условие'); obj = sprite(p)
    g = Graph(name='После третьего нажатия'); p.graphs[g.id] = g; obj.graph = g.id
    var = Variable(name='Нажатия', scope='object', value=0); p.variables[var.id] = var
    key = g.add('key', 0, 0, key='Space')
    read = g.add('read', 0, 240, variable=var.id)
    one = g.add('number', 0, 480, value=1)
    add = g.add('add', 400, 280)
    write = g.add('write', 400, 0, variable=var.id)
    greater = g.add('greater', 800, 280)
    two = g.add('number', 800, 520, value=2)
    cond = g.add('if', 800, 0)
    move = g.add('move', 1200, 0)
    vector = g.add('vector', 1200, 280, x=20, y=0)
    for a, out, b, inp in [(key, 'next', write, 'in'), (read, 'value', add, 'a'),
                           (one, 'value', add, 'b'), (add, 'value', write, 'value'),
                           (write, 'next', cond, 'in'), (read, 'value', greater, 'a'),
                           (two, 'value', greater, 'b'), (greater, 'value', cond, 'condition'),
                           (cond, 'yes', move, 'in'), (key, 'object', move, 'object'),
                           (vector, 'value', move, 'delta')]:
        link(g, a, out, b, inp)
    return p


def function_loop(n=3, control=None, return_in_function=False):
    p = Project(name='Б — Функция и цикл'); obj = sprite(p)
    fn = Graph(name='Получить смещение', kind='function'); p.graphs[fn.id] = fn
    amount = Parameter(name='Число', type='number'); direction = Parameter(name='Вектор', type='vector')
    delta = Parameter(name='Смещение', type='vector'); repeats = Parameter(name='Повторы', type='number')
    fn.parameters = [amount, direction]; fn.results = [delta, repeats]
    entry = fn.add('entry', 0, 0); ret = fn.add('return', 420, 0)
    if return_in_function:
        loop = fn.add('repeat', 420, 0)
        ret.x = 20; ret.y = 20; ret.region = loop.id
        link(fn, entry, 'next', loop, 'in'); link(fn, entry, amount.id, loop, 'n')
        link(fn, loop, 'body', ret, 'in')
    else:
        link(fn, entry, 'next', ret, 'in')
    link(fn, entry, direction.id, ret, delta.id)
    link(fn, entry, amount.id, ret, repeats.id)
    g = Graph(name='Вызов и повторение'); p.graphs[g.id] = g; obj.graph = g.id
    key = g.add('key', 0, 0, key='Space'); value = g.add('number', 0, 250, value=n)
    vector = g.add('vector', 0, 470, x=15, y=5)
    call = g.add('call', 420, 0, function=fn.id)
    loop = g.add('repeat', 840, 0)
    move = g.add('move', 20, 20, region=loop.id)
    for a, out, b, inp in [(key, 'next', call, 'in'), (value, 'value', call, 'arg:'+amount.id),
                           (vector, 'value', call, 'arg:'+direction.id), (call, 'next', loop, 'in'),
                           (call, 'result:'+repeats.id, loop, 'n'), (loop, 'body', move, 'in'),
                           (key, 'object', move, 'object'), (call, 'result:'+delta.id, move, 'delta')]:
        link(g, a, out, b, inp)
    if control:
        ctrl = g.add(control, 420, 20, region=loop.id); link(g, move, 'next', ctrl, 'in')
    return p


def test_png():
    """Original 48×48 RGBA test image; no external images or imaging dependency."""
    def chunk(tag, data):
        return struct.pack('!I', len(data))+tag+data+struct.pack('!I', zlib.crc32(tag+data)&0xffffffff)
    rows = b''.join(b'\x00'+b''.join(bytes((85, 160, 240, 255)) if 4 <= x < 44 and 4 <= y < 44
                                   else bytes((25, 45, 70, 255)) for x in range(48)) for y in range(48))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('!IIBBBBB', 48, 48, 8, 6, 0, 0, 0))+chunk(b'IDAT', zlib.compress(rows))+chunk(b'IEND', b'')


def test_xpm():
    """Text image supported by Qt directly and versionable through text-only Git tools."""
    rows = [''.join('b' if 4 <= x < 44 and 4 <= y < 44 else 'a' for x in range(48)) for y in range(48)]
    lines = ['48 48 2 1', 'a c #192D46', 'b c #55A0F0'] + rows
    return '/* XPM */\nstatic const char *horo_test[] = {\n' + ',\n'.join('"'+line+'"' for line in lines) + '\n};\n'


def write_examples(root):
    cases = {'basic': basic(), 'counter': counter(), 'function_loop': function_loop(),
             'loop_zero': function_loop(0), 'loop_negative': function_loop(-1),
             'loop_fractional': function_loop(1.5), 'loop_continue': function_loop(control='continue'),
             'loop_break': function_loop(control='break'),
             'function_return_in_loop': function_loop(return_in_function=True)}
    for name, project in cases.items():
        folder = Path(root)/name; (folder/'assets').mkdir(parents=True, exist_ok=True)
        (folder/'assets/test.xpm').write_text(test_xpm(), encoding='ascii'); save_project(project, folder)
