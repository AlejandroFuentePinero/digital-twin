"""Always-on profile loader (the Frame, per ADR-0001 / ADR-0003).

Parses `data/profile.md` into named `##` sections. Branches load only the
sections they need via `BranchSpec.profile_sections`.
"""

from pathlib import Path

DEFAULT_PROFILE_PATH = Path(__file__).parent.parent / "data" / "profile.md"


class ProfileLoader:
    def __init__(self, path: Path = DEFAULT_PROFILE_PATH):
        text = Path(path).read_text()
        self._sections = self._parse(text)
        if not self._sections:
            raise ValueError(f"profile at {path} contains no `## ` sections")

    @staticmethod
    def _parse(text: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        current_name: str | None = None
        current_body: list[str] = []
        for line in text.splitlines():
            if line.startswith("## "):
                if current_name is not None:
                    sections[current_name] = "\n".join(current_body).strip()
                name = line[3:].strip()
                if name in sections:
                    raise ValueError(f"duplicate `## {name}` heading in profile")
                current_name = name
                current_body = []
            elif current_name is not None:
                current_body.append(line)
        if current_name is not None:
            sections[current_name] = "\n".join(current_body).strip()
        return sections

    def section(self, name: str) -> str:
        return self._sections[name]
