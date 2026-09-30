"""Раскладка рабочей папки."""
import os
import unicodedata

SAFE = 'Сейф'
CLAUDE = 'Claude'
SKIP_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini', '.gitkeep'}


def nfc(s):
    return unicodedata.normalize('NFC', s)


class Workspace:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.safe = os.path.join(self.root, SAFE)
        self.claude = os.path.join(self.root, CLAUDE)
        self.orig = os.path.join(self.safe, 'Оригиналы')
        self.result = os.path.join(self.safe, 'Результат')
        self.zam = os.path.join(self.safe, 'Замены')
        self.dicts = os.path.join(self.safe, 'Словари')
        self.reports = os.path.join(self.safe, 'Отчёты')
        self.copies = os.path.join(self.claude, 'Копии')
        self.claude_out = os.path.join(self.claude, 'Результат')
        self.db = os.path.join(self.zam, 'zameny.sqlite')
        self.csv = os.path.join(self.zam, 'zameny.csv')

    def dirs(self):
        return [self.orig, self.result, self.zam, self.dicts, self.reports, self.copies, self.claude_out]

    def dict_lines(self, name):
        p = os.path.join(self.dicts, name)
        if not os.path.exists(p):
            return []
        with open(p, encoding='utf-8-sig') as f:
            return [l.strip() for l in f if l.strip() and not l.lstrip().startswith('#')]

    @staticmethod
    def find(start=None):
        """Корень рабочей папки: там, где рядом лежат «Сейф» и «Claude»."""
        cur = os.path.abspath(start or os.getcwd())
        for _ in range(4):
            if os.path.isdir(os.path.join(cur, SAFE)):
                return Workspace(cur)
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
