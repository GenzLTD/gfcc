"""Read identity.value_axes for job match. Never write them.

survival = 钱多 = salary_match
freedom = 事少 = culture_workload_match
belonging = 离家近 = location_match

The other six sub-scores and overall stay job-scoped.
"""

from __future__ import annotations

AXIS_READING = {
    "survival": ("钱多", "salary_match"),
    "freedom": ("事少", "culture_workload_match"),
    "belonging": ("离家近", "location_match"),
}

_SCORECARD_KEYS = {
    "salary_match",
    "location_match",
    "culture_workload_match",
    "overall",
    "background_match",
    "skills_overlap",
    "experience_relevance",
    "seniority",
    "language_requirement",
    "company_score",
}


def read_value_axes(raw: dict | None) -> dict[str, int] | None:
    """Return the human axes, or None when absent.

    A job-match scorecard passed in this slot is rejected. Callers must not
    persist the returned scores back onto these keys.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("value_axes must be an object")
    leaked = set(raw) & _SCORECARD_KEYS
    if leaked:
        raise ValueError("job-match scores must not be written into value_axes")
    extra = set(raw) - set(AXIS_READING)
    if extra:
        raise ValueError(f"value_axes has unknown keys: {sorted(extra)}")
    cleaned: dict[str, int] = {}
    for key in AXIS_READING:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{key} must be an integer >= 0")
        cleaned[key] = value
    return cleaned or None


def format_value_axes_prior(raw: dict | None) -> str:
    """Prompt fragment. Empty when the person has not chosen an axis."""
    axes = read_value_axes(raw)
    if not axes:
        return ""
    lines = ["【本人已选择的价值轴，只读，禁止写回身份】"]
    for key, (colloquial, score_field) in AXIS_READING.items():
        if key in axes:
            lines.append(
                f"- {key} = {axes[key]}，读作「{colloquial}」，"
                f"打 {score_field} 时按此偏好解释这一份职位。"
            )
        else:
            lines.append(f"- {key} 未声明，「{colloquial}」保持中性。")
    lines.append(
        "background_match、skills_overlap、experience_relevance、seniority、"
        "language_requirement、company_score、overall 只描述这一份职位。"
    )
    return "\n".join(lines) + "\n\n"
