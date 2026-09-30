"""Пулы фейков: редкие, без дублей, склоняются предсказуемо."""
import pytest

from shirma import morph, pools

ALL_POOLS = {k: v for k, v in vars(pools).items() if k.isupper() and isinstance(v, list)}


@pytest.mark.parametrize('name', sorted(ALL_POOLS))
def test_no_duplicates(name):
    pool = ALL_POOLS[name]
    assert len(pool) == len(set(pool)), [x for x in pool if pool.count(x) > 1]


def test_sizes():
    assert len(pools.SURNAMES_OV_RU) >= 100 and len(pools.SURNAMES_OV_KZ) >= 50
    assert len(pools.ORG_NAMES) >= 100


def test_surname_classes():
    for s in pools.SURNAMES_OV_RU + pools.SURNAMES_OV_KZ:
        assert morph.surname_class(s, 'm') == 'ov', s
        assert morph.surname_class(s + 'а', 'f') == 'ov', s
    for s in pools.SURNAMES_ADJ:
        assert morph.surname_class(s, 'm') == 'adj', s
    for s in pools.SURNAMES_INDECL:
        assert morph.surname_class(s, 'm') == 'indecl', s
    for s in pools.SURNAMES_CONS:
        assert morph.surname_class(s, 'm') == 'cons', s


def test_names_decline_as_expected():
    for n in pools.NAMES_F_RU + pools.NAMES_F_KZ:
        assert not n.endswith('ь'), n
    for f in pools.FATHERS_RU + pools.FATHERS_KZ:
        assert f[-1] not in 'аяоеиуыэю', f
        assert morph.make_patr(f, 'm').endswith('ич') and morph.make_patr(f, 'f').endswith('на')


def test_pools_disjoint():
    names = set(pools.NAMES_M_RU + pools.NAMES_F_RU + pools.NAMES_M_KZ + pools.NAMES_F_KZ)
    surnames = set(pools.SURNAMES_OV_RU + pools.SURNAMES_OV_KZ + pools.SURNAMES_ADJ +
                   pools.SURNAMES_INDECL + pools.SURNAMES_CONS)
    assert not names & surnames
    assert not set(pools.ORG_NAMES) & (names | surnames)
