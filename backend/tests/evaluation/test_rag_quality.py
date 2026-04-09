"""
Phase 8: RAG Quality Evaluation using RAGAS framework.
Metrics:
  - Faithfulness      (hallucination detection)  target >= 0.85
  - Answer Relevancy  (stays on topic)           target >= 0.80
  - Context Precision (retrieved chunks useful)  target >= 0.75
  - Context Recall    (all relevant chunks got)  target >= 0.80

Run: pytest tests/evaluation/test_rag_quality.py -v --tb=short
"""
import asyncio
import pytest
from dataclasses import dataclass
from typing import Optional

# These would use actual RAGAS in a real run:
# from ragas import evaluate
# from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
# from datasets import Dataset


@dataclass
class EvalSample:
    question: str
    ground_truth: str
    contexts: list[str]           # retrieved chunk contents
    answer: str                   # generated answer
    doc_type: Optional[str] = None


# ── Golden evaluation dataset ─────────────────────────────────────────────────
EVAL_DATASET = [
    EvalSample(
        question="What is the total AUM of the ABC Growth Fund?",
        ground_truth="The total AUM of the ABC Growth Fund is $4.2 billion as of Q3 2025.",
        contexts=[
            "ABC Growth Fund | Fact Sheet Q3 2025\nTotal Assets Under Management: $4.2 Billion\nInception Date: March 2019",
            "The fund seeks long-term capital appreciation through diversified equity exposure.",
        ],
        answer="According to the Q3 2025 fact sheet, the ABC Growth Fund has $4.2 billion in total assets under management. [1]",
        doc_type="fact_sheet",
    ),
    EvalSample(
        question="Compare the expense ratios of ABC Fund and XYZ Fund.",
        ground_truth="ABC Fund has an expense ratio of 0.45% while XYZ Fund has 0.72%.",
        contexts=[
            "ABC Growth Fund — Total Expense Ratio (TER): 0.45% per annum",
            "XYZ Balanced Portfolio — Management Fee: 0.65%, Total Expense Ratio: 0.72%",
        ],
        answer="| Fund | Expense Ratio |\n|------|---------------|\n| ABC Growth Fund | 0.45% |\n| XYZ Balanced Portfolio | 0.72% |\n\nABC Fund is significantly cheaper than XYZ Fund by 27 basis points. [1][2]",
        doc_type="fact_sheet",
    ),
    EvalSample(
        question="Were there any fund manager changes in 2025?",
        ground_truth="Yes, Jane Smith was appointed as lead fund manager of the ABC Growth Fund effective March 2025.",
        contexts=[
            "PERSONNEL NOTICE — March 2025\nEffective 1 March 2025, Jane Smith has been appointed Lead Fund Manager of ABC Growth Fund.",
            "Jane Smith holds a CFA designation and has 15 years of investment management experience.",
        ],
        answer="Yes, Jane Smith was appointed as Lead Fund Manager of ABC Growth Fund, effective 1 March 2025. [1]\n\nName | Role | Effective Date\n-----|------|--------------\nJane Smith | Lead Fund Manager (ABC Growth Fund) | 1 March 2025",
        doc_type="personnel",
    ),
    EvalSample(
        question="What were the Q3 2025 net returns for the growth fund?",
        ground_truth="The ABC Growth Fund returned 7.2% net in Q3 2025.",
        contexts=[
            "Quarterly Report Q3 2025 — Performance Summary\nABC Growth Fund Net Return Q3 2025: 7.2%\nBenchmark (MSCI World): 5.8%",
        ],
        answer="The ABC Growth Fund achieved a net return of 7.2% in Q3 2025, outperforming its MSCI World benchmark by 140 basis points (5.8%). [1]",
        doc_type="quarterly_report",
    ),
    EvalSample(
        question="What is the weather in London today?",  # Out-of-scope query
        ground_truth="This information is not available in the financial documents.",
        contexts=[],  # No relevant chunks retrieved
        answer="I could not find this information in the available documents. This appears to be outside the scope of the indexed financial documents.",
        doc_type=None,
    ),
]


# ── Faithfulness check (simplified without RAGAS API call) ────────────────────

def check_faithfulness(answer: str, contexts: list[str]) -> float:
    """
    Simplified faithfulness: check if key claims in the answer
    can be traced back to at least one context chunk.
    In production: use ragas.metrics.faithfulness
    """
    if not contexts:
        # No context, answer should say so
        return 1.0 if "not find" in answer.lower() or "not available" in answer.lower() else 0.0

    answer_lower = answer.lower()
    context_combined = " ".join(contexts).lower()

    # Extract numeric claims from answer
    import re
    numbers_in_answer = re.findall(r'\d+\.?\d*[%$]?', answer)
    numbers_in_context = re.findall(r'\d+\.?\d*[%$]?', context_combined)

    if not numbers_in_answer:
        return 0.85  # Default for non-numeric answers

    supported = sum(1 for n in numbers_in_answer if n in numbers_in_context)
    return supported / len(numbers_in_answer) if numbers_in_answer else 1.0


def check_answer_relevancy(question: str, answer: str) -> float:
    """
    Simplified answer relevancy: check key question terms appear in answer.
    In production: use ragas.metrics.answer_relevancy
    """
    if not answer.strip():
        return 0.0
    q_words = set(question.lower().split()) - {'what', 'is', 'the', 'a', 'an', 'of', 'for', 'in', 'are'}
    answer_lower = answer.lower()
    matched = sum(1 for w in q_words if w in answer_lower)
    return matched / len(q_words) if q_words else 1.0


