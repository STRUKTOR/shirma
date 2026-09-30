"""Текстовые файлы: txt, md, csv и прочий текст (для результатов Claude)."""
import csv
import io
import re

from .. import detect
from ..replace import learn, learn_cell, process

TEXT_EXT = ('.txt', '.md', '.csv', '.tsv')
# результаты Claude могут быть в любом текстовом формате
TEXT_EXT_OUT = TEXT_EXT + ('.json', '.html', '.htm', '.xml', '.yaml', '.yml', '.rtf', '.tex', '.log',
                           '.py', '.js', '.sql', '.ini', '.toml', '.eml', '.srt', '.vtt')


class NotText(Exception):
    pass


def decode(data):
    if data.startswith(b'\xef\xbb\xbf'):
        return data[3:].decode('utf-8'), 'utf-8-sig'
    try:
        return data.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        pass
    if b'\x00' in data[:4096]:
        raise NotText()
    return data.decode('cp1251'), 'cp1251'


def encode(text, enc):
    return text.encode(enc, errors='replace') if enc == 'cp1251' else text.encode(enc)


def _csv_dialect(text, ext):
    if ext == '.tsv':
        return '\t'
    try:
        return csv.Sniffer().sniff(text[:20000], delimiters=',;\t|').delimiter
    except csv.Error:
        return ';' if text.count(';') > text.count(',') else ','


def _csv_rows(text, ext):
    delim = _csv_dialect(text, ext)
    return list(csv.reader(io.StringIO(text, newline=''), delimiter=delim)), delim


def csv_kinds(rows):
    for i, row in enumerate(rows[:10]):
        filled = [v for v in row if v.strip()]
        if len(filled) < 2:
            continue
        kinds = {j: detect.kind_by_header(v) for j, v in enumerate(row)}
        kinds = {j: k for j, k in kinds.items() if k}
        if kinds:
            return kinds, i
    return {}, -1


def learn_file(data, ext, reg, use_ner=True):
    text, _ = decode(data)
    if ext in ('.csv', '.tsv'):
        rows, _ = _csv_rows(text, ext)
        kinds, head = csv_kinds(rows)
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                if i > head and kinds.get(j) in ('person', 'org'):
                    learn_cell(kinds[j], v, reg)
                learn(v, reg, use_ner)
        return
    for para in re.split(r'\n', text):
        learn(para, reg, use_ner)


def convert_file(data, ext, reg, direction, stats):
    text, enc = decode(data)
    if ext in ('.csv', '.tsv'):
        rows, delim = _csv_rows(text, ext)
        kinds, head = csv_kinds(rows)
        eol = '\r\n' if '\r\n' in text else '\n'
        out = io.StringIO()
        w = csv.writer(out, delimiter=delim, lineterminator=eol)
        for i, row in enumerate(rows):
            w.writerow([process(v, reg, direction, stats, hints=kinds.get(j) if i > head else None)
                        for j, v in enumerate(row)])
        return encode(out.getvalue(), enc)
    return encode(process(text, reg, direction, stats), enc)


def texts_of(data):
    text, _ = decode(data)
    return [text]
