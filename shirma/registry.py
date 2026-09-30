"""Реестр сущностей: оригинал ↔ фейк, словоформы, хранение в SQLite."""
import json
import os
import re
import secrets
import sqlite3
import time

from . import detect, fakes, morph, pools
from .morph import CASES, PersonRec

NUM_TYPES = ('iin', 'bin', 'num12', 'iban', 'card', 'phone', 'acc20', 'inn', 'rekv')


def _norm(t):
    return t.replace('ё', 'е').replace('Ё', 'Е')


def norm_key(s):
    return _norm(re.sub(r'\s+', ' ', s.strip()).lower())


class Person:
    def __init__(self, id, orig, fake, run):
        self.id, self.orig, self.fake, self.run = id, orig, fake, run

    @property
    def gender(self):
        return self.orig['gender']


class Org:
    def __init__(self, id, orig, fake, run):
        self.id, self.orig, self.fake, self.run = id, orig, fake, run


class FormIndex:
    """Словоформы как последовательности токенов: первый токен → варианты, длинные первыми."""

    def __init__(self):
        self.by_first = {}
        self.exact = {}

    def add(self, src_tokens, dst_tokens, need_quotes=False):
        key = tuple(_norm(t) for t in src_tokens)
        lst = self.by_first.setdefault(key[0], [])
        for k, _, _ in lst:
            if k == key:
                return
        lst.append((key, list(dst_tokens), need_quotes))
        lst.sort(key=lambda x: -len(x[0]))

    def add_exact(self, src, dst):
        self.exact.setdefault(norm_key(src), dst)


