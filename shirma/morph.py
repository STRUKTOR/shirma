"""Склонение и нормализация ФИО по правилам (русские и казахские имена).

Падежи всегда в порядке CASES. Функции decline_* возвращают список из 6 форм.
Нормализация — перебором: подставляем возможные окончания именительного падежа
и проверяем, что склонение кандидата даёт исходное слово.
"""
from dataclasses import dataclass, field
from functools import lru_cache
import re

from . import pools

CASES = ('nomn', 'gent', 'datv', 'accs', 'ablt', 'loct')
KZ_LETTERS = set('әғқңөұүһіӘҒҚҢӨҰҮҺІ')
KZ_PATR_SUFFIXES = ('ұлы', 'улы', 'қызы', 'кызы')
KZ_SURNAME_HINTS = ('баев', 'беков', 'ханов', 'жанов', 'галиев', 'баева', 'бекова', 'ханова',
                    'жанова', 'галиева', 'тбаев', 'гулов', 'гулова', 'магамбетов', 'кенов')
# Частые казахские имена — только для распознавания происхождения (не для фейков).
KZ_NAME_HINTS = set('''
Азамат Айдар Айдос Акылбек Алибек Алмас Алмат Аслан Асхат Бауыржан Бекзат Болат Галым Дамир Данияр
Дастан Досым Ельдар Ерболат Ерлан Ермек Жандос Жанибек Кайрат Канат Мадияр Марат Мейрам Нурбол Нурлан
Нұрлан Нурсултан Олжас Рустем Сакен Серик Серік Талгат Тимур Улан Шынгыс Ерик Бахыт Сабит Даулет
Жасулан Ербол Максат Арман Айгерим Айгуль Айжан Айнур Акмарал Алия Асель Әсел Ботагоз Гульмира
Гульнара Динара Жанар Жулдыз Зарина Индира Камила Ляззат Мадина Меруерт Назгуль Салтанат Сауле
Толганай Томирис Шолпан Айдана Аружан Дильназ Жибек Камшат Райхан Умит Гүлнұр Әсем Ақмарал
'''.split())
_HISS = set('жшчщц')
_VELAR_HISS = set('гкхжшчщ')
_VOWELS = set('аеёиоуыэюяәөұүі')
_FLEETING = {'Павел': 'Павл', 'Лев': 'Льв', 'Пётр': 'Петр'}
_FLEETING_BACK = {v: k for k, v in _FLEETING.items()}


def _lower(s):
    return s.lower()


def _a_decl(nom):
    """Склонение на -а/-я (Жанна, Никита, Мария, Илья)."""
    l = nom.lower()
    if l.endswith('ия'):
        st = nom[:-1]
        return [nom, st + 'и', st + 'и', st + 'ю', st + 'ей', st + 'и']
    if l.endswith('я'):
        st = nom[:-1]
        return [nom, st + 'и', st + 'е', st + 'ю', st + 'ей', st + 'е']
    st = nom[:-1]
    last = st[-1:].lower()
    gen = st + ('и' if last in _VELAR_HISS else 'ы')
    abl = st + ('ей' if last in _HISS else 'ой')
    return [nom, gen, st + 'е', st + 'у', abl, st + 'е']


def _cons_decl(nom, stem=None):
    st = stem or nom
    abl = 'ем' if st[-1:].lower() in _HISS else 'ом'
    return [nom, st + 'а', st + 'у', st + 'а', st + abl, st + 'е']


def _soft_decl(nom):
    st = nom[:-1]
    return [nom, st + 'я', st + 'ю', st + 'я', st + 'ем', st + 'е']


def _indecl(nom):
    return [nom] * 6


def surname_class(nom, gender):
    l = nom.lower().split('-')[-1]
    if gender == 'm':
        if l.endswith(('ов', 'ев', 'ёв', 'ин', 'ын')):
            return 'ov'
        if l.endswith(('ий', 'ый', 'ой')) and len(l) > 4:
            return 'adj'
    else:
        if l.endswith(('ова', 'ева', 'ёва', 'ина', 'ына')):
            return 'ov'
        if l.endswith(('ая', 'яя')) and len(l) > 4:
            return 'adj'
    if l.endswith(('о', 'е', 'э', 'и', 'ы', 'у', 'ю', 'их', 'ых')) or l.endswith(KZ_PATR_SUFFIXES):
        return 'indecl'
    if l[-1:] in ('а', 'я'):
        return 'a'
    return 'cons' if gender == 'm' else 'indecl'


