"""Extra analyses run during an audit, after keywords/performance and before checks.

Each enricher stores its result in `ctx.extras[...]` for checks and reports to consume.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from seoforge.checks.base import AuditContext
    from seoforge.http import PoliteClient
    from seoforge.storage import Store

EnricherFn = Callable[["AuditContext", "PoliteClient", "Store", Any], Awaitable[None]]
ENRICHERS: list[tuple[str, EnricherFn]] = []
