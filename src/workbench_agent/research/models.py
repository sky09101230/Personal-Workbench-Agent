from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Mapping
from urllib.parse import urlsplit

from ..errors import ResearchResultValidationError


@dataclass(frozen=True)
class ResearchAgentInfo:
    type: str
    model: str
    prompt_version: str

    def to_payload(self) -> dict[str, object]:
        return {
            "type": self.type,
            "model": self.model,
            "prompt_version": self.prompt_version,
        }


@dataclass(frozen=True)
class ResearchSource:
    provider: str
    source_id: str

    def to_payload(self) -> dict[str, object]:
        return {"provider": self.provider, "source_id": self.source_id}


@dataclass(frozen=True)
class ResearchPaper:
    title: str
    authors: tuple[str, ...]
    doi: str | None
    arxiv_id: str | None
    openalex_id: str | None
    published_at: str | None
    venue: str | None
    url: str | None
    pdf_url: str | None
    abstract: str | None
    topics: tuple[str, ...]
    ai_summary: str
    recommendation_reason: str
    relevance_score: float | None
    novelty_score: float | None
    relationship_to_library: str | None
    source: ResearchSource

    def to_payload(self) -> dict[str, object]:
        return {
            "title": self.title,
            "authors": list(self.authors),
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "openalex_id": self.openalex_id,
            "published_at": self.published_at,
            "venue": self.venue,
            "url": self.url,
            "pdf_url": self.pdf_url,
            "abstract": self.abstract,
            "topics": list(self.topics),
            "ai_summary": self.ai_summary,
            "recommendation_reason": self.recommendation_reason,
            "relevance_score": self.relevance_score,
            "novelty_score": self.novelty_score,
            "relationship_to_library": self.relationship_to_library,
            "source": self.source.to_payload(),
        }


@dataclass(frozen=True)
class ResearchResult:
    schema_version: str
    task_key: str
    run_key: str
    generated_at: str
    agent: ResearchAgentInfo
    query_plan: tuple[str, ...]
    papers: tuple[ResearchPaper, ...]

    @classmethod
    def from_payload(
        cls,
        value: object,
        *,
        task_key: str,
        max_results: int,
    ) -> ResearchResult:
        root = _strict_object(
            value,
            "result",
            {
                "schema_version",
                "task_key",
                "run_key",
                "generated_at",
                "agent",
                "query_plan",
                "papers",
            },
        )
        schema_version = _required_string(root, "schema_version")
        if schema_version != "1":
            raise ResearchResultValidationError("schema_version must be '1'")
        actual_task_key = _required_string(root, "task_key")
        if actual_task_key != task_key:
            raise ResearchResultValidationError(
                f"task_key must match current task {task_key!r}"
            )
        generated_at = _aware_datetime(root, "generated_at")

        agent_raw = _strict_object(
            root.get("agent"), "agent", {"type", "model", "prompt_version"}
        )
        agent = ResearchAgentInfo(
            type=_required_string(agent_raw, "type"),
            model=_required_string(agent_raw, "model"),
            prompt_version=_required_string(agent_raw, "prompt_version"),
        )
        if agent.type != "codex":
            raise ResearchResultValidationError("agent.type must be 'codex'")
        if agent.prompt_version != "paper_research_v1":
            raise ResearchResultValidationError(
                "agent.prompt_version must be 'paper_research_v1'"
            )

        query_plan = _string_array(root, "query_plan")
        if not query_plan:
            raise ResearchResultValidationError("query_plan must not be empty")
        papers_raw = root.get("papers")
        if not isinstance(papers_raw, list):
            raise ResearchResultValidationError("papers must be a JSON array")
        if len(papers_raw) > max_results:
            raise ResearchResultValidationError(
                f"papers must contain at most {max_results} items"
            )
        papers = tuple(_paper(item, index) for index, item in enumerate(papers_raw))
        return cls(
            schema_version=schema_version,
            task_key=actual_task_key,
            run_key=_required_string(root, "run_key"),
            generated_at=generated_at,
            agent=agent,
            query_plan=query_plan,
            papers=papers,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_key": self.task_key,
            "run_key": self.run_key,
            "generated_at": self.generated_at,
            "agent": self.agent.to_payload(),
            "query_plan": list(self.query_plan),
            "papers": [paper.to_payload() for paper in self.papers],
        }


