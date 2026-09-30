"""Замена в тексте за один проход: прямое (оригинал → фейк) и обратное (фейк → оригинал).

Результат — список непересекающихся отрезков (start, end, новый_текст, тип, было).
"""
import re
from collections import Counter

from . import detect, fakes
from .morph import sur_base
from .registry import Registry, _norm, norm_key

FWD, REV = 'fwd', 'rev'


class Stats:
    def __init__(self):
        self.by_type = Counter()
        self.pairs = Counter()        # (тип, было, стало) → раз
        self.suspicious = Counter()   # (тип, значение) → раз

    def add(self, typ, before, after):
        self.by_type[typ] += 1
        self.pairs[(typ, before, after)] += 1

    def merge(self, other):
        self.by_type.update(other.by_type)
        self.pairs.update(other.pairs)
        self.suspicious.update(other.suspicious)

    @property
    def total(self):
        return sum(self.by_type.values())


def _free(occupied, s, e):
    for a, b in occupied:
        if s < b and a < e:
            return False
    return True


def _reg_domain(host):
    parts = host.lower().split('.')
    if len(parts) >= 3 and parts[-2] in ('com', 'org', 'net', 'gov', 'edu', 'co'):
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


def find_spans(text, reg: Registry, direction, hints=None, numbers=True, create=None):
    """Отрезки замены. hints — тип столбца ('iin', 'phone', …) для ячейки таблицы.

    create=False — только поиск уже известных оригиналов (для проверки копий).
    """
    if create is None:
        create = direction == FWD
    spans = []
    occ = []

    def put(s, e, new, typ, old):
        if new is None or new == old or not _free(occ, s, e):
            return
        spans.append((s, e, new, typ, old))
        occ.append((s, e))

    # целиком совпадающий фрагмент (ячейка с коротким названием, фамилия-обычное слово)
    idx = reg.fwd if direction == FWD else reg.rev
    stripped = text.strip()
    if stripped and norm_key(stripped) in idx.exact:
        s = text.index(stripped)
        new = idx.exact[norm_key(stripped)]
        if stripped.isupper():
            new = new.upper()
        put(s, s + len(stripped), new, 'exact', stripped)
        return spans

    for m in detect.RE_EMAIL.finditer(text):
        v = m.group()
        if direction == FWD:
            new = reg.email(v, create)
        else:
            new = reg.emails_rev.get(v.lower())
            if new is None:
                local, _, dom = v.partition('@')
                d = reg.domains_rev.get(dom.lower())
                new = f'{local}@{d}' if d else None
        put(m.start(), m.end(), new, 'email', v)

    for m in detect.RE_DOMAIN.finditer(text):
        host = m.group(1)
        rd = _reg_domain(host)
        new_rd = reg.domain(rd, create) if direction == FWD else reg.domains_rev.get(rd)
        if new_rd:
            s = m.start(1) + len(host) - len(rd)
            put(s, m.end(1), new_rd, 'domain', host[len(host) - len(rd):])

    if numbers:
        _number_spans(text, reg, direction, put, hints, create)

    _form_spans(text, idx, put)
    spans.sort()
    return spans


def _map_num(reg, typ, key, direction, create=True):
    if direction == FWD:
        return reg.num(typ, key, create)
    return reg.nums_rev[typ].get(key)


