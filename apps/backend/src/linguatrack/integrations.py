from typing import Literal, Protocol

from linguatrack.schemas import BridgeContext


class SourceEnvelope(BridgeContext):
    provider: Literal["manual", "zoom", "meet", "duolingo", "mcp"]
    external_event_id: str | None = None
    language_tag: str
    text: str


class SourceAdapter(Protocol):
    def normalize(self, payload: dict) -> SourceEnvelope: ...


class ManualAdapter:
    def normalize(self, payload: dict) -> SourceEnvelope:
        return SourceEnvelope(provider="manual", **payload)


class PlannedAdapter:
    def __init__(self, provider: str):
        self.provider = provider

    def normalize(self, payload: dict) -> SourceEnvelope:
        raise NotImplementedError(f"{self.provider} integration is not implemented")


ADAPTERS: dict[str, SourceAdapter] = {
    "manual": ManualAdapter(),
    **{name: PlannedAdapter(name) for name in ("zoom", "meet", "duolingo", "mcp")},
}


def capabilities():
    return [
        {
            "provider": name,
            "enabled": name == "manual",
            "status": "available" if name == "manual" else "planned",
        }
        for name in ADAPTERS
    ]
