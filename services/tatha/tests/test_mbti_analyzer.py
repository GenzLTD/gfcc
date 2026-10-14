"""
MBTI 文本分析器契约测试：无信号不得猜测类型（BE-2 静默降级回归）。

背景——修复前存在三处联动缺陷：

1. `_calculate_confidence` 带 50 分下限 `max(min(avg * 2, 100), 50.0)`，
   四轴零命中时仍报「置信 50」；
2. 平局分支 `e > i ? E : I` 使 `0 == 0` 判为 I/N/F/P，于是任何「≥20 字但
   无关键词」的文本恒返回 **INFP + 薰衣草 + 置信 50**；
3. `central_brain` 的守卫 `mbti_type != "XXXX"` 是死代码——`XXXX` 只在
   正文 < 20 字时出现，而该路径已被外层 `MIN_TEXT_LENGTH` 拦截，于是上面
   那个 INFP 一路走到回话「已完成性格分析并给出职业建议」。

本文件锁定修复后的契约：无信号必须显式返回 `insufficient`，且不得产出
花语与职业建议。

运行：
    PYTHONPATH=.:yeDall:src .venv/bin/python -m pytest tests/test_mbti_analyzer.py -v
"""

import pytest

from tatha.agents.mbti_analyzer import (
    MIN_TEXT_LENGTH,
    NEGATION_PREFIXES,
    UNKNOWN_TYPE,
    MBTITextAnalyzer,
)
from tatha.agents.mbti_career_match import (
    CAREER_MATCHES,
    DEFAULT_CAREER,
    get_career_match,
)
from tatha.api.central_brain import parse_intent, dispatch
from tatha.api.schemas import AskRequest

# 零关键词语料：长度远超 MIN_TEXT_LENGTH，四轴却一个词都不命中
NEUTRAL_TEXT = (
    "今天上午我出门买了些水果，路上遇到邻居聊了几句，下午回家做饭，晚上早点睡。"
)
ENGLISH_TEXT = (
    "This is a plain factual sentence with no Chinese personality words at all."
)
# 关键词密集语料：I/S/T/J 四轴均有明确信号
SIGNAL_TEXT = (
    "帮我分析一下性格：我喜欢独立思考问题，注重逻辑和细节，做事有计划，"
    "喜欢按步骤完成目标，比较理性。"
)


@pytest.fixture
def analyzer():
    return MBTITextAnalyzer()


# ---------------------------------------------------------------- 无信号拦截


def test_text_shorter_than_min_returns_insufficient_without_guessing(analyzer):
    """短于阈值：返回 insufficient，不得猜类型。"""
    result = analyzer.analyze_text("你好")

    assert result["status"] == "insufficient"
    assert result["insufficient_reason"] == "text_too_short"
    assert result["mbti_type"] == UNKNOWN_TYPE
    assert result["mbti_confidence"] == 0.0
    assert result["flower_personality"] == "待分析"


@pytest.mark.parametrize(
    "text,label",
    [(NEUTRAL_TEXT, "中文中性叙述"), (ENGLISH_TEXT, "英文零关键词")],
)
def test_no_keyword_signal_returns_insufficient(analyzer, text, label):
    """长度足够但零关键词：必须 insufficient，而非静默猜一个类型。"""
    assert len(text) >= MIN_TEXT_LENGTH, f"{label} 语料长度应超过阈值"

    result = analyzer.analyze_text(text)

    assert result["status"] == "insufficient"
    assert result["insufficient_reason"] == "no_keyword_signal"
    assert result["mbti_type"] == UNKNOWN_TYPE
    assert result["mbti_confidence"] == 0.0
    assert result["flower_personality"] == "待分析"
    assert result["flower_traits"] == []
    assert result["mbti_indicators"] == {}


def test_zero_signal_never_yields_infp_haiku_with_50_confidence(analyzer):
    """回归点：修复前零信号恒返回 INFP + 薰衣草 + 置信 50。"""
    result = analyzer.analyze_text(NEUTRAL_TEXT)

    assert result["mbti_type"] != "INFP"
    assert result["flower_personality"] != "薰衣草"
    assert result["mbti_confidence"] != 50.0


def test_confidence_has_no_lower_bound(analyzer):
    """置信度不再有 50 分下限；零信号即 0。"""
    assert analyzer.analyze_text(NEUTRAL_TEXT)["mbti_confidence"] == 0.0

    # 单轴有信号、三轴未定 → 既不是 0 也不是被抬到 50 的伪值
    single_axis = analyzer.analyze_text("我特别注重具体的细节和实际的经验，凡事讲事实和步骤。")
    assert 0 < single_axis["mbti_confidence"] < 50


