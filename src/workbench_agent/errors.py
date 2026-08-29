class AgentError(Exception):
    """Base error expected by the command-line interface."""


class AgentConfigError(AgentError):
    """Configuration is missing or invalid."""


class WorkbenchConnectionError(AgentError):
    """The Workbench server could not be reached."""


class WorkbenchAuthenticationError(AgentError):
    """The Workbench server rejected authentication."""


class WorkbenchApiError(AgentError):
    """The Workbench server returned an unexpected response."""


class ManifestValidationError(AgentError):
    """A run manifest does not satisfy the v0.1 contract."""


class ResearchTaskError(AgentError):
    """A paper research task is missing or invalid."""


class CodexExecutionError(AgentError):
    """Codex could not produce a structured research result."""


class ResearchResultValidationError(AgentError):
    """A Codex research result does not satisfy ingest schema v1."""
