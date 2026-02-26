"""
integrations/jira_integration.py
Jira Cloud adapter for Aegis.

Credentials:
  email        — Jira account email
  token        — Jira API token (https://id.atlassian.com/manage-profile/security/api-tokens)
  base_url     — e.g. "https://company.atlassian.net"
  webhook_secret — (optional) Authorization header value expected on inbound webhooks

Filters:
  project_key  — Jira project key, e.g. "PROJ"
  jql_extra    — additional JQL appended to the base query, e.g. "priority = High"
"""
import base64
from typing import Optional

import httpx

from .base import BaseIntegration


def _adf_to_text(adf: dict) -> str:
    """Minimal Atlassian Document Format → plain text extractor."""
    parts = []

    def walk(node: dict):
        if node.get("type") == "text":
            parts.append(node.get("text", ""))
        for child in node.get("content", []):
            walk(child)

    walk(adf)
    return " ".join(parts)


class JiraIntegration(BaseIntegration):
    SOURCE = "jira"

    def _headers(self) -> dict:
        raw = f"{self.credentials['email']}:{self.credentials['token']}"
        b64 = base64.b64encode(raw.encode()).decode()
        return {
            "Authorization": f"Basic {b64}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _base(self) -> str:
        return self.credentials.get("base_url", "").rstrip("/")

    # ── sync_in ──────────────────────────────────────────────────────────────

    async def sync_in(self) -> list:
        project = self.filters.get("project_key", "")
        jql_extra = self.filters.get("jql_extra", "")
        jql = f'project = "{project}" AND statusCategory != Done'
        if jql_extra:
            jql += f" AND {jql_extra}"

        results = []
        start = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                resp = await client.get(
                    f"{self._base()}/rest/api/3/search",
                    headers=self._headers(),
                    params={
                        "jql": jql,
                        "fields": "summary,description,status,priority",
                        "startAt": start,
                        "maxResults": 100,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                issues = data.get("issues", [])
                if not issues:
                    break

                for issue in issues:
                    key = issue["key"]
                    fields = issue.get("fields", {})
                    raw_desc = fields.get("description") or ""
                    description = _adf_to_text(raw_desc) if isinstance(raw_desc, dict) else raw_desc
                    priority_raw = (fields.get("priority") or {}).get("name", "normal")

                    card = await self._upsert_card(
                        external_id=key,
                        external_source=self.SOURCE,
                        external_url=f"{self._base()}/browse/{key}",
                        title=f"[{key}] {fields.get('summary', '')}",
                        description=f"{description}\n\nJira: {self._base()}/browse/{key}".strip(),
                        priority=self._map_priority(priority_raw),
                    )
                    results.append(card)

                start += len(issues)
                if start >= data.get("total", 0):
                    break
        return results

    # ── sync_out ─────────────────────────────────────────────────────────────

    async def sync_out(self, card: dict, event_type: str) -> bool:
        if card.get("external_source") != self.SOURCE:
            return False
        key = card.get("external_id")
        if not key:
            return False

        async with httpx.AsyncClient(timeout=20) as client:
            if event_type == "card_moved" and card.get("column") == "Done":
                # Find a transition that leads to a "done" status category
                resp = await client.get(
                    f"{self._base()}/rest/api/3/issue/{key}/transitions",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                transitions = resp.json().get("transitions", [])
                done_id = next(
                    (t["id"] for t in transitions
                     if t.get("to", {}).get("statusCategory", {}).get("key") == "done"),
                    None,
                )
                if not done_id:
                    self.logger.warning(f"No 'done' transition found for {key}")
                    return False
                resp2 = await client.post(
                    f"{self._base()}/rest/api/3/issue/{key}/transitions",
                    headers=self._headers(),
                    json={"transition": {"id": done_id}},
                )
                return resp2.status_code == 204

            if event_type == "comment_added":
                comments = card.get("comments", [])
                if not comments:
                    return False
                latest = comments[-1]
                text = f"[Aegis — {latest.get('author', 'unknown')}]: {latest.get('content', '')}"
                # Jira API v3 requires Atlassian Document Format for comment body
                adf_body = {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": text}],
                        }
                    ],
                }
                resp = await client.post(
                    f"{self._base()}/rest/api/3/issue/{key}/comment",
                    headers=self._headers(),
                    json={"body": adf_body},
                )
                return resp.status_code == 201

        return False

    # ── handle_webhook ───────────────────────────────────────────────────────

    async def handle_webhook(self, payload: dict, headers: dict) -> Optional[dict]:
        # Jira webhooks can be secured by matching the Authorization header value
        secret = self.credentials.get("webhook_secret", "")
        if secret:
            auth_header = headers.get("authorization", "")
            if auth_header != secret:
                self.logger.warning("Jira webhook auth mismatch — ignoring")
                return None

        event = payload.get("webhookEvent", "")
        issue = payload.get("issue", {})
        if not issue:
            return None

        key = issue.get("key")
        fields = issue.get("fields", {})
        raw_desc = fields.get("description") or ""
        description = _adf_to_text(raw_desc) if isinstance(raw_desc, dict) else raw_desc
        priority_raw = (fields.get("priority") or {}).get("name", "normal")

        if event in ("jira:issue_created", "jira:issue_updated"):
            return await self._upsert_card(
                external_id=key,
                external_source=self.SOURCE,
                external_url=f"{self._base()}/browse/{key}",
                title=f"[{key}] {fields.get('summary', '')}",
                description=description,
                priority=self._map_priority(priority_raw),
            )

        return None
