import pytest

from app import scoring

F = scoring.FACTORS


def fac(v):
    return {f: v for f in F}


def test_identical_sites_score_one():
    r = scoring.score_pair(fac(0.4), fac(0.4))
    assert r["score"] == pytest.approx(1.0)


def test_opposite_sites_score_zero():
    r = scoring.score_pair(fac(0.0), fac(1.0))
    assert r["score"] == pytest.approx(0.0)


def test_default_weights_are_equal():
    w = scoring.clean_weights(None)
    assert all(v == pytest.approx(0.2) for v in w.values())


def test_weights_are_normalized_and_change_the_score():
    t = {**fac(0.5), "slope": 0.0}
    c = {**fac(0.5), "slope": 1.0}
    equal = scoring.score_pair(t, c)["score"]
    slope_heavy = scoring.score_pair(t, c, {"slope": 10})["score"]
    assert slope_heavy < equal
    assert sum(scoring.clean_weights({"slope": 10}).values()) == pytest.approx(1.0)


@pytest.mark.parametrize("bad", [{"nope": 1}, {"slope": -1}, {f: 0 for f in F}])
def test_bad_weights_rejected(bad):
    with pytest.raises(ValueError):
        scoring.clean_weights(bad)


def test_rank_sorted_filtered_and_numbered():
    target = {"factors": fac(0.5)}
    cands = [
        {"id": "a", "name": "A", "type": "desert", "lat": 0, "lon": 0, "factors": fac(0.9)},
        {"id": "b", "name": "B", "type": "polar", "lat": 0, "lon": 0, "factors": fac(0.5)},
        {"id": "c", "name": "C", "type": "desert", "lat": 0, "lon": 0, "factors": fac(0.6)},
    ]
    out = scoring.rank(target, cands)
    assert [x["id"] for x in out] == ["b", "c", "a"]
    assert [x["rank"] for x in out] == [1, 2, 3]
    assert [x["id"] for x in scoring.rank(target, cands, types=["desert"])] == ["c", "a"]
    assert len(scoring.rank(target, cands, top_n=1)) == 1
