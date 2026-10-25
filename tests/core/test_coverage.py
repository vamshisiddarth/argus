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
        "discovery_complete",
        "stop_reason",
        "skipped_by_reason",
        "free_config_skipped",
        "metrics_lost_to_throttling",
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


def test_discovery_complete_defaults_to_unknown_and_serialises():
    cov = _cov()
    assert cov.discovery_complete is None
    assert cov.to_dict()["discovery_complete"] is None
    cov.discovery_complete = False
    assert Coverage.from_dict(cov.to_dict()).discovery_complete is False


def test_merge_discovery_complete_is_false_if_any_false_true_only_if_all_true():
    def with_flag(flag):
        c = _cov()
        c.discovery_complete = flag
        return c

    merged = Coverage.merge([with_flag(True), with_flag(False)])
    assert merged.discovery_complete is False
    assert Coverage.merge([with_flag(True), with_flag(True)]).discovery_complete is True
    assert Coverage.merge([with_flag(True), with_flag(None)]).discovery_complete is None


def test_skip_reasons_round_trip_and_merge():
    a = _cov(10, 6)
    a.stop_reason = "budget"
    a.skipped_by_reason = {"budget": 4}
    b = _cov(5, 3)
    b.skipped_by_reason = {"budget": 1, "llm_failure": 1}

    assert Coverage.from_dict(a.to_dict()).skipped_by_reason == {"budget": 4}
    merged = Coverage.merge([a, b])
    assert merged.skipped_by_reason == {"budget": 5, "llm_failure": 1}
    assert merged.stop_reason == "budget"


def test_free_config_count_round_trips_and_merges():
    a = _cov(10, 10)
    a.free_config_skipped = 70
    b = _cov(5, 5)
    b.free_config_skipped = 7

    assert Coverage.from_dict(a.to_dict()).free_config_skipped == 70
    assert Coverage.merge([a, b]).free_config_skipped == 77
    assert Coverage.empty().free_config_skipped == 0


def test_metrics_lost_to_throttling_defaults_to_zero_and_round_trips():
    assert _cov().metrics_lost_to_throttling == 0
    cov = _cov(metrics_lost_to_throttling=4)
    assert Coverage.from_dict(cov.to_dict()).metrics_lost_to_throttling == 4


def test_merge_sums_metrics_lost_to_throttling():
    merged = Coverage.merge(
        [_cov(metrics_lost_to_throttling=2), _cov(metrics_lost_to_throttling=3)]
    )
    assert merged.metrics_lost_to_throttling == 5
