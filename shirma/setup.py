"""Создание рабочей папки: раскладка, словари, ярлыки, CLAUDE.md, скилл, настройки и хук."""
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
- Не правь этот файл, `.claude/settings.json` и скилл `.claude/skills/shirma` — они защищают оригиналы.

## Команды (их можно запускать; они печатают только количества)

Когда просят обезличить, проверить или вернуть данные, следуй скиллу `shirma`. Коротко:

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

SKILL_MD = """---
name: shirma
description: Обезличивание документов и возврат настоящих данных через Ширму. Используй, когда пользователь просит обезличить (обфусцировать, анонимизировать, «прогнать через Ширму») новые файлы, проверить копии на персональные данные, вернуть (восстановить, раскрыть) настоящие данные в результатах или спрашивает, какие новые файлы появились.
---

# Ширма: обезличить, проверить, вернуть

Оригиналы лежат в папке `private` рядом с проектом — тебе она недоступна и не нужна.
Работать можно только через три команды ниже. Запускай их **ровно в том виде, как написано**,
одной строкой, без изменений и без дополнений (`&&`, `|`, `cd` и т.п.) — любая другая форма
заблокирована. Команды печатают только количества, настоящих значений в выводе нет.

## «Обезличь» — новые файлы из private/input → `input/`

1. Обезличить:

       {cmd_obfuscate}

2. Сразу проверить копии — **всегда**, даже если пользователь не просил:

       {cmd_check}

3. Сообщить итог коротко: сколько файлов и замен, что проверка показала.
   - Проверка чистая (код 0) — перечисли новые файлы в `input/` и предложи начать работу.
   - Проверка что-то нашла (код 1) — **не открывай копии**. Скажи пользователю, что нужно
     посмотреть отчёт в `private/system/reports` (он откроет его сам), дописать пропущенное
     в `private/system/dictionaries/companies.txt` или `people.txt`, ложное — в `stoplist.txt`,
     и попросить тебя обезличить заново.
   - Обезличивание с ошибками (код 2) — назови причины из вывода (файл открыт в Word/Excel,
     формат не поддерживается, файл повреждён) и что с этим сделать.

## «Верни данные» — результаты из `output/` → private/output

1. Убедись, что результаты лежат в `output/` в docx, xlsx, pptx, md, txt, csv или другом
   текстовом формате. PDF вернуть нельзя — предложи пересохранить в docx или md.
2. Вернуть:

       {cmd_restore}

3. Сообщить итог: сколько файлов восстановлено; готовые файлы — в `private/output`,
   пользователь откроет их сам (тебе они не видны). Если вывод говорит «возможно,
   не восстановлено» — посоветуй посмотреть отчёт в `private/system/reports`.

## Чего не делать

- Не пытайся прочитать `private`, отчёты, таблицу соответствий или словари — даже чтобы помочь.
- Не запускай ярлыки `1-Обезличить` / `2-Проверить` / `3-Вернуть`: они для двойного щелчка
  человеком (ждут нажатия клавиши и открывают браузер).
- Не правь этот скилл, `CLAUDE.md` и `.claude/settings.json` — они защищают оригиналы.
  Если правило мешает, скажи пользователю.
- Не угадывай настоящие имена и не меняй написание фейковых имён в результатах
  (склонять можно).
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
    fmt = {f'cmd_{c}': v for c, v in cmds.items()}
    skill_dir = os.path.join(ws.claude, '.claude', 'skills', 'shirma')
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, 'SKILL.md'), 'w', encoding='utf-8') as f:
        f.write(SKILL_MD.format(**fmt))

    deny = []
    for tool in ('Read', 'Edit', 'Write'):
        deny += [f'{tool}(../{os.path.basename(ws.private)}/**)', f'{tool}({_deny_abs(ws.private)}/**)']
    # свои защиты Claude не правит: настройки, скилл, CLAUDE.md
    claude_abs = _deny_abs(ws.claude)
    for tool in ('Edit', 'Write'):
        deny += [f'{tool}(./.claude/**)', f'{tool}({claude_abs}/.claude/**)',
                 f'{tool}(./CLAUDE.md)', f'{tool}({claude_abs}/CLAUDE.md)']
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
