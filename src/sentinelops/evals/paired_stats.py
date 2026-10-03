"""
Paired Statistical Analysis Module for SentinelOps Benchmark Evaluations.

Provides rigorous paired statistical testing for:
1. Binary investigation correctness across paired modes (McNemar's exact test & paired proportion CIs).
2. Query-level continuous/discrete retrieval metrics across paired modes (Paired bootstrap CIs).

Invariants:
- Rejects misaligned, missing, or mismatched scenario/query IDs.
- Deterministic bootstrap resampling with configurable seed.
- Exact binomial computation for small sample discordant pairs.
- Zero fabricated significance claims.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class BinaryPairedComparisonResult:
    """Statistical result for paired binary correctness outcomes (e.g. McNemar's test)."""

    mode_a: str
    mode_b: str
    sample_count: int
    both_correct: int
    a_only_correct: int
    b_only_correct: int
    neither_correct: int
    accuracy_a: float
    accuracy_b: float
    accuracy_difference: float
    difference_ci_95: tuple[float, float]
    test_name: str
    test_statistic: float | None
    p_value: float
    is_statistically_significant: bool  # alpha = 0.05
    interpretation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode_a": self.mode_a,
            "mode_b": self.mode_b,
            "sample_count": self.sample_count,
            "contingency_table": {
                "both_correct": self.both_correct,
                "a_only_correct": self.a_only_correct,
                "b_only_correct": self.b_only_correct,
                "neither_correct": self.neither_correct,
            },
            "accuracy_a": round(self.accuracy_a, 4),
            "accuracy_b": round(self.accuracy_b, 4),
            "accuracy_difference": round(self.accuracy_difference, 4),
            "difference_ci_95": [round(self.difference_ci_95[0], 4), round(self.difference_ci_95[1], 4)],
            "test_name": self.test_name,
            "test_statistic": round(self.test_statistic, 4) if self.test_statistic is not None else None,
            "p_value": round(self.p_value, 6),
            "is_significant_at_0_05": self.is_statistically_significant,
            "interpretation": self.interpretation,
        }


@dataclass(frozen=True)
class RetrievalPairedBootstrapResult:
    """Statistical result for paired continuous/discrete retrieval metrics via bootstrap."""

    mode_a: str
    mode_b: str
    metric_name: str
    sample_count: int
    mean_a: float
    mean_b: float
    mean_difference: float  # mean(a) - mean(b)
    difference_ci_95: tuple[float, float]
    bootstrap_iterations: int
    random_seed: int
    test_name: str
    is_statistically_significant: bool  # 95% CI does not span 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode_a": self.mode_a,
            "mode_b": self.mode_b,
            "metric_name": self.metric_name,
            "sample_count": self.sample_count,
            "mean_a": round(self.mean_a, 4),
            "mean_b": round(self.mean_b, 4),
            "mean_difference": round(self.mean_difference, 4),
            "difference_ci_95": [round(self.difference_ci_95[0], 4), round(self.difference_ci_95[1], 4)],
            "bootstrap_iterations": self.bootstrap_iterations,
            "random_seed": self.random_seed,
            "test_name": self.test_name,
            "is_significant_at_0_05": self.is_statistically_significant,
        }


def mcnemar_exact_p_value(b: int, c: int) -> float:
    """
    Compute two-tailed p-value for McNemar's test using the exact binomial distribution.
    Discordant pairs b (A correct, B incorrect) and c (B correct, A incorrect).
    Under H0, b ~ Binomial(n=b+c, p=0.5).
    """
    n = b + c
    if n == 0:
        return 1.0

    k = min(b, c)
    # Two-sided exact binomial test: 2 * sum_{i=0}^k (n choose i) * 0.5^n
    tail_prob = sum(math.comb(n, i) for i in range(k + 1)) * (0.5**n)
    p_val = min(1.0, 2.0 * tail_prob)
    return p_val