def _decline_surname_part(nom, gender):
    l = nom.lower()
    cls = surname_class(nom, gender)
    if cls == 'ov':
        if gender == 'm':
            return [nom, nom + 'а', nom + 'у', nom + 'а', nom + 'ым', nom + 'е']
        st = nom[:-1]
        return [nom, st + 'ой', st + 'ой', st + 'у', st + 'ой', st + 'ой']
    if cls == 'adj':
        st = nom[:-2]
        if gender == 'm':
            ins = 'им' if l.endswith('ий') or st[-1:].lower() in _VELAR_HISS else 'ым'
            return [nom, st + 'ого', st + 'ому', st + 'ого', st + ins, st + 'ом']
        return [nom, st + 'ой', st + 'ой', st + 'ую', st + 'ой', st + 'ой']
    if cls == 'a':
        return _a_decl(nom)
    if cls == 'indecl':
        return _indecl(nom)
    # cons, мужской род
    if l.endswith(('ь', 'й')):
        return _soft_decl(nom)
    return _cons_decl(nom)


def decline_surname(nom, gender):
    parts = nom.split('-')
    if len(parts) == 1:
        return _decline_surname_part(nom, gender)
    declined = [_decline_surname_part(p, gender) for p in parts]
    return ['-'.join(d[i] for d in declined) for i in range(6)]


def decline_name(nom, gender):
    l = nom.lower()
    if l[-1:] in ('а', 'я'):
        return _a_decl(nom)
    if gender == 'm':
        if l.endswith('ий'):
            st = nom[:-1]
            return [nom, st + 'я', st + 'ю', st + 'я', st + 'ем', st + 'и']
        if l.endswith(('й', 'ь')):
            return _soft_decl(nom)
        if l[-1:] in _VOWELS:
            return _indecl(nom)
        return _cons_decl(nom, _FLEETING.get(nom))
    if l.endswith('ь'):
        st = nom[:-1]
        return [nom, st + 'и', st + 'и', nom, st + 'ью', st + 'и']
    return _indecl(nom)


def decline_patr(nom, gender):
    l = nom.lower()
    if l.endswith(KZ_PATR_SUFFIXES):
        return _indecl(nom)
    if gender == 'm' and l.endswith('ич'):
        return [nom, nom + 'а', nom + 'у', nom + 'а', nom + 'ем', nom + 'е']
    if gender == 'f' and l.endswith('на'):
        st = nom[:-1]
        return [nom, st + 'ы', st + 'е', st + 'у', st + 'ой', st + 'е']
    return _indecl(nom)


def make_patr(father, gender):
    """Отчество по-русски из имени отца."""
    l = father.lower()
    if father == 'Павел':
        st = 'Павл'
    elif father == 'Лев':
        st = 'Льв'
    elif l.endswith('ий'):
        st = father[:-2] + 'ь'
        return st + ('евич' if gender == 'm' else 'евна')
    elif l.endswith(('й', 'ь')):
        st = father[:-1]
        return st + ('евич' if gender == 'm' else 'евна')
    else:
        st = father
    return st + ('ович' if gender == 'm' else 'овна')


# --- нормализация -----------------------------------------------------------

_NOM_ADDS = ('', 'а', 'я', 'й', 'ь', 'ий', 'ый', 'ой', 'ая', 'ия')


def _norm_e(s):
    return s.replace('ё', 'е').replace('Ё', 'Е')


def _candidates(token, decline, extra_stems=()):
    """[(nom, gender, case)] — все кандидаты, чьё склонение даёт token."""
    out = []
    t = _norm_e(token)
    stems = set()
    for cut in range(0, 4):
        if cut >= len(token):
            break
        stem = token[:len(token) - cut]
        for add in _NOM_ADDS:
            stems.add(stem + add)
    stems.update(extra_stems)
    for cand in stems:
        if len(cand) < 2:
            continue
        for g in ('m', 'f'):
            forms = decline(cand, g)
            for i, f in enumerate(forms):
                if _norm_e(f) == t:
                    out.append((cand, g, CASES[i]))
    return out


