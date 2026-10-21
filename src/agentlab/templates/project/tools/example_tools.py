"""Custom tools. Every .py file in tools/ is loaded automatically.

Type hints become the JSON schema; the first docstring paragraph is the
description the model sees; the Args: section describes each parameter.
Return a string (anything else is converted with str()).
"""

from datetime import datetime

from agentlab import tool


@tool
def current_time() -> str:
    """Get the current local date and time."""
    return datetime.now().isoformat(timespec="seconds")


@tool
def word_count(text: str) -> str:
    """Count the words and characters in a piece of text.

    Args:
        text: the text to count
    """
    return f"{len(text.split())} words, {len(text)} characters"
