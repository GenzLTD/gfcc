"""合意引擎 W1 —— consensus_math.py（共识数学内核，纯函数库）。

来源：合意引擎技术调研（Pol.is / Loomio 算法思想重写）。
AGPL-3.0 红线（Mac 侧评审 13ec0f0 确认）：不搬两仓库代码与测试向量；
以下公式均为公开统计表述（拉普拉斯平滑、比例 z 检验、跨组连乘），
属数学常识重写，不构成衍生作品。

边界（Mac 侧评审约定）：
- 纯函数、零 I/O、不 import `gfcc_kernel`、不改 `contracts/`
- 默认零第三方依赖（标准库 `math` 足矣）；PCA / k-means / 轮廓系数等
  scikit-learn 组件按 extras（`gfcc_kernel[consensus-math]`）后续挂载
- 无 extras 时，consensus 端口 `score` 仍走现有显式证据路径

核心公式（公开统计表述）：
- 拉普拉斯平滑同意概率：pa = (A + 1) / (S + 2)      # 哑先验防小样本极端值
- 单比例 z 检验：       z = (pa - p0) / sqrt(p0(1-p0)/n)，90% 置信临界 ±1.6449
- 同意度 / 分歧度：     am = pa × z(pa)；dm = pd × z(pd)
- 跨组共识：            consensus = ∏_g (A_g + 1) / (S_g + 2)   # 任一组反对即拉垮
- 代表性（repness）：   ra × rat × pa × pat 四项连乘
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, Sequence, Tuple

# 标准正态分布 90% 置信双尾临界值（每尾 5%）
Z_CRITICAL_90 = 1.6449

Votes = Dict[str, int]  # 归一化投票计数：{"agree", "disagree", "skip"}


def normalize_votes(votes: Sequence[int] | Votes) -> Tuple[int, int, int]:
    """把投票归一到 (agree, disagree, skip) 计数。

    接受两种形态：
    - 列表：参与者逐票序列，∈ {-1, 0, 1}（-1 不同意 / 0 跳过 / 1 同意）
    - 字典：{"agree": n, "disagree": n, "skip": n}（缺省计 0）
    """
    if isinstance(votes, dict):
        agree = int(votes.get("agree", 0))
        disagree = int(votes.get("disagree", 0))
        skip = int(votes.get("skip", 0))
        if agree < 0 or disagree < 0 or skip < 0:
            raise ValueError("vote counts must be non-negative")
        return agree, disagree, skip
    agree = disagree = skip = 0
    for v in votes:
        if v == 1:
            agree += 1
        elif v == -1:
            disagree += 1
        elif v == 0:
            skip += 1
        else:
            raise ValueError(f"vote must be -1/0/1, got {v!r}")
    return agree, disagree, skip


def laplace_agreement(agree: int, seen: int) -> float:
    """拉普拉斯平滑同意概率 pa = (A + 1) / (S + 2)。

    seen = agree + disagree（跳过者不计入分母的“立场基数”）。
    边界：0/0 → (0+1)/(0+2)=0.5（无信息先验）。
    """
    if agree < 0 or seen < 0 or agree > seen:
        raise ValueError(f"require 0 <= agree <= seen, got agree={agree}, seen={seen}")
    return (agree + 1.0) / (seen + 2.0)


def one_proportion_z(p_hat: float, n: int, p0: float = 0.5) -> float:
    """单比例 z 检验：z = (p_hat - p0) / sqrt(p0(1-p0)/n)。

    默认零假设 p0=0.5（同意/不同意无偏好）。z 绝对值 ≥ 临界值即显著。
    """
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0.0 <= p_hat <= 1.0:
        raise ValueError("p_hat must be within [0, 1]")
    if not 0.0 < p0 < 1.0:
        raise ValueError("p0 must be strictly within (0, 1)")
    denom = math.sqrt(p0 * (1.0 - p0) / n)
    return (p_hat - p0) / denom


def two_proportion_z(p1: float, n1: int, p2: float, n2: int) -> float:
    """两比例 z 检验（池化标准误），用于组 vs 其余组的代表性检验。"""
    if n1 <= 0 or n2 <= 0:
        raise ValueError("n1, n2 must be positive")
    if not 0.0 <= p1 <= 1.0 or not 0.0 <= p2 <= 1.0:
        raise ValueError("p1, p2 must be within [0, 1]")
    pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
    if pooled <= 0.0 or pooled >= 1.0:
        return 0.0 if p1 == p2 else float("inf")
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n1 + 1.0 / n2))
    return (p1 - p2) / se


def is_significant(z: float, z_critical: float = Z_CRITICAL_90) -> bool:
    """|z| ≥ 90% 置信双尾临界值 → 统计显著（够格）。"""
    return abs(z) >= z_critical


def agreement_mass(agree: int, seen: int, p0: float = 0.5) -> float:
    """同意度 am = pa × z(pa)：同时惩罚“票数少”与“同意不占优”。"""
    pa = laplace_agreement(agree, seen)
    return pa * one_proportion_z(pa, seen, p0)


def disagreement_mass(disagree: int, seen: int, p0: float = 0.5) -> float:
    """分歧度 dm = pd × z(pd)：pd = (D + 1)/(S + 2)。"""
    if disagree < 0 or seen < 0 or disagree > seen:
        raise ValueError(f"require 0 <= disagree <= seen, got disagree={disagree}, seen={seen}")
    pd = (disagree + 1.0) / (seen + 2.0)
    return pd * one_proportion_z(pd, seen, p0)


def cross_group_consensus(groups: Iterable[Tuple[int, int]]) -> float:
    """跨组共识 = ∏_g (A_g + 1) / (S_g + 2)。

    groups：每组的 (agree, seen)。任一组强烈反对（A_g≈0）即把整体拉垮——
    “寻找最大公约数”的数学表达（Pol.is group-aware consensus 重写）。
    空输入返回 0.0（无投票 = 无共识）。
    """
    product = 1.0
    seen_any = False
    for agree, seen in groups:
        product *= laplace_agreement(agree, seen)
        seen_any = True
    return product if seen_any else 0.0


def representativeness(
    group_agree: int, group_seen: int, rest_agree: int, rest_seen: int
) -> float:
    """代表性 repness = ra × rat × pa × pat（四项连乘）。

    - ra  = pa(本组) / pa(其余组)      —— 本组立场与全局的偏离度
    - rat = 两比例 z 检验（组 vs 其余）
    - pa  = 本组拉普拉斯同意概率
    - pat = 本组单比例 z 检验（对 p0=0.5）

    注意：rat/pat 可为负，四项连乘可为负——负值表示“显著更不同意”，
    调用方应结合 is_significant 与 ra>1 的筛选规则决定“够格”与否。
    """
    pa_g = laplace_agreement(group_agree, group_seen)
    pa_r = laplace_agreement(rest_agree, rest_seen)
    if pa_r <= 0.0:  # 防御：其余组无同意先验时无代表性可言
        return 0.0
    ra = pa_g / pa_r
    rat = two_proportion_z(pa_g, group_seen, pa_r, rest_seen)
    pat = one_proportion_z(pa_g, group_seen, 0.5)
    return ra * rat * pa_g * pat


def consensus_report(votes_by_group: Dict[str, Sequence[int] | Votes]) -> Dict[str, object]:
    """面向 score_evidence 的报告：把分组投票汇成共识指标。

    输出可直接用于 consensus 端口 score_evidence[].basis 的数值来源：
    - {组名}：每组拉普拉斯同意概率
    - cross_group：跨组共识连乘值
    - n_parties：参与立场投票的人数（agree + disagree）
    - pa_total / z_statistic / significant_90：全局同意占优的显著性检验
    """
    row: Dict[str, object] = {}
    group_rows: list[Tuple[int, int]] = []  # (agree, seen)
    for label, votes in votes_by_group.items():
        agree, disagree, _skip = normalize_votes(votes)
        seen = agree + disagree
        group_rows.append((agree, seen))
        row[label] = laplace_agreement(agree, seen)
    row["cross_group"] = cross_group_consensus(group_rows)
    total_agree = sum(a for a, _s in group_rows)
    total_seen = sum(s for _a, s in group_rows)
    row["n_parties"] = total_seen
    if total_seen > 0:
        pa_total = laplace_agreement(total_agree, total_seen)
        z = one_proportion_z(pa_total, total_seen, 0.5)
        row["pa_total"] = pa_total
        row["z_statistic"] = z
        row["significant_90"] = is_significant(z)
    return row
