"""Prompt-injection screening for anything a caller says before it reaches an LLM."""

import re

PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) (instructions|rules|prompts?)",
    r"(system|developer) prompt",
    r"you are now",
    r"act as (an? )?(admin|developer|owner)",
    r"(set|change|make) (the )?(price|total|amount)",
    r"(free|zero dollars|\$0|no charge)",
    r"(refund|pay|send) (me|money) .*(paypal|account)",
    r"reveal .*(secret|key|token|password)",
    r"</?(system|assistant|tool)>",
]
_RX = re.compile("|".join(PATTERNS), re.I)


def screen(text: str) -> tuple[str, bool]:
    """Return (safe text, flagged). Flagged input is still answered, but the LLM is told it is untrusted."""
    text = text.replace("\x00", "")[:600]
    return text, bool(_RX.search(text))