def _strict_object(
    value: object, label: str, fields: set[str]
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ResearchResultValidationError(f"{label} must be a JSON object")
    unknown = sorted(set(value) - fields)
    if unknown:
        raise ResearchResultValidationError(
            f"Unknown {label} field(s): {', '.join(unknown)}"
        )
    return value


def _required_string(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ResearchResultValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ResearchResultValidationError(f"{field} must be a non-empty string or null")
    return value.strip()


def _string_array(data: Mapping[str, object], field: str) -> tuple[str, ...]:
    value = data.get(field)
    if not isinstance(value, list):
        raise ResearchResultValidationError(f"{field} must be a JSON array")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ResearchResultValidationError(
                f"{field}[{index}] must be a non-empty string"
            )
        result.append(item.strip())
    return tuple(result)


def _aware_datetime(data: Mapping[str, object], field: str) -> str:
    value = _required_string(data, field)
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ResearchResultValidationError(
            f"{field} must be a valid ISO 8601 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchResultValidationError(f"{field} must include a timezone offset")
    return value


def _url(data: Mapping[str, object], field: str) -> str | None:
    value = _optional_string(data, field)
    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ResearchResultValidationError(f"{field} must be an absolute http(s) URL")
    return value


def _score(data: Mapping[str, object], field: str) -> float | None:
    value = data.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResearchResultValidationError(f"{field} must be a number or null")
    score = float(value)
    if not 0 <= score <= 1:
        raise ResearchResultValidationError(f"{field} must be between 0 and 1")
    return score


def _identifier(
    data: Mapping[str, object], field: str, pattern: str, label: str
) -> str | None:
    value = _optional_string(data, field)
    if value is not None and re.fullmatch(pattern, value, re.IGNORECASE) is None:
        raise ResearchResultValidationError(f"{field} must be a valid {label}")
    return value


def _paper(value: object, index: int) -> ResearchPaper:
    label = f"papers[{index}]"
    raw = _strict_object(
        value,
        label,
        {
            "title",
            "authors",
            "doi",
            "arxiv_id",
            "openalex_id",
            "published_at",
            "venue",
            "url",
            "pdf_url",
            "abstract",
            "topics",
            "ai_summary",
            "recommendation_reason",
            "relevance_score",
            "novelty_score",
            "relationship_to_library",
            "source",
        },
    )
    source_raw = _strict_object(
        raw.get("source"), f"{label}.source", {"provider", "source_id"}
    )
    url = _url(raw, "url")
    doi = _identifier(raw, "doi", r"10\.\d{4,9}/\S+", "DOI")
    arxiv_id = _identifier(
        raw,
        "arxiv_id",
        r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?",
        "arXiv ID",
    )
    openalex_id = _identifier(
        raw,
        "openalex_id",
        r"(?:https?://openalex\.org/)?W\d+",
        "OpenAlex ID",
    )
    if not any((url, doi, arxiv_id, openalex_id)):
        raise ResearchResultValidationError(
            f"{label} requires a valid URL, DOI, arXiv ID, or OpenAlex ID"
        )
    return ResearchPaper(
        title=_required_string(raw, "title"),
        authors=_string_array(raw, "authors"),
        doi=doi,
        arxiv_id=arxiv_id,
        openalex_id=openalex_id,
        published_at=_optional_string(raw, "published_at"),
        venue=_optional_string(raw, "venue"),
        url=url,
        pdf_url=_url(raw, "pdf_url"),
        abstract=_optional_string(raw, "abstract"),
        topics=_string_array(raw, "topics"),
        ai_summary=_required_string(raw, "ai_summary"),
        recommendation_reason=_required_string(raw, "recommendation_reason"),
        relevance_score=_score(raw, "relevance_score"),
        novelty_score=_score(raw, "novelty_score"),
        relationship_to_library=_optional_string(raw, "relationship_to_library"),
        source=ResearchSource(
            provider=_required_string(source_raw, "provider"),
            source_id=_required_string(source_raw, "source_id"),
        ),
    )


def research_result_schema(max_results: int) -> dict[str, object]:
    nullable_string = {"type": ["string", "null"]}
    score = {"type": ["number", "null"], "minimum": 0, "maximum": 1}
    string_array = {"type": "array", "items": {"type": "string"}}
    paper_properties = {
        "title": {"type": "string"},
        "authors": string_array,
        "doi": nullable_string,
        "arxiv_id": nullable_string,
        "openalex_id": nullable_string,
        "published_at": nullable_string,
        "venue": nullable_string,
        "url": nullable_string,
        "pdf_url": nullable_string,
        "abstract": nullable_string,
        "topics": string_array,
        "ai_summary": {"type": "string"},
        "recommendation_reason": {"type": "string"},
        "relevance_score": score,
        "novelty_score": score,
        "relationship_to_library": nullable_string,
        "source": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "provider": {"type": "string"},
                "source_id": {"type": "string"},
            },
            "required": ["provider", "source_id"],
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "const": "1"},
            "task_key": {"type": "string"},
            "run_key": {"type": "string"},
            "generated_at": {"type": "string"},
            "agent": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "const": "codex"},
                    "model": {"type": "string"},
                    "prompt_version": {
                        "type": "string",
                        "const": "paper_research_v1",
                    },
                },
                "required": ["type", "model", "prompt_version"],
            },
            "query_plan": string_array,
            "papers": {
                "type": "array",
                "maxItems": max_results,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": paper_properties,
                    "required": list(paper_properties),
                },
            },
        },
        "required": [
            "schema_version",
            "task_key",
            "run_key",
            "generated_at",
            "agent",
            "query_plan",
            "papers",
        ],
    }
