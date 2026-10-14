"""
MBTI 文本分析器：从用户自述/沟通文本推断性格维度与类型。

轻量实现，基于关键词维度打分（E/I, S/N, T/F, J/P），无 LLM、无外仓依赖。
来源思路：gozervi/zervipy LoomaCRM MBTI 分析服务，已迁入 Tatha 主仓独立使用。
"""

from typing import Dict, List, Tuple

# 最小有效文本长度（字符），低于此不分析
MIN_TEXT_LENGTH = 20

# 无信号 / 未产出类型时的占位类型（沿用既有约定，消费方据此判定「未产出类型」）
UNKNOWN_TYPE = "XXXX"

# 否定前缀：关键词紧邻这些字词时不计分（「不独立」「没有计划」不构成 I/J 信号）
NEGATION_PREFIXES = (
    "不", "没", "无", "非", "未", "别", "莫", "毫无",
    "没有", "并不", "绝不", "从不", "不太", "不是", "无法", "未能", "未曾",
)

# 否定词与关键词之间可插入的修饰词：「不是很独立」「不太理性」同样是否定，
# 但「不断探索」的「不断」不是——故只剥离白名单内的填充词，不做逐字判断。
NEGATION_FILLERS = (
    "是", "很", "太", "挺", "蛮", "比较", "非常", "特别", "有点", "有些",
    "那么", "这么", "真的",
)

# 否定回看窗口（字符）：容纳「否定词 + 填充词」的最长常见组合
NEGATION_WINDOW = 5


