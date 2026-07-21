from __future__ import annotations

import re
from pathlib import Path


PATTERNS = {
    "private-key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "github-token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "generic-secret": re.compile(r"(?i)(?:api[_-]?key|secret|password)\s*=\s*['\"][^'\"]{8,}"),
}
SKIP = {".git", ".runtime", ".venv", "venv", "__pycache__"}


def main() -> None:
    findings = []
    for path in Path(".").rglob("*"):
        if not path.is_file() or any(part in SKIP for part in path.parts):
            continue
        if path.stat().st_size > 1_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append(f"{path}:{text.count(chr(10), 0, match.start()) + 1}:{name}")
    if findings:
        raise SystemExit("Potential secrets found:\n" + "\n".join(findings))
    print("security scan passed")


if __name__ == "__main__":
    main()
