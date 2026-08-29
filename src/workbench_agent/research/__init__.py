"""Paper research capability for Personal Workbench Agent."""

from .models import ResearchResult
from .task import ResearchTask, load_research_task

__all__ = ["ResearchResult", "ResearchTask", "load_research_task"]
