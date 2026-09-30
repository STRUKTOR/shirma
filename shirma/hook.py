"""PreToolUse-хук Claude Code: не пускает Claude в Сейф.

Разрешены только три команды shirma (их вывод — только количества).
Блокировка: код выхода 2, причина — в stderr (её видит Claude).
Только стандартная библиотека: хук вызывается на каждый шаг Claude.
"""
import argparse
import json
import os
import re
import sys
import unicodedata

PATH_KEYS = ('file_path', 'path', 'notebook_path')
SEARCH_TOOLS = ('Glob', 'Grep', 'LS')


def nfc(s):
    return unicodedata.normalize('NFC', s)


def norm_path(p):
    return nfc(os.path.normcase(os.path.abspath(p))).replace('\\', '/')


def allowed_commands(py, root):
    return {f'"{py}" -m shirma {c} --root "{root}"' for c in ('obezlichit', 'proverit', 'vernut')}


def check(data, safe, root, py):
    """None — можно, иначе текст причины."""
    tool = data.get('tool_name', '')
    inp = data.get('tool_input') or {}
    cwd = data.get('cwd') or os.getcwd()
    safe_n = norm_path(safe)
    root_n = norm_path(root)
    safe_name = nfc(os.path.basename(safe)).casefold()

    if tool == 'Bash':
        cmd = ' '.join((inp.get('command') or '').split())
        if cmd in allowed_commands(py, root):
            return None
    blob = nfc(json.dumps(inp, ensure_ascii=False)).replace('\\\\', '/')
    if safe_name in blob.casefold() or safe_n.casefold() in blob.casefold():
        return 'Доступ к Сейфу запрещён: там оригиналы с персональными данными.'

    for k in PATH_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v:
            p = norm_path(os.path.join(cwd, os.path.expanduser(v)))
            if p == safe_n or p.startswith(safe_n + '/'):
                return 'Доступ к Сейфу запрещён: там оригиналы с персональными данными.'
            if tool in SEARCH_TOOLS and (safe_n.startswith(p + '/') or p == root_n):
                return 'Поиск выше папки проекта запрещён: так видны файлы Сейфа.'
    if tool in SEARCH_TOOLS and not inp.get('path'):
        pat = inp.get('pattern') or ''
        if pat.startswith(('..', '/', '~')):
            return 'Поиск выше папки проекта запрещён: так видны файлы Сейфа.'

    if tool == 'Bash':
        cmd = inp.get('command') or ''
        if re.search(r'(^|[\s\'"=/:])\.\.([/\\\s\'"]|$)', cmd):
            return 'Выход за пределы папки проекта (..) запрещён: рядом лежит Сейф с оригиналами.'
        if root_n.casefold() in nfc(cmd).replace('\\', '/').casefold():
            rest = nfc(cmd).replace('\\', '/').casefold().split(root_n.casefold(), 1)[1]
            if not rest.startswith('/claude'):
                return 'Доступ к рабочей папке вне проекта запрещён: рядом лежит Сейф с оригиналами.'
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--safe', required=True)
    ap.add_argument('--root', required=True)
    ap.add_argument('--py', required=True)
    a = ap.parse_args()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    reason = check(data, a.safe, a.root, a.py)
    if reason:
        sys.stderr.write(reason + ' Для обезличивания и восстановления используйте команды из CLAUDE.md.\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
