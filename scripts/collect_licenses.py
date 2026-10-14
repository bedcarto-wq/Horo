"""Copy installed wheel license notices into the onedir distribution."""
from importlib.metadata import distribution
from pathlib import Path
import shutil

root = Path('dist/Horo/licenses')
for name in ('PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6'):
    dist = distribution(name)
    found = 0
    for entry in dist.files or []:
        parts = [part.lower() for part in entry.parts]
        filename = entry.name.lower()
        if ('licenses' in parts or filename.startswith(('license', 'copying', 'notice'))) and Path(dist.locate_file(entry)).is_file():
            target = root/name/str(entry)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dist.locate_file(entry), target)
            found += 1
    target = root/name/'WHEEL-NOTICE.txt'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'{name} {dist.version}\nLicense: {dist.metadata.get("License")}\n'
                      'PySide6 licensing: https://doc.qt.io/qtforpython-6/licenses.html\n'
                      'Qt licensing: https://doc.qt.io/qt-6/licenses.html\n'
                      'Some wheels omit license texts; bundled GNU license copies are in licenses/GNU/.\n', encoding='utf-8')
for filename in ('LGPL-3.0.txt', 'GPL-3.0.txt', 'GPL-2.0.txt'):
    source = Path('third_party/licenses')/filename
    if not source.exists():
        raise SystemExit(f'Не найден обязательный текст {filename}')
    target = root/'GNU'/filename; target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
print('PySide6/Qt/Shiboken license notices copied')
