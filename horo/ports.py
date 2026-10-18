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


# Presentation metadata lives next to the authoritative port definitions. It
# never supplies defaults or changes evaluation/validation semantics.
DESCRIPTIONS = {
 'key':'Запускает отдельное событие при нажатии выбранной клавиши; удержание не повторяет нажатие.',
 'key_release':'Запускает событие при отпускании выбранной клавиши.',
 'start':'Запускается один раз при старте игрового снимка для каждого экземпляра поведения.',
 'frame':'Запускает событие каждого update. Интервал берётся из монотонного времени, не обещает 60 FPS.',
 'contact_begin':'Событие начала контакта пары тел; доставляется обычной очередью Runtime.',
 'contact_end':'Событие окончания контакта пары тел.',
 'number':'Конечное число из поля внутри карточки.', 'text':'Текст из поля внутри карточки.',
 'bool':'Логическое значение из поля внутри карточки.', 'object':'Ссылка на объект сцены; пустая ссылка допустима как значение, но не для действий над телом.',
 'vector':'Собирает Vector2 из X/Y. Подключённый вход заменяет соответствующее поле. Сам вектор не задаёт единицы или систему координат.',
 'move':'Немедленно меняет локальное положение объекта: это телепорт, не физическая скорость и не перенос пассажиров.',
 'body_move':'Задаёт мировую скорость ходьбы только на следующий update; последняя команда побеждает. Накопленная скорость отдельна.',
 'held':'Читает текущее удержание клавиши, не запускает выполнение.',
 'direction':'Собирает направление по удерживаемым клавишам; диагональ сама не нормализуется.',
 'normalize':'Нормализует вектор; нулевой вектор остаётся нулевым.',
 'vector_scale':'Умножает вектор на число; единицы зависят от подключённых значений.',
 'dot':'Скалярное произведение двух векторов.', 'vector_add':'Покомпонентно складывает векторы.', 'vector_sub':'Вычитает B из A.',
 'read':'Читает выбранную переменную. Переменные объекта раздельны для разных экземпляров общего поведения.',
 'write':'Записывает выбранную переменную после прихода выполнения. Для объектной переменной в функции нужна явная ссылка.',
 'add':'Складывает два конечных числа.', 'greater':'Проверяет A > B.',
 'if':'Запускает выход Да или Нет по логическому условию.',
 'entry':'Единственный вход функции; параметры сигнатуры доступны на выходах данных.',
 'return':'Завершает текущий вызов функции и возвращает результаты сигнатуры. Первый исполненный возврат завершает вызов.',
 'call':'Вызывает выбранную функцию. Результаты доступны после её исполнения; рекурсия запрещена.',
 'repeat':'Повторяет вложенное тело N раз. N — целое неотрицательное число. После завершения запускается После цикла.',
 'while':'Проверяет условие перед каждой итерацией вложенного тела. Действуют прежние лимиты шагов/задач.',
 'break':'Завершает ближайший цикл текущего графа. Размещается только в его теле.',
 'continue':'Переходит к следующей итерации ближайшего цикла текущего графа. Размещается только в его теле.',
 'wait':'Ждёт N секунд без блокировки других задач. Подключённый вход заменяет поле; 0 продолжает на следующем update.',
 'sequence':'Запускает нумерованные выходы последовательно; ждёт завершения предыдущей ветки.',
 'fork':'Создаёт независимые ветки текущего запуска; они делят переменные запуска и обслуживаются прежним FIFO.',
 'get_velocity':'Читает накопленную мировую скорость персонажа/динамики, без ходьбы и переноса платформой.',
 'get_gravity':'Читает индивидуальную мировую гравитацию персонажа/динамики.',
 'get_angular':'Читает угловую скорость динамического тела, градусы/с, по часовой стрелке при Y вниз.',
 'grounded':'Читает завершённую опору персонажа: статика/платформа, нормаль не дальше 45° от вверх. Динамика не даёт опору.',
 'get_up':'Читает направление вверх персонажа: нормализованное −g, при g=0 — явное авторское направление.',
 'get_mass':'Читает общую массу динамического тела.', 'get_inertia':'Читает общую инерцию динамического тела относительно центра масс.',
 'set_velocity':'Задаёт накопленную мировую скорость персонажа/динамики, не стирая отдельную команду ходьбы.',
 'set_gravity':'Задаёт индивидуальное мировое ускорение персонажа/динамики.',
 'set_angular':'Задаёт угловую скорость динамики, градусы/с, по часовой стрелке.',
 'impulse':'Прикладывает мировой импульс к динамике. Необязательная мировая точка — центр масс, если вход не подключён.',
 'jump':'При наличии опоры задаёт скорость персонажа вдоль вверх, сохраняет касательную и поглощает опору. В воздухе — обычный отказ.',
 'platform_move':'Задаёт мировую скорость поступательной платформы только на update. Переносит опирающихся персонажей фактическим смещением.'}


def port_help(project, graph, node, port):
    from .model import TYPE_LABELS
    kind = 'Выполнение' if port.type == 'exec' else TYPE_LABELS[port.type]
    lines = [f'{port.label} · {kind}', 'Вход' if port.direction == 'in' else 'Выход']
    if port.direction == 'in':
        if port.type == 'exec': lines.append('Сигнал выполнения команды; не значение данных')
        else:
            lines.append('Обязательный' if port.required else 'Необязательный: используется поле/значение по умолчанию')
            connected = any(e.target == node.id and e.input == port.key for e in graph.edges)
            lines.append('Значение приходит по линии' if connected else 'Вход не подключён')
    else: lines.append('Источник сигнала выполнения' if port.type == 'exec' else 'Источник данных')
    if port.type == 'vector':
        if node.kind == 'move' and port.key == 'delta': lines.append('Единицы сцены; локальные координаты родителя; Y вниз')
        elif node.kind in ('get_velocity','set_velocity','body_move','platform_move'): lines.append('Единицы сцены/с; мировые координаты; Y вниз')
        elif node.kind in ('get_gravity','set_gravity'): lines.append('Единицы сцены/с²; мировые координаты; Y вниз')
        elif node.kind == 'impulse': lines.append('Единицы сцены; мировая точка' if port.key == 'point' else 'Масса × единицы сцены/с; мировой импульс')
        elif node.kind == 'get_up': lines.append('Безразмерное единичное направление; мировые координаты')
        else: lines.append('Два числа X/Y; единицы и система координат определяются применением')
    if port.type == 'number':
        if node.kind in ('get_angular','set_angular'): lines.append('Градусы/с; положительное по часовой стрелке при Y вниз')
        elif node.kind == 'jump': lines.append('Единицы сцены/с вдоль направления вверх; значение ≥ 0')
        elif node.kind == 'get_mass': lines.append('Условные единицы массы')
        elif node.kind == 'get_inertia': lines.append('Масса × единицы сцены²; относительно общего центра масс')
        elif node.kind == 'wait' or (node.kind in STARTS and port.key in ('time','delta')): lines.append('Секунды; монотонное игровое время')
        elif node.kind == 'repeat': lines.append('Количество итераций: целое ≥ 0')
        else: lines.append('Число; единицы определяются применением')
    if port.type == 'object': lines.append('Ссылка на ID объекта сцены, не копия объекта')
    lines.append(DESCRIPTIONS[node.kind])
    return '\n'.join(lines)