@lru_cache(maxsize=None)
def _morph():
    import pymorphy3
    return pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=20000)
def known_name_gender(nom):
    """'m'/'f', если имя известно словарю или пулам, иначе None."""
    for g, pool in (('m', pools.NAMES_M_RU), ('f', pools.NAMES_F_RU),
                    ('m', pools.NAMES_M_KZ), ('f', pools.NAMES_F_KZ)):
        if nom in pool:
            return g
    for p in _morph().parse(nom.lower()):
        if 'Name' in p.tag and p.is_known and _norm_e(p.normal_form) == _norm_e(nom.lower()) and p.score >= 0.1:
            if 'masc' in p.tag:
                return 'm'
            if 'femn' in p.tag:
                return 'f'
    return None


@lru_cache(maxsize=20000)
def is_name_like(word):
    """Похоже ли слово (в любом падеже) на личное имя."""
    for p in _morph().parse(word.lower()):
        if 'Name' in p.tag and p.is_known and p.score >= 0.05:
            return True
    return False


@lru_cache(maxsize=20000)
def is_surname_like(word):
    l = word.lower()
    if re.search(r'(ов|ев|ёв|ин|ын|ова|ева|ина|ына|ский|цкий|ская|цкая|енко|ко|ых|их|ук|юк|ян|дзе|швили)'
                 r'(а|у|ым|е|ой|ого|ому|им|ом|ую)?$', l):
        return True
    for p in _morph().parse(l):
        if 'Surn' in p.tag and p.score >= 0.1:
            return True
    return False


@lru_cache(maxsize=20000)
def is_common_word(word):
    """Обычное слово языка (не только имя/фамилия/топоним)."""
    for p in _morph().parse(word.lower()):
        tag = p.tag
        if not p.is_known or p.score < 0.05:
            continue
        if any(x in tag for x in ('Name', 'Surn', 'Patr', 'Geox', 'Orgn', 'Trad', 'Poss', 'Abbr')):
            continue
        if tag.POS in ('NOUN', 'ADJF', 'ADJS', 'VERB', 'INFN', 'PRTF', 'PRTS', 'ADVB', 'NPRO',
                       'PREP', 'CONJ', 'PRCL', 'NUMR', 'COMP', 'PRED', 'GRND', 'INTJ'):
            return True
    return False


def surname_score(nom, g):
    cls = surname_class(nom, g)
    if cls == 'adj' and not re.search(r'(ск|цк)(ий|ой|ая)$', nom.lower()):
        return 1.0
    if cls == 'indecl' and g == 'f' and nom[-1:].lower() not in _VOWELS and not nom.lower().endswith(('их', 'ых')):
        return 1.0   # женская фамилия на согласную (Ким, Сокол) — реже, чем мужская
    return {'ov': 3.0, 'adj': 3.0, 'indecl': 1.5, 'cons': 1.2, 'a': 0.4}[cls]


def name_score(nom, g):
    kg = known_name_gender(nom)
    if kg == g:
        return 3.0
    if kg is not None:
        return -2.0
    l = nom.lower()
    if g == 'f' and l[-1:] in ('а', 'я'):
        return 1.0
    if g == 'm' and l[-1:] not in _VOWELS and l[-1:] not in ('а', 'я'):
        return 1.0
    if g == 'f':
        return 0.6   # казахские женские имена на согласную (Айгерим) не склоняются
    return 0.2


@dataclass
class PersonRec:
    sur: str                      # фамилия в им. п. данного пола
    gender: str                   # 'm' / 'f'
    name: str | None = None       # имя в им. п.
    patr: str | None = None       # отчество в им. п. («Серік ұлы» — два слова)
    init_n: str | None = None     # инициал имени (буква)
    init_p: str | None = None     # инициал отчества
    patr_style: str | None = None  # 'ru' / 'kz' / 'kz_sep'
    kz: bool = False
    case: str = 'nomn'
    score: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def key(self):
        return _norm_e(sur_base(self.sur, self.gender).lower())


