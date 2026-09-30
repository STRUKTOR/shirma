"""docx / xlsx / pptx — работа прямо с XML внутри архива.

Абзац собирается из кусков текста (runs), замена раскладывается обратно по кускам:
форматирование сохраняется, даже если имя разбито между runs. После точечной обработки
все остальные текстовые узлы и атрибуты всех XML-частей проходят через общую замену.
"""
import io
import re
import zipfile

from lxml import etree

from .. import detect, fakes
from ..replace import FWD, find_spans, learn, learn_cell, process

NS_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
NS_S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'


def q(ns, tag):
    return f'{{{ns}}}{tag}'


PARA_TEXT = {
    q(NS_W, 'p'): (q(NS_W, 't'), q(NS_W, 'delText')),
    q(NS_A, 'p'): (q(NS_A, 't'),),
    q(NS_S, 'si'): (q(NS_S, 't'),),
    q(NS_S, 'is'): (q(NS_S, 't'),),
    q(NS_S, 'text'): (q(NS_S, 't'),),
}
PARA_TAGS = tuple(PARA_TEXT)
ALL_TEXT_TAGS = tuple({t for v in PARA_TEXT.values() for t in v})
# Перенос строки и табуляция внутри абзаца — граница слова: без неё «…877<br/>Иванов» склеится в одно слово
BREAK_TAGS = (q(NS_W, 'br'), q(NS_W, 'cr'), q(NS_W, 'tab'), q(NS_A, 'br'))
S_RPH = q(NS_S, 'rPh')

AUTHOR_ATTRS = {'author': 'Автор', 'initials': 'А', 'displayName': 'Автор'}
SKIP_ATTRS = {'id', 'Id', 'r', 'ref', 'sqref', 't', 's', 'spans', 'Type', 'TargetMode', 'ContentType',
              'Extension', 'PartName', 'rsidR', 'rsidRPr', 'rsidRDefault', 'rsidP', 'rsidTr', 'rsidDel',
              'paraId', 'textId', 'embed', 'link', 'uri'}
MAX_SHEET_NAME = 31

OOXML_EXT = ('.docx', '.xlsx', '.pptx', '.docm', '.xlsm', '.pptm')


def local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


