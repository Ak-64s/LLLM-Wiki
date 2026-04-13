"""Page proposal data structures and slug generation. Contract: contracts/s-4-batch-proposal.contract.md"""

import hashlib
import re
from dataclasses import dataclass, field


@dataclass
class Conflict:
    existing_page: str
    description: str
    source_ref: str


@dataclass
class PageProposal:
    title: str
    slug: str
    category: str
    content: str
    action: str
    conflicts: list[Conflict] = field(default_factory=list)
    existing_path: str = ""


def slugify(title: str) -> str:
    slug = title.strip()
    if not slug:
        raise ValueError("Title must be non-empty.")

    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9\s-]", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    slug = slug.replace(" ", "-")
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")

    if not slug:
        raise ValueError("Title must produce a non-empty slug.")

    return slug


def resolve_collision(slug: str, existing_slugs: set[str]) -> str:
    if slug not in existing_slugs:
        return slug
    h = hashlib.sha256(slug.encode()).hexdigest()[:8]
    return f"{slug}-{h}"
