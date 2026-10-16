"""One port catalog used by runtime, validation and UI. Port IDs are stable keys."""
from dataclasses import dataclass
from .model import Project, Graph, GraphNode

LABELS = {'key': 'При нажатии клавиши', 'number': 'Число', 'text': 'Текст',
          'bool': 'Логическое значение', 'object': 'Объект', 'vector': 'Вектор 2D',
          'move': 'Переместить объект', 'read': 'Прочитать переменную',
          'write': 'Записать переменную', 'add': 'Сложить числа', 'greater': 'Больше',
          'if': 'Если', 'entry': 'Вход функции', 'return': 'Вернуть результат',
          'call': 'Вызвать функцию', 'repeat': 'Повторить N раз',
          'break': 'Прервать цикл', 'continue': 'Продолжить',
          'start': 'При старте', 'frame': 'Каждый кадр', 'key_release': 'При отпускании клавиши',
          'wait': 'Ждать N секунд', 'sequence': 'Последовательно', 'fork': 'Разветвитель',
          'while': 'Пока'}
CATEGORIES = {'События': ['key', 'key_release', 'start', 'frame'], 'Значения': ['number', 'text', 'bool', 'object', 'vector'],
              'Действия': ['move'], 'Переменные': ['read', 'write'],
              'Вычисления': ['add', 'greater'], 'Управление': ['if', 'repeat', 'while', 'wait', 'sequence', 'fork', 'break', 'continue'],
              'Функции': ['entry', 'call', 'return']}
STARTS = {'key', 'key_release', 'start', 'frame'}
LABELS.update({'held': 'Клавиша удерживается', 'direction': 'Направление по клавишам',
    'normalize': 'Нормализовать вектор', 'vector_scale': 'Умножить вектор на число',
    'body_move': 'Двигать управляемое тело', 'contact_begin': 'Начало контакта', 'contact_end': 'Конец контакта'})
CATEGORIES['Ввод'] = ['held', 'direction']
CATEGORIES['Вычисления'] += ['normalize', 'vector_scale']
CATEGORIES['Действия'] += ['body_move']
CATEGORIES['События'] += ['contact_begin', 'contact_end']
STARTS |= {'contact_begin', 'contact_end'}
LOOPS = {'repeat', 'while'}
PURE = {'number', 'text', 'bool', 'object', 'vector', 'read', 'add', 'greater', 'held', 'direction', 'normalize', 'vector_scale'}

PHYSICS_READ = {'get_velocity': ('Получить скорость','vector'),
    'get_gravity': ('Получить гравитацию','vector'), 'get_angular': ('Получить угловую скорость','number'),
    'grounded': ('Есть опора','bool'), 'get_up': ('Направление вверх','vector'),
    'get_mass': ('Получить массу','number'), 'get_inertia': ('Получить инерцию','number')}
PHYSICS_ACTION = {'set_velocity': ('Задать скорость','vector'),
    'set_gravity': ('Задать гравитацию','vector'), 'set_angular': ('Задать угловую скорость','number'),
    'impulse': ('Приложить импульс','vector'), 'jump': ('Прыгнуть','number'),
    'platform_move': ('Двигать платформу','vector')}
LABELS.update({k:v[0] for k,v in {**PHYSICS_READ,**PHYSICS_ACTION}.items()})
LABELS.update({'dot': 'Скалярное произведение', 'vector_add': 'Сложить векторы', 'vector_sub': 'Вычесть векторы'})
CATEGORIES['Физика'] = list(PHYSICS_READ)+list(PHYSICS_ACTION)
CATEGORIES['Вычисления'] += ['dot','vector_add','vector_sub']
PURE |= set(PHYSICS_READ)|{'dot','vector_add','vector_sub'}

@dataclass(frozen=True)
class Port:
    key: str
    label: str
    type: str
    direction: str
    required: bool = True


