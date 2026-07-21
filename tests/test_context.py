from agentic_sdlc_runtime.context import ContextBuilder
from agentic_sdlc_runtime.models import ContextSource


def test_context_filters_classification_and_preserves_provenance():
    envelope = ContextBuilder("internal").build(
        "payments", "CHG-1001", "refine", ["testable"],
        [
            ContextSource("repo://public", "allowed", "public"),
            ContextSource("vault://restricted", "secret", "restricted"),
        ],
        max_chars=100,
    )
    assert "allowed" in envelope.rendered
    assert "secret" not in envelope.rendered
    assert envelope.sources[0]["uri"] == "repo://public"
    assert len(envelope.sources[0]["sha256"]) == 64
    assert len(envelope.digest) == 64