def test_all_axes_tied_is_insufficient_but_reason_differs(analyzer):
    """四轴两向都持平 = 有信号却判不出任一轴，理由不应写成「无关键词」。"""
    tied = analyzer.analyze_text("团队 独立 具体 概念 逻辑 感受 计划 灵活")

    assert tied["status"] == "insufficient"
    assert tied["insufficient_reason"] == "all_axes_tied"
    assert tied["mbti_type"] == UNKNOWN_TYPE


# ---------------------------------------------------------------- 有信号路径


def test_clear_signal_returns_full_type_with_flower_and_career(analyzer):
    """有明确信号：仍返回完整四字母类型 + 花语 + 职业建议。"""
    result = analyzer.analyze_text(SIGNAL_TEXT)

    assert result["status"] == "ok"
    assert result["undetermined_axes"] == []
    assert len(result["mbti_type"]) == 4
    assert "X" not in result["mbti_type"]
    assert result["mbti_type"] in analyzer.flower_mapping
    assert result["flower_personality"] == analyzer.flower_mapping[result["mbti_type"]]["flower"]
    assert result["mbti_confidence"] > 0

    career = get_career_match(result["mbti_type"])
    assert career["suitable_careers"] != ["可根据更详细的自述再做分析"]


def test_partial_signal_marks_axis_x_and_withholds_flower(analyzer):
    """只有部分轴有信号：该轴以外用 X 占位，且不套花语。"""
    result = analyzer.analyze_text("我特别注重具体的细节和实际的经验，凡事讲事实和步骤。")

    assert result["status"] == "partial"
    assert "X" in result["mbti_type"]
    assert result["mbti_type"].startswith("XS")  # 仅 S/N 轴有信号
    assert set(result["undetermined_axes"]) == {"E/I", "T/F", "J/P"}
    assert result["flower_personality"] == "待分析"


# ---------------------------------------------------------------- 关键词表


def test_keyword_table_has_no_cross_axis_duplicate(analyzer):
    """「可能」原同时挂在 N 与 P，会双重计分；去重后共 55 词。"""
    flat = [k for dim in analyzer.keywords.values() for k in dim]

    assert len(flat) == len(set(flat)) == 55
    assert "可能" in analyzer.keywords["N"]
    assert "可能" not in analyzer.keywords["P"]


def test_flower_mapping_covers_all_sixteen_types(analyzer):
    """16 型花语全覆盖（2026-09-30 补齐缺失 8 型）。"""
    all_types = {
        a + b + c + d for a in "EI" for b in "NS" for c in "TF" for d in "JP"
    }

    assert set(analyzer.flower_mapping) == all_types
    assert all(v["flower"] and v["traits"] for v in analyzer.flower_mapping.values())


def test_career_match_covers_all_sixteen_types():
    """职业匹配表 16 型全覆盖，且每型四个字段均非空。

    下游（GenzLTD/Tatha）曾漂到 8 型、缺省落到「百合」，根因之一是缺这条契约。
    MB-1 同步时本测试随 `mbti_career_match.py` 一并搬过去。
    """
    all_types = {
        a + b + c + d for a in "EI" for b in "NS" for c in "TF" for d in "JP"
    }

    assert set(CAREER_MATCHES) == all_types
    for mbti_type, entry in CAREER_MATCHES.items():
        for field in ("suitable_careers", "work_style", "strengths", "growth_areas"):
            assert entry.get(field), f"{mbti_type}.{field} 不应为空"
        assert entry["suitable_careers"] != DEFAULT_CAREER["suitable_careers"]


def test_flower_and_career_tables_cover_the_same_types(analyzer):
    """两张表类型集合必须一致：任一表缺型都会静默落到默认值。"""
    assert set(analyzer.flower_mapping) == set(CAREER_MATCHES)


def test_negated_keywords_are_not_counted(analyzer):
    """「不独立」「没有计划」「不确定」不应构成 I/J 信号。"""
    result = analyzer.analyze_text(
        "我不独立，也没有计划，更不确定要不要做决定。今天天气不错，出门散步了。"
    )

    indicators = result["mbti_indicators"]
    assert indicators["I"] == 0  # 「不独立」被否定
    assert indicators["P"] == 0
    assert result["mbti_type"].endswith("J")  # 仅「做决定」这一处有效 J 信号


