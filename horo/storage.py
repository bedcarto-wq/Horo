"""Atomic local JSON storage and copied assets. Never evaluate project content."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from .model import Project

PROJECT_FILE = 'project.horo.json'


def asset_path(folder, relative):
    root = Path(folder).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Путь ресурса выходит за пределы проекта')
    return target


def save_project(project, folder):
    project.check_structure()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(project.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=folder, suffix='.tmp', delete=False) as f:
            temporary = f.name
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, folder / PROJECT_FILE)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_project(path):
    path = Path(path)
    if path.is_dir():
        path = path / PROJECT_FILE
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('Файл проекта больше 20 МБ: лимит прототипа')
    try:
        with path.open(encoding='utf-8') as f:
            data = json.load(f, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Нечисловая константа JSON')))
        return Project.from_dict(data)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise ValueError(f'Невозможно прочитать JSON проекта: {exc}') from exc


def import_asset(source, folder):
    source = Path(source)
    if source.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.bmp', '.xpm'):
        raise ValueError('Поддерживаются PNG, JPEG, BMP и XPM')
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()[:16]
    relative = 'assets/' + digest + source.suffix.lower()
    target = asset_path(folder, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(source, target)
    return relative
