from copy import deepcopy

import pytest

from workbench_agent.errors import ResearchResultValidationError
from workbench_agent.research.models import ResearchResult


def valid_result() -> dict[str, object]:
    return {
        "schema_version": "1",
        "task_key": "d2nn-recent-papers",
        "run_key": "d2nn-recent-papers-20260829T091500Z-a31f42",
        "generated_at": "2026-08-29T09:15:00Z",
        "agent": {
            "type": "codex",
            "model": "gpt-5",
            "prompt_version": "paper_research_v1",
        },
        "query_plan": ["diffractive neural network 2026"],
        "papers": [
            {
                "title": "Verified paper",
                "authors": ["A. Author"],
                "doi": "10.1000/example",
                "arxiv_id": None,
                "openalex_id": None,
                "published_at": "2026-08-20",
                "venue": "Example Journal",
                "url": "https://doi.org/10.1000/example",
                "pdf_url": None,
                "abstract": "Abstract",
                "topics": ["diffractive neural networks"],
                "ai_summary": "Problem, method, innovation, results, and limits.",
                "recommendation_reason": "Directly informs the task.",
                "relevance_score": 0.95,
                "novelty_score": 0.82,
                "relationship_to_library": None,
                "source": {"provider": "publisher", "source_id": "10.1000/example"},
            }
        ],
    }


def parse(data: object, max_results: int = 5) -> ResearchResult:
    return ResearchResult.from_payload(
        data, task_key="d2nn-recent-papers", max_results=max_results
    )


def test_valid_result_round_trips_to_ingest_payload() -> None:
    data = valid_result()

    assert parse(data).to_payload() == data


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("schema_version", "2", "schema_version"),
        ("task_key", "other", "task_key"),
        ("generated_at", "2026-08-29T09:15:00", "timezone"),
    ],
)
def test_root_contract_validation(field: str, value: object, match: str) -> None:
    data = valid_result()
    data[field] = value

    with pytest.raises(ResearchResultValidationError, match=match):
        parse(data)


def test_too_many_papers_is_rejected() -> None:
    data = valid_result()
    data["papers"] = data["papers"] * 2  # type: ignore[operator]

    with pytest.raises(ResearchResultValidationError, match="at most"):
        parse(data, max_results=1)


@pytest.mark.parametrize("field", ["relevance_score", "novelty_score"])
def test_invalid_score_is_rejected(field: str) -> None:
    data = valid_result()
    data["papers"][0][field] = 1.1  # type: ignore[index]

    with pytest.raises(ResearchResultValidationError, match=field):
        parse(data)


@pytest.mark.parametrize("field", ["title", "recommendation_reason"])
def test_required_paper_text_is_rejected(field: str) -> None:
    data = valid_result()
    data["papers"][0][field] = ""  # type: ignore[index]

    with pytest.raises(ResearchResultValidationError, match=field):
        parse(data)


def test_paper_requires_url_or_identifier() -> None:
    data = deepcopy(valid_result())
    paper = data["papers"][0]  # type: ignore[index]
    for field in ("url", "doi", "arxiv_id", "openalex_id"):
        paper[field] = None

    with pytest.raises(ResearchResultValidationError, match="URL, DOI"):
        parse(data)


def test_invalid_url_is_rejected() -> None:
    data = valid_result()
    data["papers"][0]["url"] = "doi.org/10.1000/example"  # type: ignore[index]

    with pytest.raises(ResearchResultValidationError, match="absolute"):
        parse(data)


@pytest.mark.parametrize(
    "field,value,label",
    [
        ("doi", "not-a-doi", "DOI"),
        ("arxiv_id", "not-arxiv", "arXiv"),
        ("openalex_id", "123", "OpenAlex"),
    ],
)
def test_invalid_identifiers_are_rejected(field: str, value: str, label: str) -> None:
    data = valid_result()
    data["papers"][0][field] = value  # type: ignore[index]

    with pytest.raises(ResearchResultValidationError, match=label):
        parse(data)


def test_query_plan_must_not_be_empty() -> None:
    data = valid_result()
    data["query_plan"] = []

    with pytest.raises(ResearchResultValidationError, match="query_plan"):
        parse(data)
