"""Раскладка рабочей папки.

<рабочая папка>/
  1-Обезличить / 2-Вернуть   ярлыки
  private/                 Claude сюда не заглядывает
    input/                 оригиналы
    output/                восстановленные результаты
    system/                таблица соответствий, словари, отчёты
  claude/                  папка проекта Claude Code
    input/                 обезличенные копии
    output/                результаты Claude
"""
import os
import unicodedata

PRIVATE = 'private'
CLAUDE = 'claude'
SKIP_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini', '.gitkeep'}

DICT_COMPANIES = 'companies.txt'
DICT_PEOPLE = 'people.txt'
DICT_STOPLIST = 'stoplist.txt'


def nfc(s):
    return unicodedata.normalize('NFC', s)


class Workspace:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.private = os.path.join(self.root, PRIVATE)
        self.claude = os.path.join(self.root, CLAUDE)
        self.private_in = os.path.join(self.private, 'input')
        self.private_out = os.path.join(self.private, 'output')
        self.system = os.path.join(self.private, 'system')
        self.dicts = os.path.join(self.system, 'dictionaries')
        self.reports = os.path.join(self.system, 'reports')
        self.claude_in = os.path.join(self.claude, 'input')
        self.claude_out = os.path.join(self.claude, 'output')
        self.db = os.path.join(self.system, 'mapping.sqlite')
        self.csv = os.path.join(self.system, 'mapping.csv')

    def dirs(self):
        return [self.private_in, self.private_out, self.system, self.dicts, self.reports,
                self.claude_in, self.claude_out]

    def is_workspace(self):
        return os.path.isdir(self.system) and os.path.isdir(self.claude)

    def dict_lines(self, name):
        p = os.path.join(self.dicts, name)
        if not os.path.exists(p):
            return []
        with open(p, encoding='utf-8-sig') as f:
            return [l.strip() for l in f if l.strip() and not l.lstrip().startswith('#')]

    @staticmethod
    def find(start=None):
        """Корень рабочей папки: там, где рядом лежат private/system и claude."""
        cur = os.path.abspath(start or os.getcwd())
        for _ in range(4):
            ws = Workspace(cur)
            if ws.is_workspace():
                return ws
            cur = os.path.dirname(cur)
        return None


def walk_files(top):
    """Относительные пути всех обычных файлов (без служебных)."""
    out = []
    if not os.path.isdir(top):
        return out
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
        for fn in sorted(filenames):
            if fn in SKIP_NAMES or fn.startswith(('~$', '.~lock', '.')) or fn.endswith('.tmp'):
                continue
            out.append(nfc(os.path.relpath(os.path.join(dirpath, fn), top)))
    return out
