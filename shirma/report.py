"""HTML-отчёт. Лежит в Сейфе: содержит настоящие данные."""
import datetime as dt
import html
import os

from .registry import TYPE_NAMES

TYPE_NAMES_X = dict(TYPE_NAMES, form='Имя / организация', exact='Ячейка целиком')

CSS = """
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#e5e5ea; --warn:#b25000; --bad:#c9302c;
        --ok:#1f7a3a; --chip:#f2f2f7; }
@media (prefers-color-scheme: dark) { :root { --bg:#1c1c1e; --fg:#f2f2f7; --muted:#a1a1a6;
        --line:#38383a; --warn:#ffa94d; --bad:#ff6b6b; --ok:#69db7c; --chip:#2c2c2e; } }
body { background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system, Segoe UI, Roboto, sans-serif;
       margin:0 auto; max-width:1100px; padding:24px 16px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 8px; }
.muted { color:var(--muted); } .warn { color:var(--warn); } .bad { color:var(--bad); } .ok { color:var(--ok); }
table { border-collapse:collapse; width:100%; margin:6px 0 12px; font-size:14px; }
th, td { text-align:left; padding:5px 8px; border-bottom:1px solid var(--line); vertical-align:top;
         overflow-wrap:anywhere; }
th { color:var(--muted); font-weight:500; }
.chip { display:inline-block; background:var(--chip); border-radius:6px; padding:1px 8px; margin:2px 4px 2px 0; }
details { margin:6px 0; } summary { cursor:pointer; }
"""


def _e(s):
    return html.escape(str(s))


class Report:
    def __init__(self, title, ws):
        self.title = title
        self.ws = ws
        self.sections = []
        self.summary = []

    def add_summary(self, text, cls=''):
        self.summary.append((text, cls))

    def add_file(self, name, out_name, stats, warnings=(), error=None):
        parts = [f'<h2>{_e(name)}</h2>']
        if out_name and out_name != name:
            parts.append(f'<div class="muted">→ {_e(out_name)}</div>')
        if error:
            parts.append(f'<div class="bad">{_e(error)}</div>')
        for w in dict.fromkeys(warnings):
            parts.append(f'<div class="warn">⚠ {_e(w)}</div>')
        if stats is not None:
            chips = ''.join(f'<span class="chip">{_e(TYPE_NAMES_X.get(t, t))}: {n}</span>'
                            for t, n in sorted(stats.by_type.items()))
            parts.append(f'<div>{chips or "<span class=muted>замен нет</span>"}</div>')
            if stats.pairs:
                rows = ''.join(f'<tr><td>{_e(TYPE_NAMES_X.get(t, t))}</td><td>{_e(a)}</td><td>{_e(b)}</td>'
                               f'<td>{n}</td></tr>'
                               for (t, a, b), n in sorted(stats.pairs.items(), key=lambda x: (x[0][0], x[0][1])))
                parts.append(f'<details><summary>Что на что заменено ({len(stats.pairs)})</summary>'
                             f'<table><tr><th>Тип</th><th>Было</th><th>Стало</th><th>Раз</th></tr>{rows}</table>'
                             f'</details>')
            if stats.suspicious:
                rows = ''.join(f'<tr><td>{_e(t)}</td><td>{_e(v)}</td><td>{n}</td></tr>'
                               for (t, v), n in sorted(stats.suspicious.items()))
                parts.append(f'<div class="bad">Подозрительное:</div><table><tr><th>Что</th><th>Значение</th>'
                             f'<th>Раз</th></tr>{rows}</table>')
        self.sections.append('\n'.join(parts))

    def add_block(self, html_text):
        self.sections.append(html_text)

    def save(self):
        os.makedirs(self.ws.reports, exist_ok=True)
        now = dt.datetime.now()
        path = os.path.join(self.ws.reports, f'{now:%Y-%m-%d_%H-%M-%S}_{self.title.split()[0].lower()}.html')
        summary = ''.join(f'<div class="{c}">{_e(t)}</div>' for t, c in self.summary)
        doc = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
               f'<meta name="viewport" content="width=device-width, initial-scale=1">'
               f'<title>{_e(self.title)}</title><style>{CSS}</style></head><body>'
               f'<h1>{_e(self.title)}</h1><div class="muted">{now:%d.%m.%Y %H:%M} · {_e(self.ws.root)}</div>'
               f'<div style="margin-top:12px">{summary}</div>{"".join(self.sections)}</body></html>')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(doc)
        return path
