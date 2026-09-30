"""Команды: init, obezlichit, proverit, vernut.

В консоль печатаются только количества — никаких значений. Подробности — в отчёте в Сейфе.
"""
import argparse
import hashlib
import os
import pathlib
import shutil
import sys
import webbrowser
import zipfile
from collections import Counter

from . import detect, formats
from .registry import Registry, TYPE_NAMES
from .replace import FWD, REV, Stats, fake_stems, learn, process, scan_leftovers
from .report import Report
from .workspace import Workspace, walk_files


def _out(msg=''):
    print(msg, flush=True)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _registry(ws):
    reg = Registry(ws.db, stoplist=ws.dict_lines('стоп-лист.txt'))
    for line in ws.dict_lines('компании.txt'):
        reg.add_org(detect.strip_org(line))
    for line in ws.dict_lines('люди.txt'):
        reg.add_person(detect.parse_person(line, from_column=True))
    return reg


def _map_path(rel, reg, direction, stats=None):
    parts = rel.replace('\\', '/').split('/')
    out = []
    for i, part in enumerate(parts):
        if i == len(parts) - 1:
            base, ext = os.path.splitext(part)
            out.append(process(base, reg, direction, stats) + ext)
        else:
            out.append(process(part, reg, direction, stats))
    return os.path.join(*out)


def _write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


def _error_text(e):
    if isinstance(e, PermissionError):
        return 'файл открыт в другой программе (Word/Excel) — закройте его'
    if isinstance(e, zipfile.BadZipFile):
        return 'файл повреждён или защищён паролем'
    if isinstance(e, formats.Unsupported):
        return 'формат не поддерживается'
    return f'ошибка обработки ({type(e).__name__})'


def _kinds_line(counter):
    names = dict(TYPE_NAMES, form='имена и организации', exact='ячейки целиком')
    return ', '.join(f'{names.get(k, k).lower()} {v}' for k, v in sorted(counter.items()))


def _open_report(path, do_open):
    if do_open:
        webbrowser.open(pathlib.Path(path).as_uri())


# --- обезличить ----------------------------------------------------------------

