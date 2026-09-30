"""Создание рабочей папки: раскладка, словари, ярлыки, CLAUDE.md, настройки и хук."""
import json
import os
import pathlib
import stat
import sys

from .hook import allowed_commands
from .workspace import DICT_COMPANIES, DICT_PEOPLE, DICT_STOPLIST

DICT_HEADERS = {
    DICT_COMPANIES: '# Известные клиенты и контрагенты — по одному в строке.\n'
                    '# Можно с формой и кавычками: ТОО «Ромашка», или просто: Ромашка\n',
    DICT_PEOPLE: '# Известные люди — по одному в строке: Иванов Иван Иванович\n',
    DICT_STOPLIST: '# Что никогда не заменять — по одному в строке (точное совпадение).\n'
                   '# Например, публичные лица или названия госорганов, которые ошибочно заменяются.\n',
}

CLAUDE_MD = """# Работа с обезличенными документами

Документы в этой папке обезличены: имена, организации, ИИН/БИН, счета, телефоны, почта заменены
на правдоподобные фейки. Работай с ними как с обычными данными, не пытайся угадать настоящие значения.

## Правила

- Входные файлы — в `input/`. Свои результаты сохраняй в `output/`.
- Никогда не обращайся к папке `private` и вообще к чему-либо выше этой папки (`..`) — там оригиналы.
- Результаты сохраняй в docx, xlsx, pptx, md, txt, csv или другом текстовом формате — не в PDF:
  PDF нельзя автоматически вернуть к настоящим данным.
- Не переименовывай людей и организации в результатах и не меняй написание их имён (можно склонять).
  Не придумывай новых людей, телефонов и реквизитов.

## Команды (их можно запускать; они печатают только количества)

Обезличить новые файлы из private/input в `input/`:

    {cmd_obfuscate}

Проверить копии на остатки персональных данных (после каждого обезличивания):

    {cmd_check}

Вернуть настоящие данные в результаты из `output/` (готовые файлы появятся в private/output,
тебе они не видны):

    {cmd_restore}

Если проверка что-то нашла — не работай с этими копиями, сообщи пользователю: ему нужно посмотреть
отчёт в private/system/reports и дополнить словари.
"""

README = """Ширма — рабочая папка.

1-Обезличить, 2-Проверить, 3-Вернуть  — ярлыки, запускаются двойным щелчком

private/                  сюда Claude не заглядывает
  input/                  кладите сюда свои файлы (docx, xlsx, pptx, txt, md, csv)
  output/                 готовые файлы с настоящими данными после «3-Вернуть»
  system/                 служебное:
    mapping.sqlite          таблица соответствий
    mapping.csv             её копия для просмотра в Excel
    dictionaries/           известные компании и люди (companies.txt, people.txt), стоп-лист (stoplist.txt)
    reports/                отчёты: что на что заменено, что подозрительно

claude/                   папка проекта Claude Code
  input/                  обезличенные копии — с ними работает Claude
  output/                 сюда Claude кладёт свои результаты

Порядок работы:
1. Положить файлы в private/input и запустить «1-Обезличить».
2. Запустить «2-Проверить». Если что-то найдено — открыть отчёт, дополнить словари, повторить.
3. Открыть Claude Code в папке claude и работать с файлами из claude/input.
4. Когда Claude положит результаты в claude/output — запустить «3-Вернуть».
5. Забрать готовые файлы из private/output.

Можно просто попросить Claude: «обезличь новые файлы», «верни данные в результаты».
"""

LAUNCHERS = {'obfuscate': '1-Обезличить', 'check': '2-Проверить', 'restore': '3-Вернуть'}


def _python():
    """Python окружения без номера версии в имени (переживёт обновление Python в venv)."""
    cand = os.path.join(sys.prefix, 'Scripts', 'python.exe') if os.name == 'nt' else \
        os.path.join(sys.prefix, 'bin', 'python')
    return cand if os.path.exists(cand) else sys.executable


def _posix(p):
    return pathlib.Path(p).as_posix()


def _deny_abs(p):
    s = _posix(p)
    if len(s) > 1 and s[1] == ':':          # Windows: C:/x → //c/x
        return '//' + s[0].lower() + s[2:]
    return '/' + s                           # POSIX: /Users/x → //Users/x


def init_workspace(ws):
    for d in ws.dirs():
        os.makedirs(d, exist_ok=True)
    for name, header in DICT_HEADERS.items():
        p = os.path.join(ws.dicts, name)
        if not os.path.exists(p):
            with open(p, 'w', encoding='utf-8') as f:
                f.write(header)
    with open(os.path.join(ws.system, 'README.txt'), 'w', encoding='utf-8') as f:
        f.write(README)

    py = _posix(_python())
    root = _posix(ws.root)
    private = _posix(ws.private)
    cmds = {c: f'"{py}" -m shirma {c} --root "{root}"' for c in LAUNCHERS}
    assert set(cmds.values()) == allowed_commands(py, root)

    # ярлыки — в корне рабочей папки, рядом с private и claude
    if os.name == 'nt':
        for c, title in LAUNCHERS.items():
            with open(os.path.join(ws.root, f'{title}.bat'), 'w', encoding='utf-8') as f:
                f.write('@echo off\r\nchcp 65001 >nul\r\nset PYTHONUTF8=1\r\n'
                        f'{cmds[c]} --open\r\necho.\r\npause\r\n')
    else:
        for c, title in LAUNCHERS.items():
            p = os.path.join(ws.root, f'{title}.command')
            with open(p, 'w', encoding='utf-8') as f:
                f.write('#!/bin/bash\n'
                        f'{cmds[c]} --open\n'
                        'echo\nread -n 1 -s -r -p "Нажмите любую клавишу, чтобы закрыть окно"\n')
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Claude: правила, запреты, хук
    with open(os.path.join(ws.claude, 'CLAUDE.md'), 'w', encoding='utf-8') as f:
        f.write(CLAUDE_MD.format(**{f'cmd_{c}': v for c, v in cmds.items()}))
    deny = []
    for tool in ('Read', 'Edit', 'Write'):
        deny += [f'{tool}(../{os.path.basename(ws.private)}/**)', f'{tool}({_deny_abs(ws.private)}/**)']
    hook_cmd = f'"{py}" -m shirma.hook --private "{private}" --root "{root}" --py "{py}"'
    settings = {
        'permissions': {
            'allow': [f'Bash({v})' for v in cmds.values()],
            'deny': deny,
        },
        'hooks': {
            'PreToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': hook_cmd}]}],
        },
    }
    os.makedirs(os.path.join(ws.claude, '.claude'), exist_ok=True)
    with open(os.path.join(ws.claude, '.claude', 'settings.json'), 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
