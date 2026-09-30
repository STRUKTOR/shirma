"""Создание рабочей папки: раскладка, словари, ярлыки, CLAUDE.md, настройки и хук."""
import json
import os
import pathlib
import stat
import sys

from .hook import allowed_commands

DICT_HEADERS = {
    'компании.txt': '# Известные клиенты и контрагенты — по одному в строке.\n'
                    '# Можно с формой и кавычками: ТОО «Ромашка», или просто: Ромашка\n',
    'люди.txt': '# Известные люди — по одному в строке: Иванов Иван Иванович\n',
    'стоп-лист.txt': '# Что никогда не заменять — по одному в строке (точное совпадение).\n'
                     '# Например, публичные лица или названия госорганов, которые ошибочно заменяются.\n',
}

CLAUDE_MD = """# Работа с обезличенными документами

Документы в этой папке обезличены: имена, организации, ИИН/БИН, счета, телефоны, почта заменены
на правдоподобные фейки. Работай с ними как с обычными данными, не пытайся угадать настоящие значения.

## Правила

- Входные файлы — в `Копии/`. Свои результаты сохраняй в `Результат/`.
- Никогда не обращайся к папке `Сейф` и вообще к чему-либо выше этой папки (`..`) — там оригиналы.
- Результаты сохраняй в docx, xlsx, pptx, md, txt, csv или другом текстовом формате — не в PDF:
  PDF нельзя автоматически вернуть к настоящим данным.
- Не переименовывай людей и организации в результатах и не меняй написание их имён (можно склонять).
  Не придумывай новых людей, телефонов и реквизитов.

## Команды (их можно запускать; они печатают только количества)

Обезличить новые файлы из Сейфа в `Копии/`:

    {cmd_obezlichit}

Проверить копии на остатки персональных данных (после каждого обезличивания):

    {cmd_proverit}

Вернуть настоящие данные в результаты из `Результат/` (готовые файлы появятся в Сейфе, тебе они не видны):

    {cmd_vernut}

Если проверка что-то нашла — не работай с этими копиями, сообщи пользователю: ему нужно посмотреть
отчёт в Сейфе и дополнить словари.
"""

SAFE_README = """Сейф — сюда Claude не заглядывает.

Оригиналы/   — кладите сюда свои файлы (docx, xlsx, pptx, txt, md, csv)
Результат/   — готовые файлы с настоящими данными после «Вернуть»
Замены/      — таблица соответствий (zameny.csv можно открыть в Excel для просмотра)
Словари/     — известные компании и люди, стоп-лист
Отчёты/      — что на что заменено, что подозрительно

Порядок работы:
1. Положить файлы в Оригиналы и запустить «Обезличить».
2. Запустить «Проверить». Если что-то найдено — открыть отчёт, дополнить Словари, повторить.
3. Открыть Claude Code в папке Claude и работать с файлами из Копии.
4. Когда Claude положит результаты в Claude/Результат — запустить «Вернуть».
5. Забрать готовые файлы из Сейф/Результат.

Можно просто попросить Claude: «обезличь новые файлы», «верни данные в результаты».
"""

LAUNCHERS = {'obezlichit': 'Обезличить', 'proverit': 'Проверить', 'vernut': 'Вернуть'}


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
    with open(os.path.join(ws.safe, 'README.txt'), 'w', encoding='utf-8') as f:
        f.write(SAFE_README)

    py = _posix(_python())
    root = _posix(ws.root)
    safe = _posix(ws.safe)
    cmds = {c: f'"{py}" -m shirma {c} --root "{root}"' for c in LAUNCHERS}
    assert set(cmds.values()) == allowed_commands(py, root)

    # ярлыки
    if os.name == 'nt':
        for c, title in LAUNCHERS.items():
            with open(os.path.join(ws.safe, f'{title}.bat'), 'w', encoding='utf-8') as f:
                f.write('@echo off\r\nchcp 65001 >nul\r\nset PYTHONUTF8=1\r\n'
                        f'{cmds[c]} --open\r\necho.\r\npause\r\n')
    else:
        for c, title in LAUNCHERS.items():
            p = os.path.join(ws.safe, f'{title}.command')
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
        deny += [f'{tool}(../{os.path.basename(ws.safe)}/**)', f'{tool}({_deny_abs(ws.safe)}/**)']
    hook_cmd = f'"{py}" -m shirma.hook --safe "{safe}" --root "{root}" --py "{py}"'
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