def _number_spans(text, reg, direction, put, hints, create=True):
    for m in detect.RE_IBAN.finditer(text):
        v = m.group()
        key = re.sub(r'\s', '', v).upper()
        new = _map_num(reg, 'iban', key, direction, create)
        if new:
            put(m.start(), m.end(), fakes.format_like(v.upper(), new, alnum=True), 'iban', v)

    for m in detect.RE_REKV.finditer(text):
        label, v = m.group(1), m.group(2)
        key = re.sub(r'\D', '', v)
        typ = 'inn' if label == 'ИНН' and len(key) in (10, 12) else 'rekv'
        if typ == 'inn' and len(key) == 12:
            continue   # 12 цифр обработает общий шаблон
        new = _map_num(reg, typ, key, direction, create)
        if new:
            put(m.start(2), m.end(2), fakes.format_like(v, new), typ, v)

    for m in detect.RE_ACC20.finditer(text):
        v = m.group()
        new = _map_num(reg, 'acc20', v, direction, create)
        if new:
            put(m.start(), m.end(), new, 'acc20', v)

    for m in detect.RE_CARD.finditer(text):
        v = m.group()
        key = re.sub(r'\D', '', v)
        if not fakes.luhn_valid(key):
            continue
        new = _map_num(reg, 'card', key, direction, create)
        if new:
            put(m.start(), m.end(), fakes.format_like(v, new), 'card', v)

    for m in detect.RE_12.finditer(text):
        v = m.group()
        typ = _type12(reg, v, direction, hints)
        new = _map_num(reg, typ, v, direction, create)
        if new:
            put(m.start(), m.end(), new, typ, v)

    if hints in ('iin', 'bin') and re.fullmatch(r'\s*\d{11}\s*', text):
        v = text.strip()
        key = v.zfill(12)
        typ = _type12(reg, key, direction, hints)
        new = _map_num(reg, typ, key, direction, create)
        if new:
            s = text.index(v)
            put(s, s + len(v), fakes.format_like(v, new), typ, v)

    for m in detect.RE_PHONE.finditer(text):
        v = m.group()
        key = re.sub(r'\D', '', v)[-10:]
        new = _map_num(reg, 'phone', key, direction, create)
        if new:
            put(m.start(), m.end(), fakes.format_like(v, new), 'phone', v)

    if hints == 'inn':
        digits = re.sub(r'\D', '', text)
        if len(digits) in (10, 12) and re.fullmatch(r'\s*\d+\s*', text):
            new = _map_num(reg, 'inn', digits, direction, create)
            if new:
                s = text.index(digits)
                put(s, s + len(digits), new, 'inn', digits)

    if hints == 'phone':
        digits = re.sub(r'\D', '', text)
        if len(digits) == 10 and re.fullmatch(r'[\s\d()\-+]+', text):
            new = _map_num(reg, 'phone', digits, direction, create)
            if new:
                put(0, len(text), fakes.format_like(text, new), 'phone', text)


def _type12(reg, v, direction, hints):
    if direction == REV:
        for t in ('iin', 'bin', 'num12'):
            if v in reg.nums_rev[t]:
                return t
        return 'num12'
    for t in ('iin', 'bin', 'num12'):
        if v in reg.nums[t]:
            return t
    t = fakes.classify12(v)
    if t == 'num12' and hints in ('iin', 'bin'):
        return hints
    return t


def _form_spans(text, idx, put):
    toks = detect.tokenize(text)
    n = len(toks)
    i = 0
    while i < n:
        s0, e0, t0 = toks[i]
        cands = idx.by_first.get(_norm(t0))
        matched = False
        if cands:
            for key, dst, need_q in cands:
                L = len(key)
                if i + L > n:
                    continue
                ok = True
                for j in range(1, L):
                    if _norm(toks[i + j][2]) != key[j]:
                        ok = False
                        break
                    gap = text[toks[i + j - 1][1]:toks[i + j][0]]
                    if gap.strip():
                        ok = False
                        break
                if not ok:
                    continue
                if need_q:
                    if not (i > 0 and i + L < n and toks[i - 1][2] in detect.QUOTES_OPEN
                            and toks[i + L][2] in detect.QUOTES_CLOSE):
                        continue
                s, e = s0, toks[i + L - 1][1]
                orig_toks = [toks[i + j][2] for j in range(L)]
                gaps = [text[toks[i + j][1]:toks[i + j + 1][0]] for j in range(L - 1)]
                if len(dst) == L:
                    new = dst[0] + ''.join(g + d for g, d in zip(gaps, dst[1:]))
                else:
                    new = ' '.join(dst)
                put(s, e, new, 'form', text[s:e])
                i += L
                matched = True
                break
        if not matched:
            i += 1


def apply_spans(text, spans):
    out, pos = [], 0
    for s, e, new, _, _ in spans:
        out.append(text[pos:s])
        out.append(new)
        pos = e
    out.append(text[pos:])
    return ''.join(out)


def process(text, reg, direction, stats=None, hints=None, numbers=True):
    if not isinstance(text, str) or not text.strip():
        return text
    spans = find_spans(text, reg, direction, hints, numbers)
    if stats is not None:
        for _, _, new, typ, old in spans:
            stats.add(typ, old, new)
    return apply_spans(text, spans) if spans else text


