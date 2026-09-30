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


def test_hook_blocks_private(tmp_path):
    root = str(tmp_path)
    priv = str(tmp_path / 'private')
    cwd = str(tmp_path / 'claude')
    py = '/x/python'

    def chk(tool, inp):
        return check({'tool_name': tool, 'tool_input': inp, 'cwd': cwd}, priv, root, py)

    assert chk('Read', {'file_path': '../private/input/a.docx'})
    assert chk('Read', {'file_path': priv + '/system/mapping.csv'})
    assert chk('Bash', {'command': 'ls ..'})
    assert chk('Bash', {'command': f'cat {root}/private/system/mapping.csv'})
    assert chk('Grep', {'pattern': 'x', 'path': root})
    assert chk('Glob', {'pattern': '../**/*.docx'})
    assert chk('Read', {'file_path': 'input/a.docx'}) is None
    # слово «private» само по себе не повод блокировать (код, системные пути macOS)
    assert chk('Bash', {'command': 'grep -rn "private" input/'}) is None
    assert chk('Write', {'file_path': 'output/x.py', 'content': 'private int x;'}) is None
    ok = f'"{py}" -m shirma restore --root "{root}"'
    assert chk('Bash', {'command': ok}) is None
    assert chk('Bash', {'command': ok + ' && cat ../private/x'})



def test_check_ignores_iin_without_leading_zero(reg):
    from shirma.replace import scan_leftovers
    fake = reg.num('iin', '051212650159')
    reg.nums_rev['iin']['070107676995'] = 'x'
    assert not scan_leftovers('70107676995', reg, use_ner=False)
    assert fake


def test_hook_protects_own_config(tmp_path):
    root = str(tmp_path)
    priv = str(tmp_path / 'private')
    cwd = str(tmp_path / 'claude')
    py = '/x/python'

    def chk(tool, inp):
        return check({'tool_name': tool, 'tool_input': inp, 'cwd': cwd}, priv, root, py)

    for path in ('.claude/settings.json', '.claude/skills/shirma/SKILL.md', 'CLAUDE.md', 'claude.md',
                 '.Claude/settings.json', f'{cwd}/.claude/settings.local.json'):
        assert chk('Edit', {'file_path': path, 'old_string': 'a', 'new_string': 'b'}), path
        assert chk('Write', {'file_path': path, 'content': '{}'}), path
    for cmd in ('echo {} > .claude/settings.json', 'rm -rf .claude', "sed -i '' 's/x//' CLAUDE.md",
                'mv ./.claude/skills x'):
        assert chk('Bash', {'command': cmd}), cmd
    # читать можно; обычная работа не задета
    assert chk('Read', {'file_path': 'CLAUDE.md'}) is None
    assert chk('Read', {'file_path': '.claude/skills/shirma/SKILL.md'}) is None
    assert chk('Write', {'file_path': 'output/claude-notes.md', 'content': 'x'}) is None
    assert chk('Bash', {'command': 'grep -rn claude input/'}) is None


def test_install_init_skill(tmp_path):
    from shirma.cli import main
    assert main(['install-skill', str(tmp_path)]) == 0
    text = (tmp_path / 'shirma-init' / 'SKILL.md').read_text(encoding='utf-8')
    assert text.startswith('---\nname: shirma-init\ndescription: ')
    assert '-m shirma init "<ПАПКА>" --dry-run' in text and '{py}' not in text
    # после создания — перевести сессию в claude/ и проверить, что защита включилась
    assert 'change_directory' in text and '../private/system/README.txt' in text
    assert 'cd "<ПАПКА>/claude" && claude' in text


def test_init_dry_run_and_warnings(tmp_path, monkeypatch):
    from shirma.cli import main
    from shirma.setup import location_warnings
    target = tmp_path / 'Работа'
    assert main(['init', str(target), '--dry-run']) == 0
    assert not target.exists()                 # dry-run ничего не создаёт
    (tmp_path / 'repo' / '.git').mkdir(parents=True)
    assert any('git' in w for w in location_warnings(str(tmp_path / 'repo' / 'ws')))
    assert main(['init', str(tmp_path / 'repo' / 'ws'), '--dry-run']) == 1
    assert any('облач' in w for w in location_warnings(str(tmp_path / 'Dropbox' / 'ws')))
    # iCloud «Документы» на macOS
    home = tmp_path / 'home'
    (home / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs' / 'Documents').mkdir(parents=True)
    monkeypatch.setenv('HOME', str(home))
    assert any('iCloud' in w for w in location_warnings(str(home / 'Documents' / 'ws')))
    assert not location_warnings(str(home / 'Shirma' / 'ws'))
