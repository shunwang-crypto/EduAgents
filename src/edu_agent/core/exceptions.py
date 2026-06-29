class EduAgentError(Exception):
    """Base exception for the education agent application."""


class LLMConfigurationError(EduAgentError):
    """Raised when the LLM cannot be configured."""


class WorkflowStepError(EduAgentError):
    """Raised when a workflow step fails."""
