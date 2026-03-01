"""
integrations/github_integration.py
GitHub Issues adapter for Aegis.

Credentials:
  token          — Personal Access Token (ghp_... or fine-grained)
  repo           — "owner/repo"
  webhook_secret — (optional) secret for HMAC-SHA256 webhook verification

Filters:
  state          — "open" (default) | "closed" | "all"
  labels         — comma-separated label names, e.g. "bug,feature"
  assignee       — GitHub username to filter by, or "" for all
"""
import hashlib
import hmac
import json
import re
from typing import Optional

import httpx

from .base import BaseIntegration

_BASE = "https://api.github.com"


class GitHubIntegration(BaseIntegration):
    SOURCE = "github"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.credentials['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo(self) -> str:
        return self.credentials.get("repo", "")

    # ── sync_in ──────────────────────────────────────────────────────────────

    async def sync_in(self) -> list:
        state = self.filters.get("state", "open")
        raw_labels = self.filters.get("labels", "")
        label_str = ",".join(raw_labels) if isinstance(raw_labels, list) else raw_labels
        params: dict = {"state": state, "per_page": 100}
        if label_str:
            params["labels"] = label_str
        if self.filters.get("assignee"):
            params["assignee"] = self.filters["assignee"]

        results = []
        page = 1
        async with httpx.AsyncClient(timeout=20) as client:
            while True:
                params["page"] = page
                resp = await client.get(
                    f"{_BASE}/repos/{self._repo()}/issues",
                    headers=self._headers(),
                    params=params,
                )
                resp.raise_for_status()
                issues = resp.json()
                if not issues:
                    break
                for issue in issues:
                    if issue.get("pull_request"):
                        continue  # skip PRs
                    card = await self._upsert_card(
                        external_id=str(issue["number"]),
                        external_source=self.SOURCE,
                        external_url=issue["html_url"],
                        title=f"[GH #{issue['number']}] {issue['title']}",
                        description=self._build_description(issue),
                        priority=self._priority_from_labels(issue.get("labels", [])),
                        metadata=self._build_metadata(issue),
                    )
                    results.append(card)
                page += 1
        return results

    # ── sync_out ─────────────────────────────────────────────────────────────

    async def sync_out(self, card: dict, event_type: str) -> bool:
        # Strip the [GH #N] prefix we add locally — GitHub stores the clean title
        clean_title = re.sub(r'^\[GH #\d+\]\s*', '', card.get("title", ""))

        # 1. Handle NEW cards (no external_id yet)
        if event_type == "card_created" and not card.get("external_id"):
            if card.get("column") != self.column_name:
                return False

            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{_BASE}/repos/{self._repo()}/issues",
                    headers=self._headers(),
                    json={"title": clean_title, "body": card.get("description", "")},
                )
                if resp.status_code == 201:
                    data = resp.json()
                    updated = self.store.update_card(
                        card["id"],
                        external_id=str(data["number"]),
                        external_source=self.SOURCE,
                        external_url=data["html_url"],
                    )
                    await self.broadcaster({"type": "card_updated", "card": updated})
                    return True
                self.logger.error(f"Failed to create GitHub issue: {resp.status_code} - {resp.text}")
                return False

        # 2. Handle EXISTING cards
        if card.get("external_source") != self.SOURCE:
            return False

        issue_number = card.get("external_id")
        if not issue_number:
            return False

        async with httpx.AsyncClient(timeout=20) as client:
            # MOVED TO DONE / DELETED — close the issue
            if (event_type == "card_moved" and card.get("column") == "Done") or event_type == "card_deleted":
                resp = await client.patch(
                    f"{_BASE}/repos/{self._repo()}/issues/{issue_number}",
                    headers=self._headers(),
                    json={"state": "closed"},
                )
                if resp.status_code == 404:
                    self.store.delete_card(card["id"])
                    await self.broadcaster({"type": "card_deleted", "card_id": card["id"]})
                    return False
                return resp.status_code == 200

            # CONTENT UPDATED
            if event_type == "card_updated":
                resp = await client.patch(
                    f"{_BASE}/repos/{self._repo()}/issues/{issue_number}",
                    headers=self._headers(),
                    json={"title": clean_title, "body": card.get("description", "")},
                )
                if resp.status_code == 404:
                    self.store.delete_card(card["id"])
                    await self.broadcaster({"type": "card_deleted", "card_id": card["id"]})
                    return False
                if resp.status_code == 200:
                    sync_hash = hashlib.sha256((card.get("description") or "").encode()).hexdigest()
                    self.store.update_card(card["id"], last_synced_hash=sync_hash)
                    return True
                return False

            # COMMENT ADDED
            if event_type == "comment_added":
                comments = card.get("comments", [])
                if not comments:
                    return False
                latest = comments[-1]
                body = f"[Aegis — {latest.get('author', 'unknown')}]: {latest.get('content', '')}"
                resp = await client.post(
                    f"{_BASE}/repos/{self._repo()}/issues/{issue_number}/comments",
                    headers=self._headers(),
                    json={"body": body},
                )
                return resp.status_code == 201

        return False

    # ── handle_webhook ───────────────────────────────────────────────────────

    async def handle_webhook(self, payload: dict, headers: dict) -> Optional[dict]:
        # Verify HMAC signature if secret is configured
        secret = self.credentials.get("webhook_secret", "")
        sig_header = headers.get("x-hub-signature-256", "")
        if secret and sig_header:
            raw_body = headers.get("_raw_body", b"")
            expected = "sha256=" + hmac.new(
                secret.encode(), raw_body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, sig_header):
                self.logger.warning("GitHub webhook signature mismatch — ignoring")
                return None

        event = headers.get("x-github-event", "")
        action = payload.get("action", "")
        issue = payload.get("issue")

        if not issue or event != "issues":
            return None

        if action in ("opened", "edited", "reopened", "labeled"):
            return await self._upsert_card(
                external_id=str(issue["number"]),
                external_source=self.SOURCE,
                external_url=issue["html_url"],
                title=f"[GH #{issue['number']}] {issue['title']}",
                description=self._build_description(issue),
                priority=self._priority_from_labels(issue.get("labels", [])),
                metadata=self._build_metadata(issue),
            )

        if action == "closed":
            existing = self.store.find_card_by_external_id(str(issue["number"]), self.SOURCE)
            if existing:
                updated = self.store.update_card(existing["id"], column="Done", status="completed")
                await self.broadcaster({"type": "card_updated", "card": updated})
                return updated

        return None

    # ── register_webhook ─────────────────────────────────────────────────────

    async def register_webhook(self, webhook_url: str) -> bool:
        secret = self.credentials.get("webhook_secret", "")
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{_BASE}/repos/{self._repo()}/hooks",
                headers=self._headers(),
                json={
                    "name": "web",
                    "active": True,
                    "events": ["issues"],
                    "config": {
                        "url": webhook_url,
                        "content_type": "json",
                        "secret": secret,
                        "insecure_ssl": "0",
                    },
                },
            )
            return resp.status_code == 201

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_description(self, issue: dict) -> str:
        """Return the raw issue body only. Rich metadata goes to _build_metadata."""
        return issue.get("body") or ""

    def _build_metadata(self, issue: dict) -> str:
        """Return a JSON string of structured GitHub metadata for the card's metadata field."""
        return json.dumps({
            "source": "github",
            "action_required": True,
            "state": issue.get("state", "open"),
            "github_number": issue.get("number"),
            "labels": [l["name"] for l in issue.get("labels", [])],
            "assignees": [a["login"] for a in issue.get("assignees", [])],
            "milestone": issue["milestone"]["title"] if issue.get("milestone") else None,
            "external_url": issue.get("html_url", ""),
        })

    def _priority_from_labels(self, labels: list) -> str:
        for label in labels:
            name = label.get("name", "").lower()
            if name.startswith("priority:"):
                return self._map_priority(name.split(":", 1)[1].strip())
            if name in ("high", "urgent", "critical", "p0", "p1"):
                return "high"
            if name in ("low", "minor", "trivial", "p3", "p4"):
                return "low"
        return "normal"

    # ── PR / Branch Operations ────────────────────────────────────────────────

    async def create_branch(self, branch_name: str, base: str = "main") -> dict:
        """Create a new branch from a base ref."""
        async with httpx.AsyncClient(timeout=20) as client:
            # Get SHA of base branch
            ref_resp = await client.get(
                f"{_BASE}/repos/{self._repo()}/git/ref/heads/{base}",
                headers=self._headers(),
            )
            if ref_resp.status_code != 200:
                return {"error": f"Base branch '{base}' not found: {ref_resp.status_code}"}
            sha = ref_resp.json()["object"]["sha"]

            # Create new branch ref
            create_resp = await client.post(
                f"{_BASE}/repos/{self._repo()}/git/refs",
                headers=self._headers(),
                json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            )
            if create_resp.status_code == 201:
                return {"success": True, "branch": branch_name, "sha": sha}
            return {"error": f"Failed to create branch: {create_resp.status_code} - {create_resp.text}"}

    async def create_pull_request(self, title: str, body: str, head: str, base: str = "main") -> dict:
        """Open a pull request."""
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{_BASE}/repos/{self._repo()}/pulls",
                headers=self._headers(),
                json={"title": title, "body": body, "head": head, "base": base},
            )
            if resp.status_code == 201:
                data = resp.json()
                return {
                    "success": True,
                    "pr_number": data["number"],
                    "url": data["html_url"],
                    "state": data["state"],
                }
            return {"error": f"Failed to create PR: {resp.status_code} - {resp.text}"}

    async def merge_pull_request(self, pr_number: int, merge_method: str = "squash", commit_message: str = "") -> dict:
        """Merge a pull request."""
        async with httpx.AsyncClient(timeout=20) as client:
            payload = {"merge_method": merge_method}
            if commit_message:
                payload["commit_message"] = commit_message
            resp = await client.put(
                f"{_BASE}/repos/{self._repo()}/pulls/{pr_number}/merge",
                headers=self._headers(),
                json=payload,
            )
            if resp.status_code == 200:
                return {"success": True, "merged": True, "message": resp.json().get("message", "")}
            return {"error": f"Merge failed: {resp.status_code} - {resp.text}"}

    async def list_pull_requests(self, state: str = "open") -> list:
        """List pull requests for the repo."""
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{_BASE}/repos/{self._repo()}/pulls",
                headers=self._headers(),
                params={"state": state, "per_page": 30},
            )
            resp.raise_for_status()
            return [
                {
                    "number": pr["number"],
                    "title": pr["title"],
                    "state": pr["state"],
                    "url": pr["html_url"],
                    "head": pr.get("head", {}).get("ref", ""),
                    "base": pr.get("base", {}).get("ref", ""),
                    "draft": pr.get("draft", False),
                    "mergeable": pr.get("mergeable"),
                }
                for pr in resp.json()
            ]

    async def list_branches(self) -> list:
        """List branches for the repo."""
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{_BASE}/repos/{self._repo()}/branches",
                headers=self._headers(),
                params={"per_page": 50},
            )
            resp.raise_for_status()
            return [{"name": b["name"], "sha": b["commit"]["sha"]} for b in resp.json()]
