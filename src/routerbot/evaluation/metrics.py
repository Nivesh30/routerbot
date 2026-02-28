"""Built-in evaluation metrics: BLEU, ROUGE, similarity, exact-match, contains."""

from __future__ import annotations

import math
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r"\w+", text.lower())


# ---------------------------------------------------------------------------
# n-gram helpers
# ---------------------------------------------------------------------------


def _ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    """Extract n-grams from a list of tokens."""
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _count_ngrams(tokens: list[str], n: int) -> Counter[tuple[str, ...]]:
    return Counter(_ngrams(tokens, n))


# ---------------------------------------------------------------------------
# BLEU
# ---------------------------------------------------------------------------


def bleu_score(
    reference: str,
    candidate: str,
    *,
    max_n: int = 4,
    brevity_penalty: bool = True,
) -> float:
    """Compute a (simplified) corpus-BLEU between reference and candidate.

    Uses modified n-gram precision for n = 1..max_n with uniform weights,
    plus the standard brevity penalty.

    Returns a float in [0, 1].
    """
    ref_tokens = _tokenize(reference)
    cand_tokens = _tokenize(candidate)

    if not cand_tokens or not ref_tokens:
        return 0.0

    precisions: list[float] = []
    for n in range(1, max_n + 1):
        ref_counts = _count_ngrams(ref_tokens, n)
        cand_counts = _count_ngrams(cand_tokens, n)

        # clipped counts: min(cand_count, ref_count) for each n-gram
        clipped = sum(min(count, ref_counts[ng]) for ng, count in cand_counts.items())
        total = sum(cand_counts.values())

        if total == 0:
            precisions.append(0.0)
        else:
            precisions.append(clipped / total)

    # Geometric mean of precisions (with smoothing: skip zeros)
    log_avg = 0.0
    count = 0
    for p in precisions:
        if p > 0:
            log_avg += math.log(p)
            count += 1

    if count == 0:
        return 0.0

    log_avg /= count

    # Brevity penalty
    bp = 1.0
    if brevity_penalty and len(cand_tokens) < len(ref_tokens):
        bp = math.exp(1 - len(ref_tokens) / len(cand_tokens))

    return bp * math.exp(log_avg)


# ---------------------------------------------------------------------------
# ROUGE
# ---------------------------------------------------------------------------


def rouge_score(
    reference: str,
    candidate: str,
    *,
    variant: str = "rouge_1",
) -> dict[str, float]:
    """Compute ROUGE-N or ROUGE-L F1 score.

    Variants: ``rouge_1``, ``rouge_2``, ``rouge_l``.
    Returns dict with ``precision``, ``recall``, ``f1`` keys.
    """
    ref_tokens = _tokenize(reference)
    cand_tokens = _tokenize(candidate)

    if not ref_tokens or not cand_tokens:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    if variant in ("rouge_1", "rouge_2"):
        n = 1 if variant == "rouge_1" else 2
        ref_counts = _count_ngrams(ref_tokens, n)
        cand_counts = _count_ngrams(cand_tokens, n)
        overlap = sum(min(cand_counts[ng], ref_counts[ng]) for ng in cand_counts if ng in ref_counts)
        precision = overlap / sum(cand_counts.values()) if cand_counts else 0.0
        recall = overlap / sum(ref_counts.values()) if ref_counts else 0.0
    elif variant == "rouge_l":
        lcs_len = _lcs_length(ref_tokens, cand_tokens)
        precision = lcs_len / len(cand_tokens)
        recall = lcs_len / len(ref_tokens)
    else:
        msg = f"Unknown ROUGE variant: {variant}"
        raise ValueError(msg)

    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def _lcs_length(a: list[str], b: list[str]) -> int:
    """Length of the longest common subsequence."""
    m, n = len(a), len(b)
    # Space-optimized: only keep two rows
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, [0] * (n + 1)
    return prev[n]


# ---------------------------------------------------------------------------
# Cosine similarity (bag-of-words, no external deps)
# ---------------------------------------------------------------------------


def cosine_similarity(text_a: str, text_b: str) -> float:
    """Bag-of-words cosine similarity in [0, 1]."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    counter_a = Counter(tokens_a)
    counter_b = Counter(tokens_b)
    all_terms = set(counter_a) | set(counter_b)

    dot = sum(counter_a.get(t, 0) * counter_b.get(t, 0) for t in all_terms)
    mag_a = math.sqrt(sum(v * v for v in counter_a.values()))
    mag_b = math.sqrt(sum(v * v for v in counter_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Simple string metrics
# ---------------------------------------------------------------------------


def exact_match(reference: str, candidate: str, *, case_sensitive: bool = False) -> float:
    """Return 1.0 if texts match exactly, else 0.0."""
    if case_sensitive:
        return 1.0 if reference == candidate else 0.0
    return 1.0 if reference.lower() == candidate.lower() else 0.0


def contains_match(reference: str, candidate: str, *, case_sensitive: bool = False) -> float:
    """Return 1.0 if reference appears in candidate, else 0.0."""
    if case_sensitive:
        return 1.0 if reference in candidate else 0.0
    return 1.0 if reference.lower() in candidate.lower() else 0.0


# ---------------------------------------------------------------------------
# Aggregated metric runner
# ---------------------------------------------------------------------------


def compute_metric(metric_name: str, reference: str, candidate: str) -> float:
    """Compute a named metric, returning a single float score.

    Supported names: ``bleu``, ``rouge_1``, ``rouge_2``, ``rouge_l``,
    ``exact_match``, ``contains``, ``similarity``.
    """
    metric_name = metric_name.lower()
    if metric_name == "bleu":
        return bleu_score(reference, candidate)
    if metric_name in ("rouge_1", "rouge_2", "rouge_l"):
        return rouge_score(reference, candidate, variant=metric_name)["f1"]
    if metric_name == "exact_match":
        return exact_match(reference, candidate)
    if metric_name == "contains":
        return contains_match(reference, candidate)
    if metric_name == "similarity":
        return cosine_similarity(reference, candidate)

    msg = f"Unknown metric: {metric_name}"
    raise ValueError(msg)