class Registry:
    def __init__(self, db_path, stoplist=()):
        self.db_path = db_path
        new = not os.path.exists(db_path)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS entities(id INTEGER PRIMARY KEY, type TEXT, key TEXT,
                orig TEXT, fake TEXT, run INTEGER, UNIQUE(type, key));
            CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, direction TEXT, orig_name TEXT,
                sha256 TEXT, out_name TEXT, run INTEGER, ts REAL, UNIQUE(direction, orig_name));
        ''')
        if new or not self._meta('secret'):
            self._set_meta('secret', secrets.token_hex(16))
            self._set_meta('run', '0')
        self.secret = self._meta('secret')
        self.run = int(self._meta('run') or 0) + 1
        self._set_meta('run', str(self.run))
        self.db.commit()
        self.stoplist = {norm_key(s) for s in stoplist if s.strip()}
        self.persons, self.orgs = [], {}
        self.nums = {t: {} for t in NUM_TYPES}
        self.nums_rev = {t: {} for t in NUM_TYPES}
        self.emails, self.emails_rev = {}, {}
        self.domains, self.domains_rev = {}, {}
        self.fwd, self.rev = FormIndex(), FormIndex()
        self.orig_surnames, self.fake_surnames = set(), set()
        self.orig_orgs, self.fake_orgs = set(), set()
        self.warnings = []
        self.new_ids = set()
        self._load()

    # --- хранение ---------------------------------------------------------

    def _meta(self, k):
        r = self.db.execute('SELECT value FROM meta WHERE key=?', (k,)).fetchone()
        return r[0] if r else None

    def _set_meta(self, k, v):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (k, v))

    def _load(self):
        for id, typ, key, orig, fake, run in self.db.execute(
                'SELECT id, type, key, orig, fake, run FROM entities ORDER BY id'):
            orig, fake = json.loads(orig), json.loads(fake)
            if typ == 'person':
                self._attach_person(Person(id, orig, fake, run))
            elif typ == 'org':
                self._attach_org(Org(id, orig, fake, run))
            elif typ == 'email':
                self.emails[key] = fake
                self.emails_rev[fake.lower()] = orig
            elif typ == 'domain':
                self.domains[key] = fake
                self.domains_rev[fake.lower()] = key
            else:
                self.nums[typ][key] = fake
                self.nums_rev[typ][fake] = key

    def _insert(self, typ, key, orig, fake):
        cur = self.db.execute('INSERT INTO entities(type, key, orig, fake, run) VALUES(?,?,?,?,?)',
                              (typ, key, json.dumps(orig, ensure_ascii=False),
                               json.dumps(fake, ensure_ascii=False), self.run))
        self.new_ids.add(cur.lastrowid)
        return cur.lastrowid

    def _update(self, id, orig):
        self.db.execute('UPDATE entities SET orig=?, key=key WHERE id=?',
                        (json.dumps(orig, ensure_ascii=False), id))

    def commit(self):
        self.db.commit()

    def file_record(self, direction, orig_name):
        return self.db.execute('SELECT sha256, out_name, run FROM files WHERE direction=? AND orig_name=?',
                               (direction, orig_name)).fetchone()

    def save_file(self, direction, orig_name, sha, out_name):
        self.db.execute('INSERT OR REPLACE INTO files(direction, orig_name, sha256, out_name, run, ts) '
                        'VALUES(?,?,?,?,?,?)', (direction, orig_name, sha, out_name, self.run, time.time()))

    def entities_since(self, run):
        return [p for p in self.persons if p.run > run] + [o for o in self.orgs.values() if o.run > run]

    def stopped(self, s):
        return norm_key(s) in self.stoplist

    # --- люди --------------------------------------------------------------

    def _compatible(self, p, rec):
        o = p.orig
        if o['gender'] != rec.gender or norm_key(o['sur']) != norm_key(rec.sur):
            return False
        for a, b in ((o.get('name'), rec.name), (o.get('patr'), rec.patr)):
            if a and b and norm_key(a) != norm_key(b):
                return False
        for a, b in ((o.get('init_n'), rec.init_n), (o.get('init_p'), rec.init_p)):
            if a and b and _norm(a) != _norm(b):
                return False
        return True

    def find_person(self, cands):
        best = cands[0].score
        for rec in cands:
            if rec.score < best - 1.0:
                break
            for p in self.persons:
                if self._compatible(p, rec):
                    return p, rec
        return None, None

    def add_person(self, cands):
        """Найти или создать человека по кандидатам разбора. Возвращает Person или None."""
        if not cands:
            return None
        p, rec = self.find_person(cands)
        if p:
            changed = False
            for k in ('name', 'patr', 'init_n', 'init_p', 'patr_style'):
                if getattr(rec, k) and not p.orig.get(k):
                    p.orig[k] = getattr(rec, k)
                    changed = True
            if changed:
                self._update(p.id, p.orig)
                self._attach_person(p, refresh=True)
            return p
        rec = cands[0]
        if self.stopped(rec.sur) or (rec.name and self.stopped(f'{rec.name} {rec.sur}')) \
                or self.stopped(f'{rec.sur} {rec.name or ""} {rec.patr or ""}'.strip()):
            return None
        orig = {k: getattr(rec, k) for k in ('sur', 'gender', 'name', 'patr', 'init_n', 'init_p',
                                             'patr_style', 'kz')}
        fake = self._fake_person(orig)
        base = norm_key(morph.sur_base(rec.sur, rec.gender))
        if base in self.fake_surnames:
            self.warnings.append(('коллизия', f'Фамилия {rec.sur} совпадает с ранее выданным фейком — '
                                              f'обратная замена для неё ненадёжна'))
        id = self._insert('person', f'{base}|{rec.gender}|{len(self.persons)}', orig, fake)
        p = Person(id, orig, fake, self.run)
        self._attach_person(p)
        return p

    def _fake_person(self, orig):
        g, kz = orig['gender'], orig.get('kz')
        cls = morph.surname_class(orig['sur'], g)
        if cls == 'adj':
            pool = pools.SURNAMES_ADJ
        elif cls == 'indecl':
            pool = pools.SURNAMES_INDECL
        elif cls == 'cons':
            pool = pools.SURNAMES_CONS
        else:
            pool = pools.SURNAMES_OV_KZ if kz else pools.SURNAMES_OV_RU
        names = (pools.NAMES_M_KZ if g == 'm' else pools.NAMES_F_KZ) if kz else \
                (pools.NAMES_M_RU if g == 'm' else pools.NAMES_F_RU)
        fathers = pools.FATHERS_KZ if kz else pools.FATHERS_RU
        orig_base = norm_key(morph.sur_base(orig['sur'], g))
        rng = fakes.rng_for(self.secret, 'person', orig_base, orig.get('name'), orig.get('init_n'), g)
        # фейк не должен даже частично совпадать с настоящими фамилиями
        stems = {k[:-2] if len(k) > 5 else k for k in self.orig_surnames | {orig_base}}
        stems = {st for st in stems if len(st) >= 4}

        def clean(word):
            w = norm_key(word)
            return not any(st in w for st in stems)

        order = pool[:]
        rng.shuffle(order)
        extra = [f'{a}-{b}' for a in order[:20] for b in order[20:40]]
        sur_m = None
        for cand in order + extra:
            k = norm_key(cand)
            if k not in self.fake_surnames and clean(cand):
                sur_m = cand
                break
        if g == 'f' and sur_m.lower().endswith(('ов', 'ев', 'ёв', 'ин', 'ын')):
            sur = sur_m + 'а'
        elif g == 'f' and sur_m.endswith('ий'):
            sur = sur_m[:-2] + 'ая'
        else:
            sur = sur_m
        # несклоняемое имя (Айгерим) ↔ несклоняемое, иначе падеж при замене не сохранится
        on = orig.get('name')
        if on:
            indecl = len(set(morph.decline_name(on, g))) == 1
            same = [n for n in names if (len(set(morph.decline_name(n, g))) == 1) == indecl]
            if not same:
                alt = (pools.NAMES_M_RU + pools.NAMES_M_KZ) if g == 'm' else (pools.NAMES_F_RU + pools.NAMES_F_KZ)
                same = [n for n in alt if (len(set(morph.decline_name(n, g))) == 1) == indecl]
            names = same or names
        names = [n for n in names if n != on and clean(n)] or names
        name = rng.choice(names)
        op = norm_key(orig.get('patr') or '')
        fathers = [x for x in fathers if clean(morph.make_patr(x, g))
                   and (not op or (norm_key(morph.make_patr(x, g)) != op and not op.startswith(norm_key(x))))] \
            or fathers
        father = rng.choice(fathers)
        style = orig.get('patr_style') or 'ru'
        if style == 'ru':
            patr = morph.make_patr(father, g)
        else:
            suffix = next((s for s in morph.KZ_PATR_SUFFIXES if (orig.get('patr') or '').lower().endswith(s)),
                          'ұлы' if g == 'm' else 'қызы')
            patr = father + (' ' if style == 'kz_sep' else '') + suffix
        return {'sur': sur, 'name': name, 'patr': patr, 'gender': g}

    def _attach_person(self, p, refresh=False):
        if not refresh:
            self.persons.append(p)
        o, f = p.orig, p.fake
        g = o['gender']
        self.orig_surnames.add(norm_key(morph.sur_base(o['sur'], g)))
        self.fake_surnames.add(norm_key(morph.sur_base(f['sur'], g)))
        for src, dst, exact_only in person_forms(o, f):
            if exact_only:
                self.fwd.add_exact(' '.join(src), ' '.join(dst))
                self.rev.add_exact(' '.join(dst), ' '.join(src))
            else:
                self.fwd.add(src, dst)
                self.rev.add(dst, src)

    # --- организации -------------------------------------------------------

    def add_org(self, name):
        name = re.sub(r'\s+', ' ', (name or '').strip())
        if len(name) < 2 or not re.search(r'[^\W\d_]', name):
            return None
        key = norm_key(name)
        if key in self.orgs:
            return self.orgs[key]
        if self.stopped(name) or key in self.fake_orgs:
            return None
        rng = fakes.rng_for(self.secret, 'org', key)
        order = pools.ORG_NAMES[:]
        rng.shuffle(order)
        latin = not re.search('[а-яёәғқңөұүһі]', name.lower())
        fake = None
        for cand in order + [f'{a}-{b}' for a in order[:30] for b in order[30:60]]:
            if latin:
                cand = fakes.translit(cand).capitalize()
            k = norm_key(cand)
            if k not in self.fake_orgs and k not in self.orig_orgs and k != key:
                fake = cand
                break
        if name.isupper() and len(name) > 1:
            fake = fake.upper()
        id = self._insert('org', key, {'name': name}, {'name': fake})
        o = Org(id, {'name': name}, {'name': fake}, self.run)
        self._attach_org(o)
        return o

    def _attach_org(self, o):
        key = norm_key(o.orig['name'])
        self.orgs[key] = o
        self.orig_orgs.add(key)
        self.fake_orgs.add(norm_key(o.fake['name']))
        for src, dst in org_forms(o.orig['name'], o.fake['name']):
            need_q = len(src[0]) < 4 and len(src) == 1
            self.fwd.add(src, dst, need_q)
            self.rev.add(dst, src, need_q)
        self.fwd.add_exact(o.orig['name'], o.fake['name'])
        self.rev.add_exact(o.fake['name'], o.orig['name'])

    # --- числа, почта, домены ---------------------------------------------

    def num(self, typ, key, create=True):
        m = self.nums[typ]
        if key in m:
            return m[key]
        if key in self.nums_rev[typ]:   # это уже фейк
            return key
        if not create or self.stopped(key):
            return None
        rng = fakes.rng_for(self.secret, typ, key)
        gen = {
            'iin': fakes.fake_iin, 'bin': fakes.fake_bin, 'num12': fakes.fake_num12,
            'iban': fakes.fake_iban, 'card': fakes.fake_card, 'phone': fakes.fake_phone,
            'acc20': lambda r, o: fakes.fake_digits(r, o, keep=5),
            'inn': fakes.fake_inn_ru, 'rekv': lambda r, o: fakes.fake_digits(r, o, keep=2),
        }[typ]
        for _ in range(100):
            fake = gen(rng, key)
            if fake != key and fake not in self.nums_rev[typ] and fake not in m:
                break
        m[key] = fake
        self.nums_rev[typ][fake] = key
        self._insert(typ, key, key, fake)
        return fake

    def domain(self, dom, create=True):
        d = dom.lower()
        if d in self.domains:
            return self.domains[d]
        if d in self.domains_rev:
            return d
        if not create or d in pools.PUBLIC_DOMAINS or d.endswith('.gov.kz') or self.stopped(d):
            return None
        parts = d.split('.')
        label, suffix = parts[0], '.'.join(parts[1:])
        fake_label = None
        for o in self.orgs.values():
            if label in {v.replace(' ', '').replace('-', '') for v in fakes.translit_variants(o.orig['name'])}:
                fake_label = fakes.translit(o.fake['name']).replace(' ', '').replace('-', '')
                break
        rng = fakes.rng_for(self.secret, 'domain', d)
        order = pools.ORG_NAMES[:]
        rng.shuffle(order)
        cands = ([fake_label] if fake_label else []) + [fakes.translit(x) for x in order] + \
                [fakes.translit(a) + fakes.translit(b) for a in order[:20] for b in order[20:40]]
        for c in cands:
            fake = f'{c}.{suffix}'
            if fake != d and fake not in self.domains_rev and fake not in self.domains:
                break
        self.domains[d] = fake
        self.domains_rev[fake] = d
        self._insert('domain', d, d, fake)
        return fake

    def email(self, addr, create=True):
        a = addr.lower()
        if a in self.emails:
            return self.emails[a]
        if a in self.emails_rev:
            return addr
        if not create or self.stopped(a):
            return None
        local, _, dom = a.partition('@')
        fdom = self.domain(dom) or dom
        flocal = self._fake_local(local, a)
        fake = f'{flocal}@{fdom}'
        n = 2
        while fake in self.emails_rev:
            fake = f'{flocal}{n}@{fdom}'
            n += 1
        self.emails[a] = fake
        self.emails_rev[fake] = a
        self._insert('email', a, a, fake)
        return fake

    def _fake_local(self, local, full):
        if local in pools.GENERIC_EMAIL_LOCALS:
            return local
        for p in self.persons:
            o, f = p.orig, p.fake
            g = o['gender']
            for v in fakes.translit_variants(morph.sur_base(o['sur'], g)):
                vf = v + 'a' if g == 'f' else v
                for vv in (vf, v):
                    if len(vv) >= 4 and vv in local:
                        fsur = fakes.translit(f['sur'])
                        res = local.replace(vv, fsur, 1)
                        # инициалы рядом с фамилией: a.ivanova, ivanov_ai
                        fi = fakes.translit(f['name'])[:1] + fakes.translit(f['patr'])[:1]
                        q = re.escape(fsur)
                        res = re.sub(rf'^([a-z]{{1,2}})(?=[._-]?{q})', lambda m: fi[:len(m.group(1))], res)
                        res = re.sub(rf'(?<={q})([._-]?)([a-z]{{1,2}})(?=\d*$)',
                                     lambda m: m.group(1) + fi[:len(m.group(2))], res)
                        return res
        rng = fakes.rng_for(self.secret, 'email', full)
        base = fakes.translit(rng.choice(pools.SURNAMES_OV_RU))
        digits = re.sub(r'\D', '', local)
        if digits:
            digits = ''.join(rng.choice('0123456789') for _ in digits)
        return base + digits

    # --- статистика --------------------------------------------------------

    def export_csv(self, path):
        import csv
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(['Тип', 'Настоящее значение', 'Замена'])
            for p in self.persons:
                w.writerow(['Человек', person_display(p.orig), person_display(p.fake)])
            for o in self.orgs.values():
                w.writerow(['Организация', o.orig['name'], o.fake['name']])
            for t in NUM_TYPES:
                for k, v in self.nums[t].items():
                    w.writerow([TYPE_NAMES[t], k, v])
            for k, v in self.emails.items():
                w.writerow(['Почта', k, v])
            for k, v in self.domains.items():
                w.writerow(['Домен', k, v])
        os.replace(tmp, path)


TYPE_NAMES = {'iin': 'ИИН', 'bin': 'БИН', 'num12': '12-значный номер', 'iban': 'Счёт (IBAN)', 'card': 'Карта',
              'phone': 'Телефон', 'acc20': 'Счёт (20 цифр)', 'inn': 'ИНН', 'rekv': 'Реквизит',
              'email': 'Почта', 'domain': 'Домен', 'person': 'Человек', 'org': 'Организация'}


def person_display(d):
    parts = [d.get('sur'), d.get('name'), d.get('patr')]
    s = ' '.join(x for x in parts if x)
    if not d.get('name') and d.get('init_n'):
        s += f" {d['init_n']}." + (f"{d['init_p']}." if d.get('init_p') else '')
    return s


def _upper(tokens):
    return [t.upper() for t in tokens]


def person_forms(o, f):
    """[(src_tokens, dst_tokens, exact_only)] для всех падежей и связок."""
    g = o['gender']
    tk = detect.split_tokens
    os_ = morph.decline_surname(o['sur'], g)
    fs_ = morph.decline_surname(f['sur'], g)
    on = morph.decline_name(o['name'], g) if o.get('name') else None
    fn = morph.decline_name(f['name'], g)
    op = morph.decline_patr(o['patr'], g) if o.get('patr') else None
    fp = morph.decline_patr(f['patr'], g)
    oi = [x + '.' for x in (o.get('init_n'), o.get('init_p')) if x]
    fi = [f['name'][0] + '.', f['patr'][0] + '.'][:len(oi)]
    sur_alone_ok = len(o['sur']) >= 3 and not morph.is_common_word(o['sur'])
    out = []
    for c in range(6):
        S, FS = [os_[c]], [fs_[c]]
        combos = [(S, FS, not sur_alone_ok)]
        if oi:
            combos += [(S + oi, FS + fi, False), (oi + S, fi + FS, False)]
            if len(oi) == 2:
                combos += [(S + oi[:1], FS + fi[:1], False), (oi[:1] + S, fi[:1] + FS, False)]
        if on:
            N, FN = tk(on[c]), tk(fn[c])
            combos += [(N + S, FN + FS, False), (S + N, FS + FN, False)]
            if op:
                P, FP = tk(op[c]), tk(fp[c])
                combos += [(S + N + P, FS + FN + FP, False), (N + P + S, FN + FP + FS, False),
                           (N + P, FN + FP, False)]
        for src, dst, exact in combos:
            src = [t for s in src for t in tk(s)]
            dst = [t for s in dst for t in tk(s)]
            out.append((src, dst, exact))
            out.append((_upper(src), _upper(dst), exact))
    return out


def _noun_forms(name):
    """Склонение однословного названия (Ромашка → Ромашки…); None, если не склоняем."""
    if not re.fullmatch(r'[А-ЯЁ][а-яё]+', name):
        return None
    l = name.lower()
    if l[-1] in 'ая':
        return morph._a_decl(name)
    if l[-1] in 'бвгджзклмнпрстфхцчшщ':
        return morph._cons_decl(name)
    return None


def org_forms(orig, fake):
    tk = detect.split_tokens
    pairs = [(orig, fake)]
    of, ff = _noun_forms(orig), _noun_forms(fake)
    if of and ff:
        pairs = list(zip(of, ff))
    out = []
    for a, b in pairs:
        out.append((tk(a), tk(b)))
        if not orig.isupper():
            out.append((_upper(tk(a)), _upper(tk(b))))
    return out
