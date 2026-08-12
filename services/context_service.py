"""Explicit conversation context (Detailed Build Specification section 7.9).

The context is a small explicit object owned by the application - never a
transcript-dependent assumption or provider-side memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from models.ai_contracts import ContextUpdates


@dataclass
class ConversationContext:
    current_review_id: str
    comparison_review_ids: list[str] = field(default_factory=list)
    active_filters: list[dict] = field(default_factory=list)
    last_group_by: list[str] = field(default_factory=list)
    last_measure: str | None = None
    last_dataset: str | None = None

    def to_payload(self) -> dict:
        return {
            "current_review_id": self.current_review_id,
            "comparison_review_ids": list(self.comparison_review_ids),
            "active_filters": {f"{f['field']}": f.get("value")
                               for f in self.active_filters},
            "last_group_by": list(self.last_group_by) or None,
            "last_measure": self.last_measure,
            "last_dataset": self.last_dataset,
        }

    def reset_filters(self) -> None:
        self.comparison_review_ids = []
        self.active_filters = []
        self.last_group_by = []
        self.last_measure = None
        self.last_dataset = None


def apply_updates(ctx: ConversationContext, updates: ContextUpdates,
                  allow_review_switch: bool = False) -> ConversationContext:
    """Apply planner context updates. The selected review is owned by the UI
    selector; a planner-proposed switch is applied only when explicitly
    allowed."""
    if allow_review_switch and updates.current_review_id:
        ctx.current_review_id = updates.current_review_id
    if updates.comparison_review_ids:
        ctx.comparison_review_ids = [r for r in updates.comparison_review_ids
                                     if r != ctx.current_review_id]
    if updates.active_filters:
        ctx.active_filters = [f.model_dump() for f in updates.active_filters]
    if updates.last_group_by:
        ctx.last_group_by = list(updates.last_group_by)
    if updates.last_measure:
        ctx.last_measure = updates.last_measure
    if updates.last_dataset:
        ctx.last_dataset = updates.last_dataset
    return ctx
