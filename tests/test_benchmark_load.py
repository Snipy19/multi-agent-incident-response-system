import pytest

from scripts.benchmark_load import BenchmarkError, _parse_targets


def test_benchmark_targets_are_bounded_and_deduplicated():
    assert _parse_targets("1,10,10,100") == [1, 10, 100]


@pytest.mark.parametrize("value", ["0", "101", "abc", ""])
def test_benchmark_targets_reject_invalid_values(value):
    with pytest.raises(BenchmarkError):
        _parse_targets(value)
