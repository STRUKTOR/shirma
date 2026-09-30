"""Пулы фейков: испанский манер, без дублей, склоняются предсказуемо."""
import pytest

from shirma import morph, pools

ALL_POOLS = {k: v for k, v in vars(pools).items() if k.isupper() and isinstance(v, list)}


@pytest.mark.parametrize('name', sorted(ALL_POOLS))
def test_no_duplicates(name):
    pool = ALL_POOLS[name]
    assert len(pool) == len(set(pool)), [x for x in pool if pool.count(x) > 1]


def test_sizes():
    assert len(pools.SURNAMES) >= 80
    assert len(pools.NAMES_M) >= 30 and len(pools.NAMES_F) >= 30
    assert len(pools.ORG_NAMES) >= 100


def test_spanish_surnames():
    for s in pools.SURNAMES:
        assert s.endswith(('ес', 'ас', 'ис', 'ос', 'ус')), s
        # мужские склоняются как «Иванов» (6 форм), женские не склоняются
        assert morph.surname_class(s, 'm') == 'cons', s
        assert len(set(morph.decline_surname(s, 'm'))) == 5, s   # вин. = род.
        assert len(set(morph.decline_surname(s, 'f'))) == 1, s


def test_names_decline_as_expected():
    for n in pools.NAMES_F:
        assert not n.endswith('ь'), n
    for f in pools.FATHERS:
        assert f[-1] not in 'аяоеиуыэю', f
        assert morph.make_patr(f, 'm').endswith('ич') and morph.make_patr(f, 'f').endswith('на')
    # есть и склоняемые, и несклоняемые имена — чтобы сохранять падеж (Айгерим ↔ Мерседес)
    for pool, g in ((pools.NAMES_M, 'm'), (pools.NAMES_F, 'f')):
        indecl = [n for n in pool if len(set(morph.decline_name(n, g))) == 1]
        assert 5 <= len(indecl) < len(pool) - 5


def test_pools_disjoint():
    names = set(pools.NAMES_M + pools.NAMES_F)
    assert not names & set(pools.SURNAMES)
    assert not set(pools.ORG_NAMES) & (names | set(pools.SURNAMES))
