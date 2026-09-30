"""Поиск чувствительных данных: шаблоны, ФИО, организации, заголовки столбцов, NER."""
from functools import lru_cache
import re

from . import morph

UP = 'А-ЯЁӘҒҚҢӨҰҮҺІ'
LO = 'а-яёәғқңөұүһі'
W = rf'[{UP}][{LO}]+(?:-[{UP}][{LO}]+)?'
INIT = rf'[{UP}]\.'

# --- реквизиты ---------------------------------------------------------------

RE_EMAIL = re.compile(r'(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
TLDS = 'kz|ru|com|net|org|io|info|biz|uz|kg|by|su|pro|online|site|tech|app|dev|ai|co|me|eu|рф|қаз'
RE_DOMAIN = re.compile(rf'(?<![\w@.-])(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+(?:{TLDS}))(?![\w-])', re.I)
RE_IBAN = re.compile(r'(?<![A-Za-z0-9])KZ\d{2}(?:[ ]?[A-Z0-9]){16}(?![A-Za-z0-9])', re.I)
RE_CARD = re.compile(r'(?<![\d])(?:\d{4}[ -]?){3}\d{4}(?![\d])')
RE_ACC20 = re.compile(r'(?<![\d])\d{20}(?![\d])')
RE_12 = re.compile(r'(?<![\d])\d{12}(?![\d])')
RE_PHONE = re.compile(r'(?<![\w+])(?:\+7|8|7)[\s\-]?\(?\d(?:[\s\-()]{0,2}\d){9}(?![\d])')
RE_REKV = re.compile(r'\b(ИНН|КПП|ОГРНИП|ОГРН|ОКПО|РНН|СНИЛС)\s*(?::|№)?\s*(\d[\d\- ]{6,16}\d)(?![\d])')

# --- организации -------------------------------------------------------------

OPF = [
    'Товарищество с ограниченной ответственностью', 'Общество с ограниченной ответственностью',
    'Акционерное общество', 'Публичное акционерное общество', 'Закрытое акционерное общество',
    'Открытое акционерное общество', 'Индивидуальный предприниматель', 'Некоммерческое акционерное общество',
    'Жауапкершілігі шектеулі серіктестігі', 'Жауапкершілігі шектеулі серіктестік',
    'Акционерлік қоғам', 'Производственный кооператив', 'Крестьянское хозяйство',
    'Частное учреждение', 'Общественный фонд', 'Общественное объединение',
    'ТОО', 'ООО', 'ОАО', 'ЗАО', 'ПАО', 'НАО', 'АО', 'ИП', 'ПК', 'КХ', 'ГУ', 'КГУ', 'РГП', 'ГКП',
    'ОФ', 'ОЮЛ', 'ЧУ', 'ЖШС', 'АҚ', 'LLP', 'LLC', 'JSC', 'TOO', 'Ltd', 'Inc', 'GmbH',
]
_OPF_ALT = '|'.join(re.escape(x) for x in sorted(OPF, key=len, reverse=True))
QUOTES_OPEN = '«"“„\''
QUOTES_CLOSE = '»"”“\''
RE_ORG = re.compile(rf'(?<![\w])(?:{_OPF_ALT})\s*[{QUOTES_OPEN}]([^»"”“\n]{{2,80}}?)[{QUOTES_CLOSE}]', re.I)
_OPF_UPPER = {x.upper() for x in OPF if ' ' not in x}
RE_OPF_PREFIX = re.compile(rf'^\s*(?:{_OPF_ALT})\s+', re.I)


def strip_org(value):
    """«ТОО «Ромашка»» → «Ромашка»."""
    v = (value or '').strip()
    m = RE_ORG.search(v)
    if m:
        return m.group(1).strip()
    v = RE_OPF_PREFIX.sub('', v).strip()
    v = v.strip(QUOTES_OPEN + QUOTES_CLOSE + ' ')
    return v


# --- ФИО ---------------------------------------------------------------------

_PATR = (rf'[{UP}][{LO}]+(?:ович|евич|ьич|ич)(?:а|у|ем|е)?'
         rf'|[{UP}][{LO}]+(?:овн|евн|ичн|иничн)(?:а|ы|е|у|ой)'
         rf'|[{UP}][{LO}]+(?:ұлы|улы|қызы|кызы)'
         rf'|[{UP}][{LO}]+\s(?:ұлы|улы|қызы|кызы)')
RE_FIO_PATR = re.compile(rf'(?<![\w]){W}\s+{W}\s+(?:{_PATR})(?![\w])'      # Фамилия Имя Отчество
                         rf'|(?<![\w]){W}\s+(?:{_PATR})\s+{W}(?![\w])')     # Имя Отчество Фамилия
RE_FIO_INIT_AFTER = re.compile(rf'(?<![\w]){W}\s+{INIT}\s?(?:{INIT})?')
RE_FIO_INIT_BEFORE = re.compile(rf'(?<![\w.]){INIT}\s?(?:{INIT})?\s?{W}(?![\w])')

# --- токенизация -------------------------------------------------------------

TOKEN = re.compile(r'(?:[^\W\d_]\.)|\w+(?:[-‐]\w+)*|[«»"“”„\']')


def tokenize(text):
    return [(m.start(), m.end(), m.group()) for m in TOKEN.finditer(text)]


def split_tokens(s):
    return [t for _, _, t in tokenize(s)]


def shadow_caps(text):
    """«ИВАНОВ ИВАН» → «Иванов Иван» той же длины, чтобы шаблоны ФИО срабатывали на КАПСЕ."""
    return re.sub(rf'\b[{UP}]{{2,}}(?:-[{UP}]{{2,}})?\b', lambda m: m.group().title(), text)


# --- заголовки столбцов -----------------------------------------------------

H_PERSON = ('фио', 'ф.и.о', 'контакт', 'сотрудник', 'ответствен', 'фамилия', 'подписант', 'исполнитель',
            'менеджер', 'получатель (фио', 'аты-жөні', 'аты жөні', 'т.а.ә', 'тегі', 'руководител',
            'директор', 'бухгалтер', 'работник', 'клиент (фио', 'заявитель', 'представитель')
H_ORG = ('подрядчик', 'поставщик', 'контрагент', 'заказчик', 'клиент', 'компания', 'организация',
         'покупатель', 'получатель', 'продавец', 'арендатор', 'арендодатель', 'дебитор', 'кредитор',
         'ұйым', 'наименование юр', 'юр. лицо', 'юрлицо')
H_NUM = [(r'\bбин\b|\bбсн\b', 'bin'), (r'\bиин\b|\bжсн\b', 'iin'), (r'\bиик\b|iban|\bсч[её]т\b|р/с', 'iban'),
         (r'\bтел(ефон)?\b|моб', 'phone'), (r'\bпочта\b|e-?mail|эл\. ?почта', 'email'), (r'\bинн\b', 'inn')]
H_NOT = ('фактур', 'сумм', 'итог', 'кол-во', 'количеств', 'цена', 'дата', 'номер счета-ф', 'статус', 'вид',
         'тип', 'должност')


def kind_by_header(h):
    h = (h or '').strip().lower()
    if not h or len(h) > 60 or any(x in h for x in H_NOT):
        return None
    for rx, v in H_NUM:
        if re.search(rx, h):
            return v
    if any(k in h for k in H_PERSON):
        return 'person'
    if any(k in h for k in H_ORG):
        return 'org'
    return None


def looks(kind, v):
    v = (v or '').strip()
    if not v or v.lower() in ('итого', 'всего', '-', '—', 'нет', 'н/д'):
        return False
    digits = re.sub(r'\D', '', v)
    if kind in ('iin', 'bin'):
        return len(digits) in (11, 12) and len(digits) == len(re.sub(r'[\s-]', '', v))
    if kind == 'iban':
        return bool(RE_IBAN.fullmatch(v.replace(' ', ''))) or len(digits) == 20
    if kind == 'phone':
        return len(digits) >= 10
    if kind == 'email':
        return '@' in v
    if kind == 'inn':
        return len(digits) in (10, 12)
    return len(v) >= 2 and bool(re.search(r'[^\W\d_]', v))


# --- разбор ФИО ---------------------------------------------------------------

def parse_person(text, from_column=False):
    """Строка с ФИО → список кандидатов morph.PersonRec (лучший первым), либо []."""
    if any(ch in text for ch in QUOTES_OPEN + QUOTES_CLOSE):
        return []          # «ТОО «Шафран»» — организация, не человек
    raw = split_tokens(shadow_caps(text))
    if any(t.upper() in _OPF_UPPER for t in raw):
        return []
    toks, initials = [], []
    i = 0
    while i < len(raw):
        t = raw[i]
        if len(t) == 2 and t.endswith('.') and t[0].isupper():
            initials.append(t[0])
        elif t.lower() in morph.KZ_PATR_SUFFIXES and toks:
            toks[-1] = toks[-1] + ' ' + t.lower()
        else:
            toks.append(t)
        i += 1
    if len(initials) > 2 or not toks or len(toks) > 3:
        return []
    if any(not t[:1].isupper() for t in toks):
        return []
    patr = [t for t in toks if morph.is_patr_token(t) and toks.index(t) > 0]
    words = [t for t in toks if t not in patr]
    if len(patr) > 1:
        return []
    patr_tok = patr[0] if patr else None
    sur = name = None
    if initials:
        if len(words) != 1 or patr_tok:
            return []
        sur = words[0]
    elif patr_tok:
        if len(words) == 2:
            if toks.index(patr_tok) == 2:     # Фамилия Имя Отчество
                sur, name = words
            else:                              # Имя Отчество Фамилия
                name, sur = words
        else:
            return []
    elif len(words) == 2:
        # порядок «Имя Фамилия» или «Фамилия Имя» — какой разбор правдоподобнее
        a, b = words
        name_first = morph.resolve(b, a)
        sur_first = morph.resolve(a, b)
        s1 = name_first[0].score if name_first else -99
        s2 = sur_first[0].score if sur_first else -99
        name, sur = (b, a) if s2 > s1 else (a, b)
        if not from_column and morph.is_common_word(name) and not morph.is_name_like(name):
            return []      # «Отчёт Субботина» — не имя
    elif len(words) == 1 and from_column:
        sur = words[0]
    else:
        return []
    # «Сокол», «Отчёт»: обычное слово без известного имени рядом — скорее не человек
    if sur and not from_column and not patr_tok and morph.is_common_word(sur) \
            and not morph.is_surname_like(sur) and not (name and morph.known_name_gender(name)):
        return []
    return morph.resolve(sur, name, patr_tok, tuple(initials))


# --- NER ---------------------------------------------------------------------

@lru_cache(maxsize=None)
def _natasha():
    from natasha import Segmenter, NewsEmbedding, NewsNERTagger
    return Segmenter(), NewsNERTagger(NewsEmbedding())


def ner_persons(text):
    """Отрезки PER от Natasha (минимум два слова)."""
    if not re.search(rf'[{UP}][{LO}]+\s+[{UP}][{LO}]+', text):
        return []
    from natasha import Doc
    seg, ner = _natasha()
    doc = Doc(text)
    doc.segment(seg)
    doc.tag_ner(ner)
    return [(s.start, s.stop) for s in doc.spans if s.type == 'PER' and len(s.text.split()) >= 2]


def find_people(text, use_ner=True):
    """[(start, end, [PersonRec...])] — найденные в тексте люди."""
    sh = shadow_caps(text)
    spans = []
    for rx in (RE_FIO_PATR, RE_FIO_INIT_AFTER, RE_FIO_INIT_BEFORE):
        for m in rx.finditer(sh):
            spans.append((m.start(), m.end()))
    if use_ner:
        spans += ner_persons(sh)
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out, last_end = [], -1
    for s, e in spans:
        if s < last_end:
            continue
        cands = parse_person(text[s:e])
        if cands:
            out.append((s, e, cands))
            last_end = e
    return out


def find_orgs(text):
    return [(m.start(1), m.end(1), m.group(1).strip()) for m in RE_ORG.finditer(text)]