def compute_paired_proportion_ci(
    b: int, c: int, total_n: int, confidence: float = 0.95
) -> tuple[float, float]:
    """
    Compute confidence interval for difference in paired proportions:
    p_diff = (b - c) / total_n
    Using Wald paired variance with Agresti-Min style continuity bounds.
    """
    if total_n == 0:
        return 0.0, 0.0

    diff = (b - c) / total_n
    z = 1.95996  # 95% standard normal quantile

    # Standard error of paired difference:
    # Var(p1 - p2) = ((b + c) - (b - c)^2 / total_n) / total_n^2
    var_diff = ((b + c) - ((b - c) ** 2) / total_n) / (total_n**2)
    if var_diff < 0:
        var_diff = 0.0
    se = math.sqrt(var_diff)

    lower = max(-1.0, diff - z * se)
    upper = min(1.0, diff + z * se)
    return lower, upper


def evaluate_investigation_paired_comparison(
    mode_a_name: str,
    mode_b_name: str,
    records_a: list[dict[str, Any]],
    records_b: list[dict[str, Any]],
    id_key: str = "scenario_id",
    correctness_key: str = "is_accurate",
) -> BinaryPairedComparisonResult:
    """
    Compute paired McNemar comparison between two investigation runs on identical incidents.
    Raises ValueError if scenario IDs do not align perfectly.
    """
    dict_a = {r[id_key]: bool(r[correctness_key]) for r in records_a}
    dict_b = {r[id_key]: bool(r[correctness_key]) for r in records_b}

    if set(dict_a.keys()) != set(dict_b.keys()):
        missing_in_b = set(dict_a.keys()) - set(dict_b.keys())
        missing_in_a = set(dict_b.keys()) - set(dict_a.keys())
        raise ValueError(
            f"Scenario ID mismatch between modes '{mode_a_name}' and '{mode_b_name}'. "
            f"Missing in B: {missing_in_b}, Missing in A: {missing_in_a}"
        )

    common_ids = sorted(dict_a.keys())
    sample_count = len(common_ids)
    if sample_count == 0:
        raise ValueError("Cannot perform paired comparison on empty sample.")

    both_correct = 0
    a_only = 0
    b_only = 0
    neither = 0

    for sid in common_ids:
        a_corr = dict_a[sid]
        b_corr = dict_b[sid]
        if a_corr and b_corr:
            both_correct += 1
        elif a_corr and not b_corr:
            a_only += 1
        elif not a_corr and b_corr:
            b_only += 1
        else:
            neither += 1

    acc_a = (both_correct + a_only) / sample_count
    acc_b = (both_correct + b_only) / sample_count
    diff = acc_a - acc_b

    ci_low, ci_high = compute_paired_proportion_ci(a_only, b_only, sample_count)

    discordant = a_only + b_only
    if discordant < 25:
        test_name = "McNemar's Exact Test (Binomial)"
        test_stat = None
        p_val = mcnemar_exact_p_value(a_only, b_only)
    else:
        test_name = "McNemar's Chi-Square Test (Continuity Corrected)"
        # Chi-square statistic with Edwards' continuity correction: (|b - c| - 1)^2 / (b + c)
        test_stat = (abs(a_only - b_only) - 1.0) ** 2 / discordant
        # Approximate p-value from 1-dof chi-square using erfc
        p_val = math.erfc(math.sqrt(test_stat) / math.sqrt(2.0))

    is_sig = p_val < 0.05
    if is_sig:
        favored = mode_a_name if diff > 0 else mode_b_name
        interpretation = (
            f"Statistically significant difference (p={p_val:.5f} < 0.05) "
            f"favoring {favored} by {abs(diff):.1%} [95% CI: {ci_low:.1%}, {ci_high:.1%}]."
        )
    else:
        interpretation = (
            f"No statistically significant difference detected (p={p_val:.5f} >= 0.05). "
            f"Observed difference: {diff:+.1%} [95% CI: {ci_low:.1%}, {ci_high:.1%}]."
        )

    return BinaryPairedComparisonResult(
        mode_a=mode_a_name,
        mode_b=mode_b_name,
        sample_count=sample_count,
        both_correct=both_correct,
        a_only_correct=a_only,
        b_only_correct=b_only,
        neither_correct=neither,
        accuracy_a=acc_a,
        accuracy_b=acc_b,
        accuracy_difference=diff,
        difference_ci_95=(ci_low, ci_high),
        test_name=test_name,
        test_statistic=test_stat,
        p_value=p_val,
        is_statistically_significant=is_sig,
        interpretation=interpretation,
    )