def ports(project: Project, graph: Graph, node: GraphNode):
    result = []
    def p(key, label, kind, direction, required=True):
        result.append(Port(key, label, kind, direction, required))
    if node.kind in PHYSICS_READ or node.kind in PHYSICS_ACTION:
        p('object', 'Тело', 'object', 'in')
        if node.kind in PHYSICS_READ:p('value', PHYSICS_READ[node.kind][0], PHYSICS_READ[node.kind][1], 'out')
        else:
            p('in', 'Выполнение', 'exec', 'in');p('next','Далее','exec','out')
            label = 'Градусов / с' if node.kind=='set_angular' else 'Скорость прыжка' if node.kind=='jump' else 'Значение'
            p('value',label,PHYSICS_ACTION[node.kind][1],'in')
            if node.kind=='impulse':p('point','Мировая точка (иначе центр масс)','vector','in',False)
    elif node.kind in ('dot','vector_add','vector_sub'):
        p('a','A','vector','in');p('b','B','vector','in')
        p('value','Результат','number' if node.kind=='dot' else 'vector','out')
    elif node.kind in ('held', 'direction'):
        p('value', 'Удерживается' if node.kind == 'held' else 'Направление', 'bool' if node.kind == 'held' else 'vector', 'out')
    elif node.kind == 'normalize':
        p('vector', 'Вектор', 'vector', 'in'); p('value', 'Единичный вектор', 'vector', 'out')
    elif node.kind == 'vector_scale':
        p('vector', 'Вектор', 'vector', 'in'); p('factor', 'Множитель', 'number', 'in'); p('value', 'Вектор', 'vector', 'out')
    elif node.kind == 'body_move':
        p('in', 'Выполнение', 'exec', 'in'); p('next', 'Далее', 'exec', 'out')
        p('object', 'Управляемое тело', 'object', 'in'); p('velocity', 'Мировая скорость / с', 'vector', 'in')
    elif node.kind in ('number', 'text', 'bool', 'object'):
        p('value', 'Значение', node.kind, 'out')
    elif node.kind == 'vector':
        p('x', 'X (иначе поле)', 'number', 'in', False)
        p('y', 'Y (иначе поле)', 'number', 'in', False)
        p('value', 'Вектор', 'vector', 'out')
    elif node.kind in STARTS:
        p('next', 'Выполнить', 'exec', 'out')
        p('object', 'Этот объект', 'object', 'out')
        p('time', 'Время сеанса', 'number', 'out')
        if node.kind in ('contact_begin', 'contact_end'):
            p('other', 'Второе тело', 'object', 'out')
        if node.kind in ('key', 'key_release'):
            p('key', 'Клавиша события', 'text', 'out')
        if node.kind == 'frame':
            p('delta', 'Секунд с update', 'number', 'out')
    elif node.kind in ('add', 'greater'):
        p('a', 'A', 'number', 'in'); p('b', 'B', 'number', 'in')
        p('value', 'Сумма' if node.kind == 'add' else 'A > B',
          'number' if node.kind == 'add' else 'bool', 'out')
    elif node.kind in ('read', 'write'):
        var = project.variables.get(node.params.get('variable'))
        if node.kind == 'write':
            p('in', 'Выполнение', 'exec', 'in'); p('next', 'Далее', 'exec', 'out')
        if var:
            if var.scope == 'object':
                p('object', 'Объект' if graph.kind == 'function' else 'Объект (иначе этот)',
                  'object', 'in', graph.kind == 'function')
            p('value', var.name, var.type, 'out' if node.kind == 'read' else 'in')
    elif node.kind == 'move':
        p('in', 'Выполнение', 'exec', 'in'); p('next', 'Далее', 'exec', 'out')
        p('object', 'Объект', 'object', 'in'); p('delta', 'Смещение', 'vector', 'in')
    elif node.kind == 'if':
        p('in', 'Выполнение', 'exec', 'in'); p('condition', 'Условие', 'bool', 'in')
        p('yes', 'Да', 'exec', 'out'); p('no', 'Нет', 'exec', 'out')
    elif node.kind in LOOPS:
        p('in', 'Выполнение', 'exec', 'in')
        if node.kind == 'repeat':
            p('n', 'N', 'number', 'in')
        else:
            p('condition', 'Условие', 'bool', 'in')
        p('body', 'Тело', 'exec', 'out'); p('next', 'После цикла', 'exec', 'out')
    elif node.kind == 'wait':
        p('in', 'Выполнение', 'exec', 'in'); p('n', 'N (иначе поле)', 'number', 'in', False)
        p('next', 'Далее', 'exec', 'out')
    elif node.kind in ('sequence', 'fork'):
        p('in', 'Выполнение', 'exec', 'in')
        for index, key in enumerate(node.outputs, 1):
            p(key, str(index), 'exec', 'out')
    elif node.kind in ('break', 'continue'):
        p('in', 'Выполнение', 'exec', 'in')
    elif node.kind == 'entry':
        p('next', 'Выполнить', 'exec', 'out')
        for v in graph.parameters:
            p(v.id, v.name, v.type, 'out')
    elif node.kind == 'return':
        p('in', 'Выполнение', 'exec', 'in')
        for v in graph.results:
            p(v.id, v.name, v.type, 'in')
    elif node.kind == 'call':
        p('in', 'Выполнение', 'exec', 'in'); p('next', 'Далее', 'exec', 'out')
        fn = project.graphs.get(node.params.get('function'))
        if fn and fn.kind == 'function':
            for v in fn.parameters:
                p('arg:'+v.id, v.name, v.type, 'in')
            for v in fn.results:
                p('result:'+v.id, v.name, v.type, 'out')
    return result


def port_map(project, graph, node):
    return {(p.direction, p.key): p for p in ports(project, graph, node)}
