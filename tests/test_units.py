import re

import pytest

from shirma import detect, fakes, morph
from shirma.formats.ooxml import _redistribute
from shirma.hook import check
from shirma.registry import Registry
from shirma.replace import FWD, REV, learn, process


@pytest.fixture
def reg(tmp_path):
    return Registry(str(tmp_path / 'z.sqlite'))


def roundtrip(reg, text):
    learn(text, reg)
    out = process(text, reg, FWD)
    assert process(out, reg, REV) == text
    return out


@pytest.mark.parametrize('text', [
    'Договор с Ивановым Иваном Ивановичем',
    'Подписал Иванов И.И., копия И. И. Иванову',
    'ИВАНОВ ИВАН ИВАНОВИЧ',
    'Директор Нұрлан Сәрсенбаев',
    'Жанна Серікқызы Омарова',
    'Айгерим Сеитова звонила',
    'Вишневской Марией Сергеевной',
])
def test_people_replaced(reg, text):
    out = roundtrip(reg, text)
    for w in text.split():
        if w[0].isupper() and len(w) > 3 and w not in ('Договор', 'Подписал', 'Директор'):
            assert w not in out, (w, out)


def test_script_collision_bug_fixed(reg):
    # в obezl.py получалось «Ромашка-02-01»: фейк содержал настоящее название
    out = roundtrip(reg, 'ТОО «Ақжол» и ТОО «Ромашка»')
    assert 'Ромашка' not in out and 'Ақжол' not in out


def test_same_person_one_fake(reg):
    learn('Иванов Иван Иванович', reg)
    learn('Иванову И.И.', reg)
    assert len(reg.persons) == 1


def test_numbers_keep_format(reg):
    out = roundtrip(reg, 'тел. +7 (701) 123-45-67, 8 701 123 45 67')
    a, b = out.split(', ')
    assert re.sub(r'\D', '', a)[-10:] == re.sub(r'\D', '', b)[-10:]
    assert a.startswith('тел. +7 (701) ')


def test_iin_fake_valid():
    rng = fakes.rng_for('s', 'x')
    f = fakes.fake_iin(rng, '850315300128')
    assert fakes.kz_valid(f) and fakes.classify12(f) == 'iin' and f[6] == '3'


def test_format_like_lost_zero():
    assert fakes.format_like('51212650159', '061229646782') == '61229646782'


def test_redistribute_keeps_runs():
    texts = ['Договор с Ив', 'ановым', ' ok']
    full = ''.join(texts)
    s = full.index('Ив')
    e = s + len('Ивановым')
    assert _redistribute(texts, [(s, e, 'Петровым', 'form', '')]) == ['Договор с Петровым', '', ' ok']


def test_declension():
    assert morph.decline_surname('Иванова', 'f')[4] == 'Ивановой'
    assert morph.decline_name('Юрий', 'm')[5] == 'Юрии'
    assert morph.make_patr('Сергей', 'f') == 'Сергеевна'


def test_hook_blocks_safe(tmp_path):
    root = str(tmp_path)
    safe = str(tmp_path / 'Сейф')
    cwd = str(tmp_path / 'Claude')
    py = '/x/python'
    assert check({'tool_name': 'Read', 'tool_input': {'file_path': '../Сейф/Оригиналы/a.docx'}, 'cwd': cwd},
                 safe, root, py)
    assert check({'tool_name': 'Bash', 'tool_input': {'command': 'ls ..'}, 'cwd': cwd}, safe, root, py)
    assert check({'tool_name': 'Grep', 'tool_input': {'pattern': 'x', 'path': root}, 'cwd': cwd}, safe, root, py)
    assert check({'tool_name': 'Read', 'tool_input': {'file_path': 'Копии/a.docx'}, 'cwd': cwd},
                 safe, root, py) is None
    ok = f'"{py}" -m shirma vernut --root "{root}"'
    assert check({'tool_name': 'Bash', 'tool_input': {'command': ok}, 'cwd': cwd}, safe, root, py) is None
    assert check({'tool_name': 'Bash', 'tool_input': {'command': ok + ' && cat ../Сейф/x'}, 'cwd': cwd},
                 safe, root, py)




def test_check_ignores_iin_without_leading_zero(reg):
    from shirma.replace import scan_leftovers
    fake = reg.num('iin', '051212650159')
    reg.nums_rev['iin']['070107676995'] = 'x'
    assert not scan_leftovers('70107676995', reg, use_ner=False)
    assert fake