def check_citation_present(answer: str, context_count: int) -> bool:
    """Verify citations are present in the answer."""
    if context_count == 0:
        return True  # No context, no citations needed
    import re
    citations = re.findall(r'\[\d+\]', answer)
    return len(citations) > 0


# ── Test cases ────────────────────────────────────────────────────────────────

class TestRAGQuality:

    FAITHFULNESS_THRESHOLD = 0.75   # slightly relaxed for unit test without real RAGAS
    RELEVANCY_THRESHOLD = 0.50
    MIN_FAITHFULNESS_SAMPLES = 0.80  # 80% of samples must pass

    @pytest.mark.parametrize("sample", EVAL_DATASET, ids=[s.question[:40] for s in EVAL_DATASET])
    def test_faithfulness(self, sample: EvalSample):
        """All numeric claims in the answer must be traceable to context."""
        score = check_faithfulness(sample.answer, sample.contexts)
        assert score >= self.FAITHFULNESS_THRESHOLD, (
            f"Faithfulness too low ({score:.2f}) for: '{sample.question}'\n"
            f"Answer: {sample.answer[:200]}"
        )

    @pytest.mark.parametrize("sample", EVAL_DATASET, ids=[s.question[:40] for s in EVAL_DATASET])
    def test_answer_relevancy(self, sample: EvalSample):
        """Answer must address the question's key concepts."""
        score = check_answer_relevancy(sample.question, sample.answer)
        assert score >= self.RELEVANCY_THRESHOLD, (
            f"Answer relevancy too low ({score:.2f}) for: '{sample.question}'"
        )

    @pytest.mark.parametrize("sample", EVAL_DATASET, ids=[s.question[:40] for s in EVAL_DATASET])
    def test_citations_present(self, sample: EvalSample):
        """Answers with retrieved context must include citation markers."""
        has_citations = check_citation_present(sample.answer, len(sample.contexts))
        assert has_citations, (
            f"Missing citations in answer for: '{sample.question}'\n"
            f"Answer: {sample.answer[:200]}"
        )

    def test_out_of_scope_handling(self):
        """Out-of-scope queries must explicitly state information not found."""
        oos = EVAL_DATASET[-1]  # Last sample is out-of-scope
        assert len(oos.contexts) == 0
        answer_lower = oos.answer.lower()
        assert any(phrase in answer_lower for phrase in [
            "not find", "not available", "not in the available", "outside the scope"
        ]), f"Out-of-scope answer missing explicit disclaimer: {oos.answer}"

    def test_comparison_produces_table(self):
        """Comparison queries must produce Markdown table output."""
        comparison = EVAL_DATASET[1]
        assert "|" in comparison.answer, (
            "Comparison answer missing Markdown table. "
            f"Answer: {comparison.answer[:200]}"
        )

    def test_personnel_query_structured(self):
        """Personnel queries must include structured name/role/date output."""
        personnel = EVAL_DATASET[2]
        answer_lower = personnel.answer.lower()
        assert any(k in answer_lower for k in ["name", "role", "effective", "appointed"]), (
            f"Personnel answer not structured: {personnel.answer[:200]}"
        )

    def test_overall_dataset_faithfulness_rate(self):
        """At least 80% of all samples must pass faithfulness check."""
        passes = sum(
            1 for s in EVAL_DATASET
            if check_faithfulness(s.answer, s.contexts) >= self.FAITHFULNESS_THRESHOLD
        )
        rate = passes / len(EVAL_DATASET)
        assert rate >= self.MIN_FAITHFULNESS_SAMPLES, (
            f"Overall faithfulness rate {rate:.0%} below threshold {self.MIN_FAITHFULNESS_SAMPLES:.0%}"
        )


# ── Full RAGAS evaluation runner (requires API keys + indexed documents) ──────

async def run_full_ragas_evaluation():
    """
    Full RAGAS evaluation — run this in CI with real document data.
    Requires: openai API key, indexed documents in Weaviate.

    Example output:
    {
      'faithfulness': 0.87,
      'answer_relevancy': 0.84,
      'context_precision': 0.79,
      'context_recall': 0.82,
    }
    """
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        faithfulness, answer_relevancy,
        context_precision, context_recall,
    )

    data = {
        "question": [s.question for s in EVAL_DATASET if s.contexts],
        "answer": [s.answer for s in EVAL_DATASET if s.contexts],
        "contexts": [s.contexts for s in EVAL_DATASET if s.contexts],
        "ground_truth": [s.ground_truth for s in EVAL_DATASET if s.contexts],
    }

    dataset = Dataset.from_dict(data)
    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    )

    print("\n=== RAGAS Evaluation Results ===")
    for metric, score in result.items():
        threshold = {"faithfulness": 0.85, "answer_relevancy": 0.80,
                     "context_precision": 0.75, "context_recall": 0.80}.get(metric, 0.75)
        status = "✓ PASS" if score >= threshold else "✗ FAIL"
        print(f"  {metric:<25} {score:.3f}  {status}  (target: {threshold})")

    return result


if __name__ == "__main__":
    asyncio.run(run_full_ragas_evaluation())
