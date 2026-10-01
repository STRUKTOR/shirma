"""PreToolUse-хук Claude Code: не пускает Claude в папку private и не даёт править свои защиты.

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
WRITE_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
# команды оболочки: Bash (macOS, Linux, Git Bash) и PowerShell (Windows)
SHELL_TOOLS = ('Bash', 'PowerShell')
COMMANDS = ('obfuscate', 'check', 'restore', 'open')
DENIED = 'Доступ к папке private запрещён: там оригиналы с персональными данными.'
DENIED_UP = 'Выход за пределы папки проекта запрещён: рядом лежит private с оригиналами.'
DENIED_CFG = ('Правка настроек, скилла и CLAUDE.md запрещена: они защищают оригиналы. '
              'Если правило мешает, скажи об этом пользователю.')
# в bash-команде: .claude как часть пути или CLAUDE.md
RE_CFG_IN_CMD = re.compile(r'(^|[\s\'"=/:])\.claude([/\s\'"]|$)|claude\.md', re.I)


def nfc(s):
    return unicodedata.normalize('NFC', s)


def norm_path(p):
    return nfc(os.path.normcase(os.path.abspath(p))).replace('\\', '/')


def allowed_commands(py, root):
    return {f'"{py}" -m shirma {c} --root "{root}"' for c in COMMANDS}


def _posix(p):
    return (p or '').replace('\\', '/')


def is_allowed_command(cmd, py, root):
    """Одна из команд shirma ровно в разрешённом виде; в PowerShell — с оператором вызова «& »."""
    cmd = _posix(' '.join((cmd or '').split()))
    if cmd.startswith('& '):
        cmd = cmd[2:]
    return cmd in allowed_commands(_posix(py), _posix(root))


def check(data, private, root, py):
    """None — можно, иначе текст причины."""
    tool = data.get('tool_name', '')
    inp = data.get('tool_input') or {}
    cwd = data.get('cwd') or os.getcwd()
    private_n = norm_path(private)
    root_n = norm_path(root)
    name = re.escape(nfc(os.path.basename(private)))

    if tool in SHELL_TOOLS and is_allowed_command(inp.get('command'), py, root):
        return None

    blob = nfc(json.dumps(inp, ensure_ascii=False)).replace('\\\\', '/').replace('\\', '/')
    blob = blob.replace('~/', os.path.expanduser('~').replace('\\', '/') + '/')
    if private_n.casefold() in blob.casefold():
        return DENIED
    if re.search(rf'\.\./{name}(/|\b)', blob, re.I):
        return DENIED

    claude_n = norm_path(os.path.join(root, 'claude'))
    for k in PATH_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v:
            p = norm_path(os.path.join(cwd, os.path.expanduser(v)))
            if p == private_n or p.startswith(private_n + '/'):
                return DENIED
            pc, cn = p.casefold(), claude_n.casefold()
            if tool in WRITE_TOOLS and (pc.startswith(cn + '/.claude/') or pc == cn + '/.claude'
                                        or pc == cn + '/claude.md'):
                return DENIED_CFG
            if tool in SEARCH_TOOLS and (private_n.startswith(p + '/') or p == root_n):
                return DENIED_UP
    if tool in SEARCH_TOOLS and not inp.get('path'):
        pat = inp.get('pattern') or ''
        if pat.startswith(('..', '/', '~')):
            return DENIED_UP

    if tool in SHELL_TOOLS:
        cmd = inp.get('command') or ''
        if RE_CFG_IN_CMD.search(nfc(cmd)):
            return DENIED_CFG
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
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    try:
        # Claude Code передаёт JSON в UTF-8; кодировка консоли Windows (cp1251) тут ни при чём
        data = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    except Exception:
        return 0
    reason = check(data, a.private, a.root, a.py)
    if reason:
        sys.stderr.write(reason + ' Для обезличивания и восстановления используйте команды из CLAUDE.md.\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
