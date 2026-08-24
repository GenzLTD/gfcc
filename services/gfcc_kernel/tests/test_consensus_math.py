"""consensus_math（合意引擎 W1）单测 —— 自造矩阵，不搬 Pol.is/Loomio 测试向量。

对照调研报告的"已知行为"：空矩阵、全票、小样本、跨组拉垮、代表性。
"""

import pytest

from gfcc_kernel.consensus_math import (
    Z_CRITICAL_90,
    agreement_mass,
    consensus_report,
    cross_group_consensus,
    disagreement_mass,
    is_significant,
    laplace_agreement,
    normalize_votes,
    one_proportion_z,
    representativeness,
    two_proportion_z,
)


class TestNormalizeVotes:
    def test_list_form(self):
        assert normalize_votes([1, 1, 0, -1, 1]) == (3, 1, 1)

    def test_dict_form(self):
        assert normalize_votes({"agree": 3, "disagree": 1}) == (3, 1, 0)

    def test_dict_negative_raises(self):
        with pytest.raises(ValueError):
            normalize_votes({"agree": -1})

    def test_invalid_vote_raises(self):
        with pytest.raises(ValueError):
            normalize_votes([2])


class TestLaplaceAgreement:
    def test_no_information_prior(self):
        # 0 票同意 0 票立场 → (0+1)/(0+2)=0.5，无信息先验
        assert laplace_agreement(0, 0) == pytest.approx(0.5)

    def test_unanimous_small(self):
        assert laplace_agreement(3, 3) == pytest.approx(4 / 5)

    def test_unanimous_large(self):
        assert laplace_agreement(30, 30) == pytest.approx(31 / 32)

    def test_monotonic(self):
        assert laplace_agreement(20, 30) > laplace_agreement(10, 30)

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError):
            laplace_agreement(5, 3)  # agree > seen


class TestProportionZ:
    def test_small_unanimous_not_significant(self):
        # 全票同意仅 3 人：z ≈ 1.04 < 1.6449 → 少数人不能定调
        z = one_proportion_z(4 / 5, 3)
        assert z == pytest.approx(1.0392, abs=1e-3)
        assert not is_significant(z)

    def test_large_unanimous_significant(self):
        z = one_proportion_z(31 / 32, 30)
        assert z > Z_CRITICAL_90
        assert is_significant(z)

    def test_boundary_is_significant(self):
        assert is_significant(Z_CRITICAL_90)  # |z| >= 临界值

    def test_zero_n_raises(self):
        with pytest.raises(ValueError):
            one_proportion_z(0.5, 0)

    def test_p0_boundaries_raise(self):
        with pytest.raises(ValueError):
            one_proportion_z(0.5, 10, p0=0.0)

    def test_two_proportion_equal(self):
        # 组与其余同意率相同 → z ≈ 0
        assert two_proportion_z(0.5, 20, 0.5, 40) == pytest.approx(0.0, abs=1e-9)

    def test_two_proportion_different(self):
        assert two_proportion_z(0.9, 20, 0.4, 40) > Z_CRITICAL_90


class TestAgreementMass:
    def test_strong_agreement(self):
        assert agreement_mass(30, 30) > agreement_mass(10, 30)

    def test_disagreement_mass_symmetric(self):
        # 反对占优时，分歧度高于对侧的同意度（同意侧为负值）
        assert disagreement_mass(25, 30) > agreement_mass(5, 30)


class TestCrossGroupConsensus:
    def test_single_group_equals_laplace(self):
        assert cross_group_consensus([(30, 30)]) == pytest.approx(laplace_agreement(30, 30))

    def test_two_groups_high_agreement(self):
        both = cross_group_consensus([(30, 30), (25, 30)])
        assert both < cross_group_consensus([(30, 30)])
        assert both == pytest.approx((31 / 32) * (26 / 32))

    def test_one_strong_objection_pulls_down(self):
        # 任一组强烈反对（0/20 同意）→ 乘积被拉垮
        low = cross_group_consensus([(30, 30), (0, 20)])
        assert low == pytest.approx((31 / 32) * (1 / 22))
        assert low < 0.1

    def test_empty_groups(self):
        assert cross_group_consensus([]) == 0.0


class TestRepresentativeness:
    def test_group_agree_more_than_rest(self):
        # 本组 90% 同意 vs 其余 40% → 代表性显著为正
        r = representativeness(18, 20, 16, 40)
        assert r > 0

    def test_group_same_as_rest_zero(self):
        # 本组与其余立场一致 → ra≈1 且 z≈0 → repness≈0
        r = representativeness(10, 20, 20, 40)
        assert r == pytest.approx(0.0, abs=0.1)

    def test_rest_no_agreement_returns_zero(self):
        assert representativeness(5, 10, 0, 10) == 0.0


class TestConsensusReport:
    def test_report_shape(self):
        report = consensus_report(
            {
                "growth": [1, 1, 1, 1, 0],
                "mixed": [1, 0, -1, -1],
            }
        )
        assert report["cross_group"] > 0
        assert report["n_parties"] == 7  # 5 人 + 2 人（skip 不计立场）
        assert "pa_total" in report
        assert "z_statistic" in report
        assert "significant_90" in report
        assert report["growth"] == pytest.approx(laplace_agreement(4, 4))

    def test_report_dict_votes(self):
        report = consensus_report({"g1": {"agree": 30, "disagree": 2}})
        assert report["n_parties"] == 32
        assert report["significant_90"] is True