class MBTITextAnalyzer:
    """MBTI 文本分析器 - 从沟通/自述内容中提取性格特征"""

    def __init__(self) -> None:
        self.keywords = {
            "E": ["团队", "分享", "讨论", "活动", "社交", "热情", "外向"],
            "I": ["独立", "思考", "安静", "专注", "深入", "内省", "独处"],
            "S": ["具体", "细节", "实际", "经验", "事实", "现在", "步骤"],
            "N": ["概念", "可能", "未来", "创新", "愿景", "理论", "模式"],
            "T": ["逻辑", "分析", "客观", "效率", "原则", "公平", "理性"],
            "F": ["感受", "价值", "和谐", "关系", "同情", "体谅", "情感"],
            "J": ["计划", "组织", "决定", "结构", "截止", "完成", "确定"],
            # 「可能」原同时挂在 N 与 P，同一词被双维计分；已只保留在 N（可能性/推演属直觉）
            "P": ["灵活", "适应", "探索", "开放", "即兴", "选项"],
        }
        self.flower_mapping = {
            "INTJ": {"flower": "紫罗兰", "traits": ["深思熟虑", "独立思考", "追求完美"]},
            "ENTJ": {"flower": "向日葵", "traits": ["领导力强", "目标导向", "果断决策"]},
            "INFP": {"flower": "薰衣草", "traits": ["理想主义", "富有同情心", "创造力强"]},
            "ENFP": {"flower": "雏菊", "traits": ["热情洋溢", "富有想象力", "善于沟通"]},
            "ISTJ": {"flower": "康乃馨", "traits": ["可靠负责", "注重细节", "实事求是"]},
            "ESTJ": {"flower": "菊花", "traits": ["组织能力强", "务实高效", "遵守规则"]},
            "ISFP": {"flower": "樱花", "traits": ["温和友善", "灵活变通", "审美敏感"]},
            "ESFP": {"flower": "玫瑰", "traits": ["活力四射", "乐观开朗", "享受当下"]},
            # 2026-09-30 补全缺失 8 型（陆游实测命中 INFJ 时发现缺口）
            "INFJ": {"flower": "白玉兰", "traits": ["洞察深刻", "使命感强", "温和坚定"]},
            "ENFJ": {"flower": "茉莉", "traits": ["善于激励", "共情领导", "凝聚人心"]},
            "INTP": {"flower": "蓝铃花", "traits": ["逻辑严密", "好奇心强", "独立钻研"]},
            "ENTP": {"flower": "蒲公英", "traits": ["思维敏捷", "喜欢挑战", "创新破格"]},
            "ISFJ": {"flower": "满天星", "traits": ["默默奉献", "细致体贴", "值得信赖"]},
            "ESFJ": {"flower": "绣球花", "traits": ["热心助人", "重视和谐", "组织有方"]},
            "ISTP": {"flower": "仙人掌", "traits": ["冷静务实", "动手能力强", "随机应变"]},
            "ESTP": {"flower": "红山茶", "traits": ["行动力强", "敢冒风险", "活在当下"]},
        }

    def analyze_text(self, text: str) -> Dict:
        """分析文本，返回 MBTI 类型与维度分数等。

        ``status`` 有三种取值：

        - ``ok``：四轴均有信号，``mbti_type`` 为完整四字母类型
        - ``partial``：部分轴两向计数相同，该轴以 ``X`` 占位（如 ``EXFX``），不猜
        - ``insufficient``：无信号，``mbti_type`` 为 ``XXXX``，``insufficient_reason``
          说明是哪种（``text_too_short`` / ``no_keyword_signal`` / ``all_axes_tied``）

        ``partial`` / ``insufficient`` 时不给花语、不应给出职业建议——无信号时
        猜测类型（旧行为恒返回 INFP + 薰衣草 + 置信 50）等于把噪声当结论展示。
        """
        if not text or len(text.strip()) < MIN_TEXT_LENGTH:
            return self._insufficient_result("text_too_short")

        t = text.strip()
        axis_counts = {
            (pos_dim, neg_dim): self._axis_counts(t, pos_dim, neg_dim)
            for pos_dim, neg_dim in (("E", "I"), ("S", "N"), ("T", "F"), ("J", "P"))
        }

        # 整段没有任何关键词命中（含被否定抵消的）→ 无信号，不猜类型
        if not any(pos or neg for pos, neg in axis_counts.values()):
            return self._insufficient_result("no_keyword_signal")

        axes: List[str] = []
        undetermined: List[str] = []
        for (pos_dim, neg_dim), (pos, neg) in axis_counts.items():
            if pos == neg:
                axes.append("X")
                undetermined.append(f"{pos_dim}/{neg_dim}")
            else:
                axes.append(pos_dim if pos > neg else neg_dim)

        # 有信号但四轴两向都持平（如同时提到「独立」与「团队」）→ 仍判不出任何一轴
        if len(undetermined) == 4:
            return self._insufficient_result("all_axes_tied")

        # 百分比量纲：同轴两向共享分母，保留旧版的 0–100 可比性
        pct: Dict[str, float] = {}
        for (pos_dim, neg_dim), (pos, neg) in axis_counts.items():
            pct[pos_dim], pct[neg_dim] = self._axis_percent(pos, neg)

        mbti_type = "".join(axes)
        confidence = self._calculate_confidence(
            abs(pct["E"] - pct["I"]),
            abs(pct["S"] - pct["N"]),
            abs(pct["T"] - pct["F"]),
            abs(pct["J"] - pct["P"]),
            undetermined_count=len(undetermined),
        )
        # 花语只挂在完整四字母类型上；含 X 的类型不套花语，避免张冠李戴
        flower_info = self.flower_mapping.get(
            mbti_type, {"flower": "待分析", "traits": []}
        )

        return {
            "status": "partial" if undetermined else "ok",
            "undetermined_axes": undetermined,
            "mbti_type": mbti_type,
            "mbti_confidence": round(confidence, 2),
            "extraversion_score": round(pct["E"] - pct["I"], 2),
            "sensing_score": round(pct["S"] - pct["N"], 2),
            "thinking_score": round(pct["T"] - pct["F"], 2),
            "judging_score": round(pct["J"] - pct["P"], 2),
            "flower_personality": flower_info["flower"],
            "flower_traits": flower_info["traits"],
            "emotional_tone": self._emotional_tone(t),
            "communication_style": self._communication_style(t),
            "keywords": self._extract_keywords(t),
            "mbti_indicators": pct,
        }

    def _is_negated(self, text: str, start: int) -> bool:
        """关键词命中位置是否被否定词修饰。

        取关键词前的窗口，先剥掉尾部白名单内的填充词（「不是很独立」剥掉「很」
        「是」后剩「不」），再判否定前缀。刻意不做「前 1–2 字逐字判断」——那样
        「不断」里的「不」会被当成否定，「不断探索」会从命中变成不命中。
        """
        window = text[max(0, start - NEGATION_WINDOW) : start]
        stripped = True
        while stripped:
            stripped = False
            for filler in NEGATION_FILLERS:
                if window.endswith(filler):
                    window = window[: -len(filler)]
                    stripped = True
        return window.endswith(NEGATION_PREFIXES)

    def _has_hit(self, text: str, keyword: str) -> bool:
        """关键词是否出现，且未被否定前缀修饰。

        「不确定」不计入 J，「没有计划」不计入 J，「不是很独立」不计入 I；
        而「不断探索」的「探索」仍计入 P（「不断」不是否定词）。
        """
        start = text.find(keyword)
        while start != -1:
            if not self._is_negated(text, start):
                return True
            start = text.find(keyword, start + 1)
        return False

    def _axis_counts(self, text: str, pos_dim: str, neg_dim: str) -> Tuple[int, int]:
        """返回某一轴两个方向的命中词数（去重后按出现与否计 0/1）。"""
        pos = sum(1 for k in self.keywords[pos_dim] if self._has_hit(text, k))
        neg = sum(1 for k in self.keywords[neg_dim] if self._has_hit(text, k))
        return pos, neg

    def _axis_percent(self, pos: int, neg: int) -> Tuple[float, float]:
        """把命中词数折算成百分比（+1 平滑，沿用既有量纲）。"""
        total = pos + neg + 1
        return (pos / total) * 100, (neg / total) * 100

    def _calculate_confidence(
        self,
        ei_diff: float,
        sn_diff: float,
        tf_diff: float,
        jp_diff: float,
        undetermined_count: int = 0,
    ) -> float:
        """置信度 = 四轴平均差异幅度 × 2（上界 100），再按「已确定轴」比例折减。

        刻意不设下限：旧实现的 ``max(..., 50.0)`` 会把「零信号」伪装成
        「中等置信」，是无信号却返回 INFP 的根因之一。
        """
        avg = (ei_diff + sn_diff + tf_diff + jp_diff) / 4
        raw = min(avg * 2, 100.0)
        return raw * (1 - undetermined_count / 4)

    def _emotional_tone(self, text: str) -> str:
        pos = ["好", "棒", "优秀", "满意", "喜欢", "感谢", "期待"]
        neg = ["不", "差", "问题", "困难", "担心", "抱歉", "遗憾"]
        p = sum(1 for w in pos if w in text)
        n = sum(1 for w in neg if w in text)
        if p > n * 1.5:
            return "positive"
        if n > p * 1.5:
            return "negative"
        return "neutral"

    def _communication_style(self, text: str) -> str:
        q = text.count("？") + text.count("?")
        if q > 3:
            return "inquiring"
        if len(text) > 500:
            return "detailed"
        if len(text) < 100:
            return "concise"
        return "balanced"

    def _extract_keywords(self, text: str) -> List[str]:
        out: List[str] = []
        for dim in self.keywords.values():
            for k in dim:
                if self._has_hit(text, k):
                    out.append(k)
        return list(dict.fromkeys(out))[:10]

    def _insufficient_result(self, reason: str) -> Dict:
        """无信号结果：显式声明「未产出类型」，不填任何猜测值。"""
        return {
            "status": "insufficient",
            "undetermined_axes": ["E/I", "S/N", "T/F", "J/P"],
            "insufficient_reason": reason,
            "mbti_type": UNKNOWN_TYPE,
            "mbti_confidence": 0.0,
            "extraversion_score": 0.0,
            "sensing_score": 0.0,
            "thinking_score": 0.0,
            "judging_score": 0.0,
            "flower_personality": "待分析",
            "flower_traits": [],
            "emotional_tone": "neutral",
            "communication_style": "unknown",
            "keywords": [],
            "mbti_indicators": {},
        }