def cmd_obezlichit(ws, args):
    for d in ws.dirs():
        os.makedirs(d, exist_ok=True)
    reg = _registry(ws)
    use_ner = not args.no_ner
    rep = Report('Обезличивание', ws)
    files = walk_files(ws.orig)
    bad, todo, old = [], [], []
    for rel in files:
        if formats.ext_of(rel) not in formats.IN_FORMATS:
            bad.append((rel, formats.Unsupported(formats.ext_of(rel))))
            continue
        rec = reg.file_record(FWD, rel)
        try:
            data = _read(os.path.join(ws.orig, rel))
        except Exception as e:
            bad.append((rel, e))
            continue
        sha = _sha(data)
        if rec and rec[0] == sha and rec[1] and os.path.exists(os.path.join(ws.copies, rec[1])):
            old.append((rel, data, rec))
        else:
            todo.append((rel, data, rec))

    # фаза 1: поиск людей и организаций во всех новых файлах
    learned_ok = []
    for rel, data, rec in todo:
        try:
            formats.learn(data, rel, reg, use_ner)
            for part in rel.replace('\\', '/').split('/'):
                learn(os.path.splitext(part)[0], reg, use_ner)
            learned_ok.append((rel, data, rec))
        except Exception as e:
            bad.append((rel, e))

    # старые файлы: переделать, если в них встречаются сущности, узнанные только что
    new_ents = reg.entities_since(reg.run - 1)
    redo = []
    if new_ents:
        needles = set()
        for e in new_ents:
            needles.add(e.orig['sur'][:max(4, len(e.orig['sur']) - 2)] if 'sur' in e.orig else e.orig['name'])
        for rel, data, rec in old:
            try:
                blob = ' '.join(formats.texts(data, rel)) + ' ' + rel
            except Exception:
                continue
            if any(n in blob for n in needles):
                redo.append((rel, data, rec))

    # фаза 2: замена
    total = Stats()
    done = 0
    for rel, data, rec in learned_ok + redo:
        st, warns = Stats(), []
        try:
            out = formats.convert(data, rel, reg, FWD, st, warns)
            out_rel = _map_path(rel, reg, FWD, st)
            dst = os.path.join(ws.copies, out_rel)
            if rec and rec[1] and rec[1] != out_rel:
                try:
                    os.remove(os.path.join(ws.copies, rec[1]))
                except OSError:
                    pass
            _write_atomic(dst, out)
            reg.save_file(FWD, rel, _sha(data), out_rel)
            reg.commit()
            done += 1
            total.merge(st)
            rep.add_file(rel, out_rel, st, warns)
        except Exception as e:
            bad.append((rel, e))
    reg.commit()
    reg.export_csv(ws.csv)

    for rel, e in bad:
        rep.add_file(rel, None, None, error=_error_text(e))
    for kind, text in reg.warnings:
        rep.add_summary(f'{kind}: {text}', 'warn')
    rep.add_summary(f'Обезличено файлов: {done} (из них повторно: {len(redo)}), без изменений: '
                    f'{len(old) - len(redo)}, с ошибками: {len(bad)}.', 'bad' if bad else 'ok')
    path = rep.save()

    _out(f'Обезличено файлов: {done}. Замен: {total.total}' +
         (f' ({_kinds_line(total.by_type)}).' if total.total else '.'))
    if redo:
        _out(f'Повторно обезличено старых файлов (в них нашлись данные, узнанные сейчас): {len(redo)}.')
    if old and not redo:
        _out(f'Без изменений (уже обезличены): {len(old)}.')
    if reg.warnings:
        _out(f'Предупреждений: {len(reg.warnings)} — см. отчёт.')
    if bad:
        reasons = Counter(_error_text(e) for _, e in bad)
        _out(f'ОШИБКА: {len(bad)} файл(ов) НЕ обезличено: ' +
             '; '.join(f'{r} — {n}' for r, n in reasons.items()) + '. Эти файлы в «Копии» не попали.')
    _out('Отчёт — в Сейф/Отчёты. Перед работой с новыми файлами запустите проверку.')
    _open_report(path, args.open)
    return 2 if bad else 0


# --- проверить ------------------------------------------------------------------

def cmd_proverit(ws, args):
    reg = _registry(ws)
    rep = Report('Проверка копий', ws)
    found = Counter()
    files = 0
    bad = []
    for rel in walk_files(ws.copies):
        st = Stats()
        try:
            texts = [rel] + formats.texts(_read(os.path.join(ws.copies, rel)), rel)
        except Exception as e:
            bad.append(rel)
            rep.add_file(rel, None, None, error=_error_text(e))
            continue
        files += 1
        for t in texts:
            for cat, val in scan_leftovers(t, reg, use_ner=not args.no_ner):
                st.suspicious[(cat, val)] += 1
                found[cat] += 1
        if st.suspicious:
            rep.add_file(rel, None, st)
    rep.add_summary(f'Проверено файлов: {files}. Подозрительных мест: {sum(found.values())}.',
                    'bad' if found else 'ok')
    path = rep.save()
    if found:
        _out(f'Проверено файлов: {files}. НАЙДЕНО: ' + ', '.join(f'{k} — {v}' for k, v in found.items()) +
             '. Эти копии Claude пока не давать: посмотрите отчёт в Сейф/Отчёты, '
             'добавьте пропущенное в Словари (или ложное — в стоп-лист) и обезличьте заново.')
        _open_report(path, args.open)
        return 1
    _out(f'Проверено файлов: {files}. Подозрительного не найдено. Перед работой всё равно пролистайте копию глазами.')
    if bad:
        _out(f'Не удалось прочитать: {len(bad)}.')
    _open_report(path, args.open)
    return 0


# --- вернуть ----------------------------------------------------------------------

