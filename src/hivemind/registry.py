"""Maintain stable, project-scoped agent identities like a small HR directory.

When the same role key appears in a later run, the registry reuses its profile and history.
No reputation algorithm chooses agents; the rule is a simple project-and-role lookup.
"""

from __future__ import annotations

from hivemind.persistence import HiveMindRepository
from hivemind.schemas import AgentKind, AgentProfile, AgentStatus, utc_now


class AgentRegistry:
    """Create or reuse stable agent profiles through the repository."""

    def __init__(self, repository: HiveMindRepository | None = None) -> None:
        self.repository = repository

    async def create_or_get(
        self,
        *,
        project_id: str,
        role_key: str,
        name: str,
        kind: AgentKind,
        role_description: str,
        parent_agent_id: str | None = None,
        status: AgentStatus = AgentStatus.CREATED,
    ) -> AgentProfile:
        """Reuse one project role or create it when first requested."""

        existing = (
            await self.repository.find_agent(project_id, role_key) if self.repository else None
        )
        if existing and existing.kind != kind:
            # A model-generated role key is data, not an identity grant. Keep the existing
            # role intact and deterministically namespace the new kind instead of mutating
            # (for example) a manager into a worker with the same database ID.
            base_role_key = f"{role_key}-{kind.value.replace('_', '-')}"
            role_key = base_role_key
            suffix = 2
            existing = await self.repository.find_agent(project_id, role_key)
            while existing and existing.kind != kind:
                role_key = f"{base_role_key}-{suffix}"
                suffix += 1
                existing = await self.repository.find_agent(project_id, role_key)
        if existing:
            existing.name = name
            existing.kind = kind
            existing.role_description = role_description
            existing.parent_agent_id = parent_agent_id
            existing.status = status
            existing.last_used_at = utc_now()
            if self.repository:
                await self.repository.save_agent(existing)
            return existing
        profile = AgentProfile(
            project_id=project_id,
            role_key=role_key,
            name=name,
            kind=kind,
            role_description=role_description,
            parent_agent_id=parent_agent_id,
            status=status,
        )
        if self.repository:
            await self.repository.save_agent(profile)
        return profile

    async def save(self, agent: AgentProfile) -> None:
        """Persist changed status and task counters when storage is configured."""

        agent.last_used_at = utc_now()
        if self.repository:
            await self.repository.save_agent(agent)
