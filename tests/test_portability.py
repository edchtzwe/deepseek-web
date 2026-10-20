"""Guard rail: this package ships to every agent runtime, so it must not name one.

The tool is distributed as a portable skill and a CLI. Any reference to a
specific agent or runtime inside ``deepseek_web/`` makes the package partial
and dates it. Deployment notes belong in the docs (or the operator's local
notes), never in the code.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "deepseek_web"

#: Agent runtimes, assistant products, and vendors. Extend when one creeps in.
FORBIDDEN = re.compile(
    r"zeroclaw|openclaw|claude|anthropic|chatgpt|openai|copilot|gemini|"
    r"cursor|windsurf|aider|langchain|dify|hermes",
    re.IGNORECASE,
)


class PortabilityTests(unittest.TestCase):
    def test_package_does_not_name_an_agent_runtime(self):
        offences = []
        for path in sorted(PACKAGE.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), 1):
                match = FORBIDDEN.search(line)
                if match:
                    offences.append(
                        f"{path.relative_to(PACKAGE.parent)}:{number}: {match.group(0)!r}"
                    )
        self.assertEqual(
            offences,
            [],
            "vendor/agent names leaked into the package:\n" + "\n".join(offences),
        )

    def test_package_does_not_read_foreign_config_files(self):
        """Resolving a key must never open another tool's config."""
        forbidden_calls = ("config.toml", ".zeroclaw", "ZEROCLAW_CONFIG")
        offences = []
        for path in sorted(PACKAGE.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in forbidden_calls:
                if token.lower() in text.lower():
                    offences.append(f"{path.name}: {token}")
        self.assertEqual(offences, [])


if __name__ == "__main__":
    unittest.main()