def sur_base(sur, gender):
    """Фамилия, приведённая к мужской форме (для ключа)."""
    if gender == 'f':
        parts = []
        for p in sur.split('-'):
            l = p.lower()
            if l.endswith(('ова', 'ева', 'ёва', 'ина', 'ына')):
                p = p[:-1]
            elif l.endswith('ая') and len(l) > 4:
                p = p[:-2] + ('ий' if p[-3:-2].lower() in _VELAR_HISS else 'ий')
            parts.append(p)
        return '-'.join(parts)
    return sur


def _patr_cands(token):
    l = token.lower()
    if l.endswith(KZ_PATR_SUFFIXES):
        g = 'm' if l.endswith(('ұлы', 'улы')) else 'f'
        return [(token, g, c) for c in CASES]
    return [c for c in _candidates(token, decline_patr)
            if c[0].lower().endswith(('ич', 'на'))]


def is_patr_token(token):
    l = token.lower()
    if l.endswith(KZ_PATR_SUFFIXES):
        return True
    return bool(re.search(r'(ович|евич|ьич|ич)(а|у|ем|е)?$|(овн|евн|ичн|иничн)(а|ы|е|у|ой)$', l))


def is_kz_person(sur, name, patr_style):
    text = (sur or '') + (name or '')
    if any(ch in KZ_LETTERS for ch in text):
        return True
    if patr_style in ('kz', 'kz_sep'):
        return True
    if name and (name in KZ_NAME_HINTS or name in pools.NAMES_M_KZ or name in pools.NAMES_F_KZ):
        return True
    if sur and sur.lower().endswith(KZ_SURNAME_HINTS):
        return True
    if name and known_name_gender(name) is None and not is_name_like(name):
        return True
    return False


_CASE_BONUS = {'nomn': 0.3, 'gent': 0.05, 'datv': 0.04, 'accs': 0.03, 'ablt': 0.02, 'loct': 0.01}


def resolve(sur_tok=None, name_tok=None, patr_tok=None, initials=()):
    """Все согласованные разборы ФИО, лучшие первыми."""
    if not sur_tok:
        return []
    s_c = _candidates(sur_tok, decline_surname)
    n_c = _candidates(name_tok, decline_name,
                      extra_stems=[_FLEETING_BACK[s] for s in _FLEETING_BACK
                                   if name_tok.startswith(s)]) if name_tok else None
    p_c = _patr_cands(patr_tok) if patr_tok else None
    results = []
    for g in ('m', 'f'):
        for case in CASES:
            best_s = max((surname_score(n, g), n) for n, gg, cc in s_c if gg == g and cc == case) \
                if any(gg == g and cc == case for _, gg, cc in s_c) else None
            if best_s is None:
                continue
            score = best_s[0]
            name = patr = None
            if n_c is not None:
                opts = [(name_score(n, g), n) for n, gg, cc in n_c if gg == g and cc == case]
                if not opts:
                    continue
                sc, name = max(opts)
                score += sc
            if p_c is not None:
                opts = [n for n, gg, cc in p_c if gg == g and cc == case]
                if not opts:
                    continue
                patr = opts[0]
                score += 5
            score += _CASE_BONUS[case]
            results.append((score, g, case, best_s[1], name, patr))
    results.sort(key=lambda r: -r[0])
    out, seen = [], set()
    for score, g, case, sur, name, patr in results:
        k = (g, sur, name, patr)
        if k in seen:
            continue
        seen.add(k)
        style = None
        if patr:
            l = patr.lower()
            style = ('kz_sep' if ' ' in patr else 'kz') if l.endswith(KZ_PATR_SUFFIXES) else 'ru'
        init_n = name[0] if name else (initials[0] if initials else None)
        init_p = patr[0] if patr else (initials[1] if len(initials) > 1 else None)
        out.append(PersonRec(sur=sur, gender=g, name=name, patr=patr, init_n=init_n, init_p=init_p,
                             patr_style=style, kz=is_kz_person(sur, name, style), case=case, score=score))
    return out
