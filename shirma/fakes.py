"""Валидаторы реквизитов и генераторы фейков того же вида."""
import datetime as dt
import random
import string

# --- ИИН / БИН (Казахстан) ---------------------------------------------------

_W1 = list(range(1, 12))
_W2 = [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2]


def kz_check_digit(d11):
    """Контрольная цифра ИИН/БИН или None, если номер с такими 11 цифрами не выдаётся."""
    digits = [int(c) for c in d11]
    c = sum(a * b for a, b in zip(digits, _W1)) % 11
    if c == 10:
        c = sum(a * b for a, b in zip(digits, _W2)) % 11
        if c == 10:
            return None
    return c


def kz_valid(num):
    if len(num) != 12 or not num.isdigit():
        return False
    c = kz_check_digit(num[:11])
    return c is not None and c == int(num[11])


def _iin_date(num):
    yy, mm, dd, cg = int(num[0:2]), int(num[2:4]), int(num[4:6]), int(num[6])
    if cg not in (1, 2, 3, 4, 5, 6):
        return None
    century = {1: 1800, 2: 1800, 3: 1900, 4: 1900, 5: 2000, 6: 2000}[cg]
    try:
        return dt.date(century + yy, mm, dd)
    except ValueError:
        return None


def classify12(num):
    """'iin' / 'bin' / 'num12'."""
    if kz_valid(num):
        if _iin_date(num):
            return 'iin'
        if num[4] in '456' and 1 <= int(num[2:4]) <= 12:
            return 'bin'
    return 'num12'


def _with_check(rng, prefix, serial_len):
    for _ in range(1000):
        body = prefix + ''.join(rng.choice(string.digits) for _ in range(serial_len))
        c = kz_check_digit(body)
        if c is not None:
            return body + str(c)
    raise RuntimeError('не удалось сгенерировать номер')


def fake_iin(rng, orig):
    d = _iin_date(orig)
    male = int(orig[6]) % 2 == 1
    if d is None:
        d = dt.date(1985, 1, 1)
    d = d + dt.timedelta(days=rng.choice([-1, 1]) * rng.randint(20, 400))
    cg = {1800: 1, 1900: 3, 2000: 5}.get(d.year // 100 * 100, 3) + (0 if male else 1)
    return _with_check(rng, f'{d:%y%m%d}{cg}', 4)


def fake_bin(rng, orig):
    return _with_check(rng, orig[:6], 5)


def fake_num12(rng, orig):
    if kz_valid(orig):
        return _with_check(rng, orig[:1], 10)
    return orig[:1] + ''.join(rng.choice(string.digits) for _ in range(11))


# --- IBAN --------------------------------------------------------------------

def iban_check(country, bban):
    s = bban + country + '00'
    n = ''.join(str(int(ch, 36)) for ch in s.upper())
    return f'{98 - int(n) % 97:02d}'


def iban_valid(iban):
    iban = iban.upper()
    return len(iban) >= 15 and iban_check(iban[:2], iban[4:]) == iban[2:4]


def fake_iban(rng, orig):
    """KZkk BBB AAAAAAAAAAAAA: банк (3 знака) сохраняется, счёт — случайный того же вида."""
    orig = orig.upper()
    country, bank, acc = orig[:2], orig[4:7], orig[7:]
    new_acc = ''.join(rng.choice(string.digits) if ch.isdigit() else rng.choice(string.ascii_uppercase)
                      for ch in acc)
    bban = bank + new_acc
    return country + iban_check(country, bban) + bban


# --- карты -------------------------------------------------------------------

def luhn_valid(num):
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def fake_card(rng, orig):
    body = orig[:6] + ''.join(rng.choice(string.digits) for _ in range(len(orig) - 7))
    for d in string.digits:
        if luhn_valid(body + d):
            return body + d
    raise RuntimeError


# --- прочие номера -----------------------------------------------------------

def fake_phone(rng, orig10):
    """Код оператора/города (3 цифры) сохраняется."""
    return orig10[:3] + ''.join(rng.choice(string.digits) for _ in range(7))


def _inn_ru_check(digits, weights):
    return str(sum(int(a) * b for a, b in zip(digits, weights)) % 11 % 10)


def fake_digits(rng, orig, keep=2):
    """Столько же цифр, первые `keep` сохранены."""
    return orig[:keep] + ''.join(rng.choice(string.digits) for _ in range(len(orig) - keep))


def fake_inn_ru(rng, orig):
    n = len(orig)
    body = orig[:2] + ''.join(rng.choice(string.digits) for _ in range(n - 2))
    if n == 10:
        return body[:9] + _inn_ru_check(body[:9], [2, 4, 10, 3, 5, 9, 4, 6, 8])
    if n == 12:
        b = body[:10]
        b += _inn_ru_check(b, [7, 2, 4, 10, 3, 5, 9, 4, 6, 8])
        b += _inn_ru_check(b, [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8])
        return b
    return body


# --- формат записи -----------------------------------------------------------

def format_like(sample, new_key, alnum=False):
    """Переписать `sample`, заменив последние len(new_key) значимых символов на new_key.

    Разделители, скобки, «+7» и прочее оформление сохраняются.
    """
    is_sig = (lambda c: c.isalnum()) if alnum else (lambda c: c.isdigit())
    positions = [i for i, c in enumerate(sample) if is_sig(c)]
    if len(positions) < len(new_key):
        # Excel потерял ведущий ноль: пишем столько цифр, сколько было
        extra = len(new_key) - len(positions)
        if new_key[:extra].strip('0') == '':
            new_key = new_key[extra:]
        else:
            return new_key
    out = list(sample)
    for pos, ch in zip(positions[len(positions) - len(new_key):], new_key):
        out[pos] = ch
    return ''.join(out)


# --- транслитерация ----------------------------------------------------------

_TR = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'ж': 'zh', 'з': 'z',
    'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh',
    'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'ә': 'a', 'ғ': 'g', 'қ': 'k', 'ң': 'n', 'ө': 'o', 'ұ': 'u', 'ү': 'u', 'һ': 'h', 'і': 'i',
}


def translit(s):
    return ''.join(_TR.get(ch, ch) for ch in s.lower())


def translit_variants(s):
    """Основные варианты транслита фамилии/имени, как их пишут в почте."""
    base = translit(s)
    out = {base}
    out.add(base.replace('kh', 'h'))
    out.add(base.replace('yu', 'iu').replace('ya', 'ia'))
    out.add(base.replace('zh', 'j'))
    out.add(base.replace('ts', 'c'))
    if base.endswith('iy'):
        out.add(base[:-2] + 'y')
        out.add(base[:-2] + 'i')
    return {v for v in out if v}


def rng_for(secret, *parts):
    import hashlib
    import hmac
    h = hmac.new(secret.encode(), '|'.join(map(str, parts)).encode(), hashlib.sha256).digest()
    return random.Random(int.from_bytes(h[:8], 'big'))
