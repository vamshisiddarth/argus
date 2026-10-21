from core.models.coverage import Coverage, TypeCoverage


def _cov(discovered=880, analysed=200, **kw) -> Coverage:
    defaults = dict(
        selection="cost_desc",
        cost_data_available=True,
        regions_covered=["us-east-1"],
        types={"AWS::EC2::Volume": TypeCoverage(discovered, analysed)},
    )
    defaults.update(kw)
    return Coverage(discovered=discovered, analysed=analysed, **defaults)


def test_dropped_and_truncated_when_cap_bites():
    cov = _cov(880, 200)
    assert cov.dropped == 680
    assert cov.truncated is True


def test_not_truncated_when_everything_analysed():
    cov = _cov(5, 5)
    assert cov.dropped == 0
    assert cov.truncated is False


def test_zero_resources_is_all_zero_and_not_truncated():
    cov = Coverage.empty()
    assert (cov.discovered, cov.analysed, cov.dropped) == (0, 0, 0)
    assert cov.truncated is False
    assert cov.to_dict()["types"] == {}


def test_to_dict_has_documented_keys():
    d = _cov(10, 4).to_dict()
    assert set(d) == {
        "discovered",
        "analysed",
        "dropped",
        "truncated",
        "selection",
        "cost_data_available",
        "regions_covered",
        "types",
    }
    assert d["types"]["AWS::EC2::Volume"] == {"discovered": 10, "analysed": 4}
    assert d["dropped"] == 6 and d["truncated"] is True


def test_merge_sums_counts_unions_regions_merges_types():
    a = _cov(
        10,
        4,
        regions_covered=["us-east-1"],
        types={"T1": TypeCoverage(6, 3), "T2": TypeCoverage(4, 1)},
    )
    b = _cov(
        5,
        5,
        regions_covered=["eu-west-1", "us-east-1"],
        types={"T2": TypeCoverage(5, 5)},
    )

    merged = Coverage.merge([a, b])

    assert (merged.discovered, merged.analysed) == (15, 9)
    assert merged.regions_covered == ["eu-west-1", "us-east-1"]
    assert merged.types["T1"] == TypeCoverage(6, 3)
    assert merged.types["T2"] == TypeCoverage(9, 6)


def test_merge_mixed_selection_rule_and_cost_flag():
    a = _cov(selection="cost_desc", cost_data_available=True)
    b = _cov(selection="stratified_by_type", cost_data_available=False)

    merged = Coverage.merge([a, b])

    assert merged.selection == "mixed"
    assert merged.cost_data_available is False


def test_merge_of_nothing_is_empty():
    assert Coverage.merge([]).discovered == 0


def test_from_dict_round_trips():
    original = _cov(10, 4)
    assert Coverage.from_dict(original.to_dict()).to_dict() == original.to_dict()
