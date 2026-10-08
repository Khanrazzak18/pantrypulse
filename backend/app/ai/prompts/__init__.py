from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Read a prompt from app/ai/prompts/<name>.md."""
    return (_DIR / f"{name}.md").read_text(encoding="utf-8")