def evaluate_retrieval_paired_bootstrap(
    mode_a_name: str,
    mode_b_name: str,
    records_a: list[dict[str, Any]],
    records_b: list[dict[str, Any]],
    metric_name: str,
    id_key: str = "query_id",
    bootstrap_iterations: int = 2000,
    random_seed: int = 42,
) -> RetrievalPairedBootstrapResult:
    """
    Perform paired bootstrap test for a continuous/discrete retrieval metric across matching queries.
    Computes mean(a) - mean(b) and empirical 95% bootstrap confidence interval.
    """
    def get_metric(r: dict[str, Any], m: str) -> float:
        if m in r:
            return float(r[m])
        if "metrics" in r and m in r["metrics"]:
            return float(r["metrics"][m])
        raise KeyError(f"Metric '{m}' not found in record with keys {list(r.keys())}")

    dict_a = {r[id_key]: get_metric(r, metric_name) for r in records_a}
    dict_b = {r[id_key]: get_metric(r, metric_name) for r in records_b}

    if set(dict_a.keys()) != set(dict_b.keys()):
        missing_in_b = set(dict_a.keys()) - set(dict_b.keys())
        missing_in_a = set(dict_b.keys()) - set(dict_a.keys())
        raise ValueError(
            f"Query ID mismatch between modes '{mode_a_name}' and '{mode_b_name}'. "
            f"Missing in B: {missing_in_b}, Missing in A: {missing_in_a}"
        )

    common_ids = sorted(dict_a.keys())
    q_count = len(common_ids)
    if q_count == 0:
        raise ValueError("Cannot perform paired bootstrap on empty query sample.")

    values_a = [dict_a[qid] for qid in common_ids]
    values_b = [dict_b[qid] for qid in common_ids]

    mean_a = sum(values_a) / q_count
    mean_b = sum(values_b) / q_count
    mean_diff = mean_a - mean_b

    # Paired differences per query: d_i = a_i - b_i
    paired_diffs = [a - b for a, b in zip(values_a, values_b)]

    rng = random.Random(random_seed)
    bootstrap_diffs: list[float] = []

    for _ in range(bootstrap_iterations):
        sample_indices = [rng.randint(0, q_count - 1) for _ in range(q_count)]
        boot_diff = sum(paired_diffs[i] for i in sample_indices) / q_count
        bootstrap_diffs.append(boot_diff)

    bootstrap_diffs.sort()
    low_idx = int(0.025 * bootstrap_iterations)
    high_idx = int(0.975 * bootstrap_iterations)

    ci_low = bootstrap_diffs[low_idx]
    ci_high = bootstrap_diffs[high_idx]

    # Statistically significant if 95% CI does not include zero
    is_sig = (ci_low > 0.0 and ci_high > 0.0) or (ci_low < 0.0 and ci_high < 0.0)

    return RetrievalPairedBootstrapResult(
        mode_a=mode_a_name,
        mode_b=mode_b_name,
        metric_name=metric_name,
        sample_count=q_count,
        mean_a=mean_a,
        mean_b=mean_b,
        mean_difference=mean_diff,
        difference_ci_95=(ci_low, ci_high),
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed,
        test_name=f"Paired Percentile Bootstrap ({bootstrap_iterations} resamples)",
        is_statistically_significant=is_sig,
    )