def test_negation_does_not_swallow_legit_keyword(analyzer):
    """「不断探索」的否定词不紧贴关键词，仍应计入 P。"""
    result = analyzer.analyze_text(
        "我喜欢不断探索新的可能性，适应变化，保持开放，随时调整选项。"
    )

    result_without_negation_words = analyzer.analyze_text(
        "我喜欢探索新的可能性，适应变化，保持开放，随时调整选项。" + "。" * 12
    )

    assert result["mbti_indicators"]["P"] > 0
    assert result["mbti_indicators"]["P"] == result_without_negation_words["mbti_indicators"]["P"]


@pytest.mark.parametrize(
    "text,keyword",
    [
        ("不独立", "独立"),
        ("我不独立", "独立"),
        ("没计划", "计划"),
        ("非理性", "理性"),
        ("不确定", "确定"),
        ("我没有计划", "计划"),
    ],
)
def test_negation_directly_before_keyword_blocks_it(analyzer, text, keyword):
    """否定词紧贴关键词时不计分——既有正确行为，先锁住防回归。"""
    assert analyzer._has_hit(text, keyword) is False


@pytest.mark.parametrize(
    "text,keyword",
    [
        ("我不是很独立", "独立"),
        ("不是很理性", "理性"),
        ("我不太独立", "独立"),
    ],
)
def test_negation_with_filler_words_blocks_keyword(analyzer, text, keyword):
    """回归点：否定词与关键词之间夹了「是 / 很 / 太」时同样应拦住。

    修复前窗口只取关键词前 2 字，「不是很独立」取到的是「是很」，否定词「不」
    落在窗口外，于是被当成 I 信号计分。
    """
    assert analyzer._has_hit(text, keyword) is False


def test_negation_is_not_read_into_non_negation_words(analyzer):
    """「不断」不是否定词：不得逐字判断，否则会漏掉真实信号。"""
    assert analyzer._has_hit("不断探索", "探索") is True
    assert analyzer._has_hit("我不断探索新的可能性", "探索") is True


def test_filler_negation_produces_no_axis_signal(analyzer):
    """整句层面：夹了填充词的否定不产生维度信号，真实信号不受影响。"""
    result = analyzer.analyze_text(
        "我不是很独立，也不太理性，做事也没有计划；但我很喜欢团队合作，大家一起讨论。"
    )

    assert result["mbti_indicators"]["I"] == 0  # 「不是很独立」被否定
    assert result["mbti_indicators"]["T"] == 0  # 「不太理性」被否定
    assert result["mbti_indicators"]["J"] == 0  # 「也没有计划」被否定
    assert result["mbti_indicators"]["E"] > 0  # 「团队」「讨论」仍计分
    assert result["mbti_type"].startswith("E")


def test_negation_prefixes_are_documented_constant():
    """否定前缀表是模块级常量，便于后续按语料扩充。"""
    assert "不" in NEGATION_PREFIXES and "没有" in NEGATION_PREFIXES


# ---------------------------------------------------- 中央大脑（产品回话面）


def test_dispatch_insufficient_does_not_claim_analysis_done():
    """回归点：零信号文本不得回话「已完成性格分析并给出职业建议」。"""
    result = dispatch("mbti", AskRequest(message="帮我分析一下性格：" + NEUTRAL_TEXT))

    assert result["status"] == "pending"
    assert "已完成性格分析" not in result["message"]
    assert result.get("hint")
    assert "career_match" not in (result.get("extracted") or {})


def test_dispatch_ok_returns_career_match():
    """有信号时中央大脑仍返回 ok + career_match。"""
    result = dispatch("mbti", AskRequest(message=SIGNAL_TEXT))

    assert result["status"] == "ok"
    extracted = result["extracted"]
    assert len(extracted["mbti_type"]) == 4
    assert "X" not in extracted["mbti_type"]
    assert extracted["career_match"]


def test_dispatch_partial_asks_for_more_input():
    """部分轴有信号：pending + 指明缺失维度，不给职业建议。"""
    result = dispatch(
        "mbti",
        AskRequest(message="帮我测评一下性格：我特别注重具体的细节和实际的经验，凡事讲事实和步骤。"),
    )

    assert result["status"] == "pending"
    assert "career_match" not in (result.get("extracted") or {})
    assert "E/I" in (result.get("hint") or "")


def test_intent_rules_route_personality_text_to_mbti(monkeypatch):
    """不依赖 LLM：规则路径应把含「性格」的长文本判为 mbti 意图。"""
    monkeypatch.setattr("tatha.api.central_brain.use_llm_intent", lambda: False)

    intent, confidence, _ = parse_intent("帮我分析一下性格：" + NEUTRAL_TEXT)

    assert intent == "mbti"
    assert confidence > 0
