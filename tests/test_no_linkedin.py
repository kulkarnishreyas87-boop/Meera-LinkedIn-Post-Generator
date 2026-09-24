"""Guardrail: the app must never post to LinkedIn. No LinkedIn client, API host or OAuth anywhere in code."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE_DIRS = [ROOT / "app", ROOT / "web" / "src"]
FORBIDDEN = [
    r"api\.linkedin\.com",
    r"linkedin\.com/oauth",
    r"ugcPosts",
    r"/v2/shares",
    r"/rest/posts",
    r"import\s+linkedin",
    r"from\s+linkedin",
    r"linkedin[-_]api",
]


def test_no_linkedin_publishing_code():
    hits = []
    for d in CODE_DIRS:
        if not d.exists():
            continue
        for path in d.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx", ".js"} or "node_modules" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            hits += [f"{path.relative_to(ROOT)}: {p}" for p in FORBIDDEN if re.search(p, text, re.IGNORECASE)]
    assert not hits, "LinkedIn publishing code found:\n" + "\n".join(hits)


def test_no_linkedin_dependency():
    deps = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "linkedin" not in deps.split("[project.scripts]")[0].split("dependencies")[1]
    pkg = ROOT / "web" / "package.json"
    if pkg.exists():
        assert "linkedin" not in pkg.read_text(encoding="utf-8").lower()
