"""
integrations/linear_integration.py
Linear.app adapter for Aegis using the GraphQL API.

Credentials:
  api_key        — Linear API key (lin_api_...)
  webhook_secret — (optional) signing secret for HMAC-SHA256 webhook verification

Filters:
  team_id        — Linear team UUID (find via: query { teams { nodes { id name } } })
"""
import hashlib
import hmac
from typing import Optional

import httpx

from .base import BaseIntegration

_ENDPOINT = "https://api.linear.app/graphql"

_ISSUES_QUERY = """
query GetIssues($teamId: String!, $after: String) {
  issues(
    filter: { team: { id: { eq: $teamId } }, state: { type: { nin: ["completed", "cancelled"] } } }
    after: $after
    first: 50
  ) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      description
      url
      priority
      state { name type }
    }
  }
}
"""

_DONE_STATE_QUERY = """
query GetDoneState($teamId: String!) {
  workflowStates(
    filter: { team: { id: { eq: $teamId } }, type: { eq: completed } }
  ) {
    nodes { id name }
  }
}
"""

_UPDATE_MUTATION = """
mutation UpdateIssue($id: String!, $stateId: String!) {
  issueUpdate(id: $id, input: { stateId: $stateId }) {
    success
  }
}
"""

# Linear priority mapping: 0=No priority, 1=Urgent, 2=High, 3=Medium, 4=Low
_PRIORITY_MAP = {0: "normal", 1: "high", 2: "high", 3: "normal", 4: "low"}


class LinearIntegration(BaseIntegration):
    SOURCE = "linear"

    def _headers(self) -> dict:
        return {
            "Authorization": self.credentials.get("api_key", ""),
            "Content-Type": "application/json",
        }

    async def _gql(self, query: str, variables: dict = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _ENDPOINT,
                headers=self._headers(),
                json={"query": query, "variables": variables or {}},
            )
            resp.raise_for_status()
            return resp.json()

    # ── sync_in ──────────────────────────────────────────────────────────────

    async def sync_in(self) -> list:
        team_id = self.filters.get("team_id", "")
        results = []
        cursor = None

        while True:
            data = await self._gql(_ISSUES_QUERY, {"teamId": team_id, "after": cursor})
            issues_data = data.get("data", {}).get("issues", {})
            for issue in issues_data.get("nodes", []):
                priority = _PRIORITY_MAP.get(issue.get("priority", 0), "normal")
                card = await self._upsert_card(
                    external_id=issue["id"],
                    external_source=self.SOURCE,
                    external_url=issue.get("url", ""),
                    title=f"[Linear] {issue['title']}",
                    description=self._build_description(issue),
                    priority=priority,
                )
                results.append(card)

            page_info = issues_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        return results

    # ── sync_out ─────────────────────────────────────────────────────────────

    async def sync_out(self, card: dict, event_type: str) -> bool:
        if card.get("external_source") != self.SOURCE:
            return False
        issue_id = card.get("external_id")
        if not issue_id:
            return False

        if event_type == "card_moved" and card.get("column") == "Done":
            team_id = self.filters.get("team_id", "")
            state_data = await self._gql(_DONE_STATE_QUERY, {"teamId": team_id})
            states = state_data.get("data", {}).get("workflowStates", {}).get("nodes", [])
            if not states:
                self.logger.warning(f"No completed workflow state found for team {team_id}")
                return False
            done_state_id = states[0]["id"]
            result = await self._gql(_UPDATE_MUTATION, {"id": issue_id, "stateId": done_state_id})
            return result.get("data", {}).get("issueUpdate", {}).get("success", False)

        return False

    # ── handle_webhook ───────────────────────────────────────────────────────

    async def handle_webhook(self, payload: dict, headers: dict) -> Optional[dict]:
        secret = self.credentials.get("webhook_secret", "")
        sig = headers.get("linear-signature", "")
        if secret and sig:
            raw_body = headers.get("_raw_body", b"")
            if isinstance(raw_body, str):
                raw_body = raw_body.encode()
            expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, sig):
                self.logger.warning("Linear webhook signature mismatch — ignoring")
                return None

        action = payload.get("action")
        issue = payload.get("data", {})
        if not issue or action not in ("create", "update"):
            return None

        priority = _PRIORITY_MAP.get(issue.get("priority", 0), "normal")
        return await self._upsert_card(
            external_id=issue.get("id", ""),
            external_source=self.SOURCE,
            external_url=issue.get("url", ""),
            title=f"[Linear] {issue.get('title', '')}",
            description=issue.get("description") or "",
            priority=priority,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_description(self, issue: dict) -> str:
        body = issue.get("description") or ""
        url = issue.get("url", "")
        state = issue.get("state", {}).get("name", "")
        parts = [body]
        if state:
            parts.append(f"\n**State:** {state}")
        if url:
            parts.append(f"\n\nLinear Issue: {url}")
        return "\n".join(parts).strip()
