from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class ConferenceEntry:
    title: str
    dates: str = ""
    location: str = ""
    registration_deadline: str = ""
    preregistration_deadline: str = ""
    abstract_deadline: str = ""
    details: str = ""
    url: str = ""
    llm_reason: str = ""

    @property
    def cache_key(self) -> str:
        raw = " | ".join(
            part.strip().lower()
            for part in (
                self.title,
                self.dates,
                self.location,
                self.registration_deadline,
                self.preregistration_deadline,
                self.abstract_deadline,
            )
        )
        return sha256(raw.encode("utf-8")).hexdigest()[:16]
