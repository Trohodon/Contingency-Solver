from __future__ import annotations

from contingency_solver.models.branch import Branch


class BranchService:
    def __init__(self, branches: list[Branch]) -> None:
        self.branches = branches

    def existing_connection_pairs(self) -> set[tuple[int, int]]:
        return {branch.normalized_pair for branch in self.branches if branch.in_service}

    def has_existing_direct_branch(self, from_bus: int, to_bus: int) -> bool:
        return tuple(sorted((from_bus, to_bus))) in self.existing_connection_pairs()