class Package:
    def __init__(self, data):
        self.zin = zipfile.ZipFile(io.BytesIO(data))
        self.infos = self.zin.infolist()
        self.names = [i.filename for i in self.infos]
        self.trees = {}
        self.raw = {}
        self.images = 0
        self.ole = 0

    @property
    def kind(self):
        if 'word/document.xml' in self.names:
            return 'docx'
        if 'xl/workbook.xml' in self.names:
            return 'xlsx'
        if 'ppt/presentation.xml' in self.names:
            return 'pptx'
        return 'ooxml'

    def xml_parts(self):
        return [n for n in self.names if n.endswith(('.xml', '.rels', '.vml'))]

    def tree(self, name):
        if name not in self.trees:
            parser = etree.XMLParser(huge_tree=True, remove_blank_text=False, resolve_entities=False)
            self.trees[name] = etree.fromstring(self.zin.read(name), parser)
        return self.trees[name]

    def save(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as zout:
            for info in self.infos:
                n = info.filename
                if n in self.raw:
                    data = self.raw[n]
                elif n in self.trees:
                    root = self.trees[n]
                    data = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                else:
                    data = self.zin.read(n)
                zi = zipfile.ZipInfo(n, date_time=info.date_time)
                zi.compress_type = info.compress_type
                zi.external_attr = info.external_attr
                zout.writestr(zi, data)
        return out.getvalue()


def _nearest_para(el):
    p = el.getparent()
    while p is not None and p.tag not in PARA_TEXT:
        p = p.getparent()
    return p


def _para_nodes(para):
    """Куски текста абзаца, разбитые на группы по переносам строк и табуляциям."""
    tags = PARA_TEXT[para.tag]
    groups = [[]]
    for t in para.iter(*tags, *BREAK_TAGS):
        if _nearest_para(t) is not para:
            continue
        if t.tag in BREAK_TAGS:
            if groups[-1]:
                groups.append([])
        elif t.getparent().tag != S_RPH:
            groups[-1].append(t)
    return [g for g in groups if g]


def _redistribute(texts, spans):
    """Разложить замены по кускам исходного текста."""
    bounds, pos = [], 0
    for t in texts:
        bounds.append((pos, pos + len(t)))
        pos += len(t)
    full = ''.join(texts)
    res = [[] for _ in texts]

    def copy(x, y):
        for j, (a, b) in enumerate(bounds):
            s, e = max(x, a), min(y, b)
            if s < e:
                res[j].append(full[s:e])

    def owner(p):
        for j, (a, b) in enumerate(bounds):
            if a <= p < b:
                return j
        return len(texts) - 1

    cur = 0
    for s, e, new, _, _ in spans:
        copy(cur, s)
        res[owner(s)].append(new)
        cur = e
    copy(cur, len(full))
    return [''.join(r) for r in res]


def _set_text(node, text):
    node.text = text
    if text != text.strip():
        node.set(XML_SPACE, 'preserve')


# --- обход -----------------------------------------------------------------

def iter_paragraphs(root):
    for para in root.iter(*PARA_TAGS):
        for nodes in _para_nodes(para):
            yield para, nodes


def _shared_strings(pkg):
    name = 'xl/sharedStrings.xml'
    if name not in pkg.names:
        return [], []
    root = pkg.tree(name)
    items = root.findall(q(NS_S, 'si'))
    return [''.join(n.text or '' for g in _para_nodes(si) for n in g) for si in items], items


def _col(ref):
    m = re.match(r'[A-Z]+', ref or '')
    return m.group() if m else ''


def _cell_value(c, ss):
    t = c.get('t')
    v = c.find(q(NS_S, 'v'))
    if t == 's':
        try:
            return ss[int(v.text)]
        except (TypeError, ValueError, IndexError, AttributeError):
            return None
    if t == 'inlineStr':
        is_ = c.find(q(NS_S, 'is'))
        return ''.join(n.text or '' for g in _para_nodes(is_) for n in g) if is_ is not None else None
    return v.text if v is not None else None


def _sheet_names(pkg):
    return [n for n in pkg.names if re.match(r'xl/worksheets/sheet\d+\.xml$', n)]


def sheet_kinds(pkg, sheet, ss):
    """{буква столбца: тип} по строке заголовков (первая из 10 строк, где узнан хоть один столбец)."""
    root = pkg.tree(sheet)
    rows = root.iter(q(NS_S, 'row'))
    for i, row in enumerate(rows):
        if i >= 10:
            break
        cells = [(_col(c.get('r')), _cell_value(c, ss)) for c in row.findall(q(NS_S, 'c'))]
        filled = [(col, v) for col, v in cells if v not in (None, '')]
        if len(filled) < 2:
            continue
        kinds = {col: detect.kind_by_header(v) for col, v in filled if isinstance(v, str)}
        kinds = {c: k for c, k in kinds.items() if k}
        if kinds:
            return kinds, int(row.get('r') or i + 1)
    return {}, 0


def _num_text(v):
    if v is None:
        return None
    v = v.strip()
    if re.fullmatch(r'\d+(\.0+)?', v):
        return v.split('.')[0]
    if re.fullmatch(r'\d(\.\d+)?[eE]\+\d+', v):
        f = float(v)
        if f.is_integer():
            return str(int(f))
    return None


# --- обучение (поиск новых сущностей) ----------------------------------------

def learn_package(data, reg, use_ner=True):
    pkg = Package(data)
    for name in pkg.xml_parts():
        root = pkg.tree(name)
        for para, nodes in iter_paragraphs(root):
            learn(''.join(n.text or '' for n in nodes), reg, use_ner)
    if pkg.kind == 'xlsx':
        ss, _ = _shared_strings(pkg)
        for sheet in _sheet_names(pkg):
            kinds, head = sheet_kinds(pkg, sheet, ss)
            if not kinds:
                continue
            for row in pkg.tree(sheet).iter(q(NS_S, 'row')):
                if int(row.get('r') or 0) <= head:
                    continue
                for c in row.findall(q(NS_S, 'c')):
                    k = kinds.get(_col(c.get('r')))
                    if k in ('person', 'org'):
                        v = _cell_value(c, ss)
                        if isinstance(v, str):
                            learn_cell(k, v, reg)
    for n in pkg.names:
        if n.lower().endswith(OOXML_EXT) and '/embeddings/' in n:
            learn_package(pkg.zin.read(n), reg, use_ner)


def texts_of(data):
    """Все тексты и атрибуты пакета — для проверки."""
    pkg = Package(data)
    out = []
    for name in pkg.xml_parts():
        root = pkg.tree(name)
        seen = set()
        for para, nodes in iter_paragraphs(root):
            out.append(''.join(n.text or '' for n in nodes))
            seen.update(nodes)
        for el in root.iter():
            if el in seen or not isinstance(el.tag, str):
                continue
            if el.text and el.text.strip():
                out.append(el.text)
            for k, v in el.attrib.items():
                if local(k) not in SKIP_ATTRS and re.search(r'[^\W_]{3}', v):
                    out.append(v)
    for n in pkg.names:
        if n.lower().endswith(OOXML_EXT) and '/embeddings/' in n:
            out += texts_of(pkg.zin.read(n))
    return out


# --- преобразование ----------------------------------------------------------

def convert_package(data, reg, direction, stats, warnings):
    pkg = Package(data)
    handled = set()

    def proc_nodes(nodes, hints=None):
        texts = [n.text or '' for n in nodes]
        full = ''.join(texts)
        if not full.strip():
            return
        spans = find_spans(full, reg, direction, hints)
        if spans:
            for _, _, new, typ, old in spans:
                stats.add(typ, old, new)
            for n, t in zip(nodes, _redistribute(texts, spans)):
                _set_text(n, t)

    # 1. таблицы: числа и ячейки по типу столбца
    if pkg.kind == 'xlsx':
        _convert_sheets(pkg, reg, direction, stats, handled)

    # 2. абзацы
    for name in pkg.xml_parts():
        root = pkg.tree(name)
        for para, nodes in iter_paragraphs(root):
            if any(n in handled for n in nodes):
                continue
            proc_nodes(nodes)
            handled.update(nodes)

    # 3. всё остальное: текстовые узлы и атрибуты
    for name in pkg.xml_parts():
        root = pkg.tree(name)
        is_comment_authors = name.endswith(('commentAuthors.xml', 'people.xml')) or '/persons/' in name
        is_core = name == 'docProps/core.xml'
        is_app = name == 'docProps/app.xml'
        for el in root.iter():
            if not isinstance(el.tag, str) or el in handled:
                continue
            ln = local(el.tag)
            if direction == FWD:
                if is_core and ln in ('creator', 'lastModifiedBy'):
                    el.text = 'shirma'
                    continue
                if is_app and ln in ('Company', 'Manager'):
                    el.text = ''
                    continue
                if ln == 'author' and el.getparent() is not None and local(el.getparent().tag) == 'authors':
                    el.text = 'Автор'
                    continue
            if el.text and el.text.strip():
                el.text = process(el.text, reg, direction, stats)
            for k, v in list(el.attrib.items()):
                lk = local(k)
                if direction == FWD and (lk in AUTHOR_ATTRS or (is_comment_authors and lk == 'name')):
                    el.set(k, AUTHOR_ATTRS.get(lk, 'Автор'))
                    continue
                if lk in SKIP_ATTRS or not re.search(r'[^\W_]{2}', v):
                    continue
                new = process(v, reg, direction, stats, numbers=(lk == 'v'))
                if new != v:
                    el.set(k, new)

    # 4. названия листов не длиннее 31 символа
    if pkg.kind == 'xlsx' and 'xl/workbook.xml' in pkg.names:
        for sh in pkg.tree('xl/workbook.xml').iter(q(NS_S, 'sheet')):
            n = sh.get('name') or ''
            if len(n) > MAX_SHEET_NAME:
                sh.set('name', n[:MAX_SHEET_NAME])
                warnings.append('Название листа после замены длиннее 31 символа и обрезано — '
                                'формулы со ссылкой на этот лист могут сломаться.')

    # 5. вложенные документы и картинки
    for n in pkg.names:
        low = n.lower()
        if '/embeddings/' in low:
            if low.endswith(OOXML_EXT):
                pkg.raw[n] = convert_package(pkg.zin.read(n), reg, direction, stats, warnings)
            else:
                warnings.append(f'Внутри есть встроенный объект ({low.rsplit(".", 1)[-1]}) — '
                                f'он не обработан, проверьте вручную.')
        elif '/media/' in low and low.endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff', '.emf', '.wmf')):
            pkg.images += 1
    if pkg.images and direction == FWD:
        warnings.append(f'Внутри {pkg.images} картинок — текст на картинках не обезличивается, '
                        f'проверьте их вручную.')
    return pkg.save()


def _convert_sheets(pkg, reg, direction, stats, handled):
    ss, ss_items = _shared_strings(pkg)
    for sheet in _sheet_names(pkg):
        kinds, head = sheet_kinds(pkg, sheet, ss)
        root = pkg.tree(sheet)
        for row in root.iter(q(NS_S, 'row')):
            r = int(row.get('r') or 0)
            for c in row.findall(q(NS_S, 'c')):
                hint = kinds.get(_col(c.get('r'))) if r > head else None
                t = c.get('t')
                v = c.find(q(NS_S, 'v'))
                if t in (None, 'n') and v is not None:
                    digits = _num_text(v.text)
                    # без подсказки столбца трогаем только валидные ИИН/БИН: суммы не должны пострадать
                    if digits and (hint in ('iin', 'bin', 'phone', 'inn', 'iban')
                                   or (len(digits) == 12 and fakes.kz_valid(digits))):
                        new = process(digits, reg, direction, stats, hints=hint)
                        if new != digits and re.fullmatch(r'\d+', new):
                            v.text = str(int(new))
                        elif new != digits and c.find(q(NS_S, 'f')) is None:
                            _to_inline(c, v, new)
                    if v is not None:
                        handled.add(v)
                elif t == 's' and hint in ('iin', 'bin', 'phone') and v is not None:
                    try:
                        s = ss[int(v.text)]
                    except (TypeError, ValueError, IndexError):
                        continue
                    plain = process(s, reg, direction, None)
                    hinted = process(s, reg, direction, stats, hints=hint)
                    if hinted != plain:
                        _to_inline(c, v, hinted)


def _to_inline(c, v, text):
    c.remove(v)
    c.set('t', 'inlineStr')
    is_ = etree.SubElement(c, q(NS_S, 'is'))
    t = etree.SubElement(is_, q(NS_S, 't'))
    _set_text(t, text)