def cmd_vernut(ws, args):
    os.makedirs(ws.result, exist_ok=True)
    reg = _registry(ws)
    rep = Report('Восстановление', ws)
    stems = fake_stems(reg)
    done, copied, left, bad = 0, 0, Counter(), []
    total = Stats()
    for rel in walk_files(ws.claude_out):
        src = os.path.join(ws.claude_out, rel)
        st, warns = Stats(), []
        out_rel = _map_path(rel, reg, REV, st)
        dst = os.path.join(ws.result, out_rel)
        ext = formats.ext_of(rel)
        try:
            data = _read(src)
            if ext in formats.OUT_FORMATS:
                out = formats.convert(data, rel, reg, REV, st, warns)
                _write_atomic(dst, out)
                done += 1
                texts = formats.texts(out, rel) + [out_rel]
                for t in texts:
                    for stem in stems:
                        if stem.lower() in t.lower():
                            st.suspicious[('возможно, не восстановлено', stem)] += t.lower().count(stem.lower())
                            left['возможно, не восстановлено'] += 1
                total.merge(st)
                rep.add_file(rel, out_rel, st, warns)
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
                copied += 1
                why = ('PDF нельзя восстановить — попросите Claude сохранить результат в docx или md'
                       if ext == '.pdf' else 'формат не обрабатывается — скопирован без изменений')
                rep.add_file(rel, out_rel, None, [why])
        except Exception as e:
            bad.append(rel)
            rep.add_file(rel, None, None, error=_error_text(e))
    rep.add_summary(f'Восстановлено файлов: {done}, скопировано без обработки: {copied}, ошибок: {len(bad)}.',
                    'bad' if bad else 'ok')
    path = rep.save()
    _out(f'Восстановлено файлов: {done}. Замен: {total.total}.')
    if copied:
        _out(f'Скопировано без обработки (PDF, картинки и т.п.): {copied} — проверьте их вручную.')
    if left:
        _out(f'Возможно, не восстановлено мест: {sum(left.values())} — см. отчёт в Сейф/Отчёты.')
    if bad:
        _out(f'ОШИБКА: {len(bad)} файл(ов) не обработано — см. отчёт.')
    _out('Готовые файлы — в Сейф/Результат, открывайте их сами.')
    _open_report(path, args.open)
    return 2 if bad else 0


# --- init ---------------------------------------------------------------------------

def cmd_init(ws, args):
    from .setup import init_workspace
    init_workspace(ws)
    _out(f'Рабочая папка готова: {ws.root}')
    _out('Кладите файлы в Сейф/Оригиналы и запускайте «Обезличить». Claude Code открывайте в папке Claude.')
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    p = argparse.ArgumentParser(prog='shirma', description='Обезличивание документов для работы с Claude')
    p.add_argument('command', choices=['init', 'obezlichit', 'proverit', 'vernut'])
    p.add_argument('path', nargs='?', help='рабочая папка (для init)')
    p.add_argument('--root', help='рабочая папка (где лежат Сейф и Claude)')
    p.add_argument('--open', action='store_true', help='открыть отчёт в браузере')
    p.add_argument('--no-ner', action='store_true', help='не использовать NER (быстрее, но хуже находит имена)')
    args = p.parse_args(argv)
    if args.command == 'init':
        ws = Workspace(args.path or args.root or os.getcwd())
    else:
        ws = Workspace(args.root) if args.root else Workspace.find()
        if ws is None or not os.path.isdir(ws.safe):
            _out('ОШИБКА: не найдена рабочая папка (рядом должны лежать папки «Сейф» и «Claude»). '
                 'Создайте её командой: shirma init <папка>')
            return 2
    cmd = {'init': cmd_init, 'obezlichit': cmd_obezlichit, 'proverit': cmd_proverit, 'vernut': cmd_vernut}
    return cmd[args.command](ws, args)


if __name__ == '__main__':
    sys.exit(main())