# --- поиск новых людей и организаций (прямое направление) --------------------

def learn(text, reg: Registry, use_ner=True):
    """Найти в тексте людей и организации и зарегистрировать их. Возвращает число новых."""
    if not isinstance(text, str) or not text.strip():
        return 0
    before = len(reg.persons) + len(reg.orgs)
    for _, _, name in detect.find_orgs(text):
        reg.add_org(name)
    for s, e, cands in detect.find_people(text, use_ner):
        if reg.stopped(text[s:e]):
            continue
        reg.add_person(cands)
    return len(reg.persons) + len(reg.orgs) - before


def learn_cell(kind, value, reg: Registry):
    """Значение из столбца известного типа."""
    if not detect.looks(kind, value):
        return
    if kind == 'person':
        reg.add_person(detect.parse_person(value, from_column=True))
    elif kind == 'org':
        reg.add_org(detect.strip_org(value))


# --- проверка копий ------------------------------------------------------------

def scan_leftovers(text, reg: Registry, use_ner=True):
    """Что в тексте похоже на персональные данные и не является выданным фейком.

    Возвращает [(категория, значение)]. 'утечка' — найден известный оригинал.
    """
    out = []
    if not isinstance(text, str) or not text.strip():
        return out
    for _, _, new, typ, old in find_spans(text, reg, FWD, create=False):
        out.append(('утечка', old))
    for m in detect.RE_EMAIL.finditer(text):
        a = m.group().lower()
        if a not in reg.emails_rev and a not in reg.emails:
            dom = a.partition('@')[2]
            if dom not in reg.domains_rev and dom not in _public():
                out.append(('почта', m.group()))
    checks = ((detect.RE_IBAN, 'iban', lambda v: re.sub(r'\s', '', v).upper(), 'счёт'),
              (detect.RE_12, None, lambda v: v, '12-значный номер'),
              (detect.RE_PHONE, 'phone', lambda v: re.sub(r'\D', '', v)[-10:], 'телефон'))
    for rx, typ, keyf, label in checks:
        for m in rx.finditer(text):
            if re.fullmatch(r'\d+0{6}', m.group()):
                continue   # круглая сумма, а не номер
            if re.fullmatch(r'\d{11}', m.group()) and any(
                    m.group().zfill(12) in reg.nums_rev[t] or m.group().zfill(12) in reg.nums[t]
                    for t in ('iin', 'bin', 'num12')):
                continue   # ИИН, записанный в Excel числом (ведущий ноль потерян)
            k = keyf(m.group())
            types = [typ] if typ else ['iin', 'bin', 'num12']
            if not any(k in reg.nums_rev[t] or k in reg.nums[t] for t in types):
                out.append((label, m.group()))
    for m in detect.RE_CARD.finditer(text):
        k = re.sub(r'\D', '', m.group())
        if fakes.luhn_valid(k) and k not in reg.nums_rev['card'] and k not in reg.nums['card']:
            out.append(('карта', m.group()))
    for _, _, name in detect.find_orgs(text):
        if norm_key(name) not in reg.fake_orgs and norm_key(name) not in reg.orgs and not reg.stopped(name):
            out.append(('организация', name))
    for s, e, cands in detect.find_people(text, use_ner):
        best = cands[0].score
        near = [c for c in cands if c.score >= best - 1.0]
        if not any(norm_key(sur_base(c.sur, c.gender)) in reg.fake_surnames for c in near) \
                and not reg.stopped(text[s:e]):
            out.append(('ФИО', text[s:e]))
    return out


def _public():
    from .pools import PUBLIC_DOMAINS
    return PUBLIC_DOMAINS


def fake_stems(reg: Registry):
    """Основы фейков — для поиска невосстановленных мест в результатах Claude."""
    stems = set()
    for p in reg.persons:
        base = p.fake['sur'].split('-')[0]
        stems.add(base[:-2] if len(base) > 6 else base)
    for o in reg.orgs.values():
        n = o.fake['name']
        stems.add(n[:-1] if len(n) > 5 else n)
    return {s for s in stems if len(s) >= 4}
