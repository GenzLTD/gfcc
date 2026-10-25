"""identity.value_axes 只读进职位匹配，分数不得装回这个槽。"""

import pytest

from tatha.jobs.value_axes import format_value_axes_prior, read_value_axes


def test_freedom_is_read_as_workload_not_as_a_stored_score():
    axes = read_value_axes({"freedom": 3})
    assert axes == {"freedom": 3}
    text = format_value_axes_prior({"freedom": 3})
    assert "freedom = 3" in text
    assert "事少" in text
    assert "culture_workload_match" in text
    assert "禁止写回身份" in text
    assert "钱多" in text and "未声明" in text


def test_scorecard_is_rejected():
    with pytest.raises(ValueError, match="must not be written"):
        read_value_axes({"survival": 2, "salary_match": 8})


def test_absent_axes_add_no_prior():
    assert read_value_axes(None) is None
    assert format_value_axes_prior(None) == ""
