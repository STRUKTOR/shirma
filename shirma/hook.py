"""PreToolUse-хук Claude Code: не пускает Claude в папку private.

Разрешены только три команды shirma (их вывод — только количества).
Блокировка: код выхода 2, причина — в stderr (её видит Claude).
Только стандартная библиотека: хук вызывается на каждый шаг Claude.

Проверяются пути, а не слово «private»: оно слишком общее (на macOS с него
начинаются системные пути /private/tmp, /private/var).
"""
import argparse
import json
import os
import re
import sys
import unicodedata

PATH_KEYS = ('file_path', 'path', 'notebook_path')
SEARCH_TOOLS = ('Glob', 'Grep', 'LS')
COMMANDS = ('obfuscate', 'check', 'restore')
DENIED = 'Доступ к папке private запрещён: там оригиналы с персональными данными.'
DENIED_UP = 'Выход за пределы папки проекта запрещён: рядом лежит private с оригиналами.'


def nfc(s):
    return unicodedata.normalize('NFC', s)


def norm_path(p):
    return nfc(os.path.normcase(os.path.abspath(p))).replace('\\', '/')


def allowed_commands(py, root):
    return {f'"{py}" -m shirma {c} --root "{root}"' for c in COMMANDS}


def check(data, private, root, py):
    """None — можно, иначе текст причины."""
    tool = data.get('tool_name', '')
    inp = data.get('tool_input') or {}
    cwd = data.get('cwd') or os.getcwd()
    private_n = norm_path(private)
    root_n = norm_path(root)
    name = re.escape(nfc(os.path.basename(private)))

    if tool == 'Bash':
        cmd = ' '.join((inp.get('command') or '').split())
        if cmd in allowed_commands(py, root):
            return None

    blob = nfc(json.dumps(inp, ensure_ascii=False)).replace('\\\\', '/').replace('\\', '/')
    blob = blob.replace('~/', os.path.expanduser('~').replace('\\', '/') + '/')
    if private_n.casefold() in blob.casefold():
        return DENIED
    if re.search(rf'\.\./{name}(/|\b)', blob, re.I):
        return DENIED

    for k in PATH_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v:
            p = norm_path(os.path.join(cwd, os.path.expanduser(v)))
            if p == private_n or p.startswith(private_n + '/'):
                return DENIED
            if tool in SEARCH_TOOLS and (private_n.startswith(p + '/') or p == root_n):
                return DENIED_UP
    if tool in SEARCH_TOOLS and not inp.get('path'):
        pat = inp.get('pattern') or ''
        if pat.startswith(('..', '/', '~')):
            return DENIED_UP

    if tool == 'Bash':
        cmd = inp.get('command') or ''
        if re.search(r'(^|[\s\'"=/:])\.\.([/\\\s\'"]|$)', cmd):
            return DENIED_UP
        low = blob.casefold()
        if root_n.casefold() in low:
            rest = low.split(root_n.casefold(), 1)[1]
            if not rest.startswith('/claude'):
                return DENIED_UP
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--private', required=True)
    ap.add_argument('--root', required=True)
    ap.add_argument('--py', required=True)
    a = ap.parse_args()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    reason = check(data, a.private, a.root, a.py)
    if reason:
        sys.stderr.write(reason + ' Для обезличивания и восстановления используйте команды из CLAUDE.md.\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
