"""Persistent, provenance-aware memory for JARVIS.

Legacy entries remain readable. New entries record evidence and confidence,
and remain unverified until explicitly reviewed with evidence.
"""

import json
import os
import threading
import uuid
from datetime import datetime
from typing import Iterable

from paths import user_file


MEMORY_FILE = user_file(os.path.join("memory_bank", "knowledge.json"))
MEMORY_DIR = os.path.dirname(MEMORY_FILE)
NOTES_FILE = user_file(os.path.join("memory_bank", "notes.md"))


class MemoryDataError(RuntimeError):
    """Raised when the persisted memory cannot safely be read or updated."""


def _text_list(values) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Iterable):
        raise ValueError("Expected text or a list of text values.")
    out = []
    for value in values:
        item = str(value).strip()
        if item and item not in out:
            out.append(item)
    return out


class MemoryBank:
    def __init__(self):
        self._lock = threading.RLock()
        os.makedirs(MEMORY_DIR, exist_ok=True)
        if not os.path.exists(MEMORY_FILE):
            self._save([])

    def _load(self) -> list[dict]:
        """Load memory without converting a read/JSON error into an empty bank."""
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except FileNotFoundError as exc:
            raise MemoryDataError(
                f"Memory file {MEMORY_FILE} disappeared; no empty replacement was created."
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise MemoryDataError(
                f"Could not safely read {MEMORY_FILE}; memory was not reset. "
                "Restore the file from backup or repair its JSON before writing."
            ) from exc
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise MemoryDataError(
                f"Memory file {MEMORY_FILE} has an invalid structure; no changes were made."
            )
        return entries

    def _save(self, entries: list[dict]) -> None:
        """Atomically replace the JSON file so interrupted writes don't truncate it."""
        os.makedirs(MEMORY_DIR, exist_ok=True)
        temp_path = f"{MEMORY_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, MEMORY_FILE)
        except OSError as exc:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise MemoryDataError(f"Could not save memory to {MEMORY_FILE}: {exc}") from exc

    @staticmethod
    def _entry_id(entry: dict) -> str:
        return str(entry.get("id", ""))

    def save_knowledge(
        self,
        title: str,
        content: str,
        source: str = "web",
        evidence=None,
        confidence: float | None = None,
        outcome: str = "",
        tags=None,
    ) -> str:
        """Save a new lesson as unverified with its provenance attached."""
        title = str(title or "").strip()
        content = str(content or "").strip()
        source = str(source or "unspecified").strip()
        outcome = str(outcome or "").strip()
        if not title or not content:
            return "Memory not saved: both title and content are required."

        try:
            evidence_items = _text_list(evidence)
            tag_items = _text_list(tags)
        except ValueError as exc:
            return f"Memory not saved: {exc}"

        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                return "Memory not saved: confidence must be a number from 0 to 1."
            if not 0.0 <= confidence <= 1.0:
                return "Memory not saved: confidence must be from 0 to 1."

        with self._lock:
            entries = self._load()
            item = {
                "id": uuid.uuid4().hex,
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "title": title,
                "content": content,
                "record_type": "knowledge",
                "source": source,
                "evidence": evidence_items,
                "confidence": confidence,
                "outcome": outcome,
                "tags": tag_items,
                "validation_status": "unverified",
                "validation_evidence": [],
                "validated_at": None,
                "validation_outcome": "",
            }
            entries.append(item)
            self._save(entries)

        # Markdown is a convenience mirror; the JSON file is authoritative.
        try:
            with open(NOTES_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n## [{item['timestamp']}] {item['title']}\n")
                f.write(f"**Source:** {item['source']}\n")
                f.write("**Validation:** unverified\n")
                if evidence_items:
                    f.write("**Evidence:** " + "; ".join(evidence_items) + "\n")
                if outcome:
                    f.write(f"**Outcome:** {outcome}\n")
                f.write(f"\n{item['content']}\n\n---\n")
        except OSError:
            pass

        return (
            f"Saved learning record '{title}' (ID {item['id']}) as unverified. "
            "Use its evidence and outcome to review it before relying on it as validated."
        )

    def record_task_outcome(
        self,
        task: str,
        status: str,
        result: str,
        evidence=None,
        user_feedback: str = "",
    ) -> str:
        """Keep a searchable task episode with observed outcome and evidence."""
        task = str(task or "").strip()
        result = str(result or "").strip()
        status = str(status or "").strip().lower()
        user_feedback = str(user_feedback or "").strip()
        if not task or not result:
            return "Task outcome not saved: task and result are required."
        if status not in {"success", "partial", "failure"}:
            return "Task outcome not saved: status must be success, partial, or failure."
        try:
            proof = _text_list(evidence)
        except ValueError as exc:
            return f"Task outcome not saved: {exc}"

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        reward = {"success": 1.0, "partial": 0.0, "failure": -1.0}[status]
        validated = bool(proof)
        item = {
            "id": uuid.uuid4().hex,
            "timestamp": now,
            "title": f"Task outcome: {task[:120]}",
            "content": result,
            "record_type": "task_outcome",
            "source": "observed task outcome",
            "evidence": proof,
            "confidence": 1.0 if validated else None,
            "outcome": status,
            "outcome_status": status,
            "reward": reward,
            "user_feedback": user_feedback,
            "tags": ["task-outcome", status],
            "validation_status": "validated" if validated else "unverified",
            "validation_evidence": proof,
            "validated_at": now if validated else None,
            "validation_outcome": f"Recorded task status: {status}" if validated else "",
        }
        with self._lock:
            entries = self._load()
            entries.append(item)
            self._save(entries)

        try:
            with open(NOTES_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n## [{now}] {item['title']}\n")
                f.write(f"**Type:** task outcome ({status})\n")
                f.write(f"**Reward signal:** {reward:+.1f}\n")
                f.write(f"**Validation:** {item['validation_status']}\n")
                if proof:
                    f.write("**Evidence:** " + "; ".join(proof) + "\n")
                if user_feedback:
                    f.write(f"**User feedback:** {user_feedback}\n")
                f.write(f"\n{result}\n\n---\n")
        except OSError:
            pass

        validation = "with evidence" if validated else "as unverified (no evidence supplied)"
        return f"Recorded task outcome '{task}' as {status} {validation}; reward signal {reward:+.1f}."

    def validate_knowledge(self, entry_id: str, evidence, outcome: str) -> str:
        """Mark a record reviewed only when concrete validation evidence is supplied."""
        try:
            proof = _text_list(evidence)
        except ValueError as exc:
            return f"Learning record not validated: {exc}"
        outcome = str(outcome or "").strip()
        if not proof or not outcome:
            return "Learning record not validated: provide evidence and a validation outcome."

        with self._lock:
            entries = self._load()
            target = next((e for e in entries if self._entry_id(e) == str(entry_id)), None)
            if target is None:
                return f"No learning record found with ID '{entry_id}'."
            target["validation_status"] = "validated"
            target["validation_evidence"] = proof
            target["validated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            target["validation_outcome"] = outcome
            self._save(entries)

        return f"Learning record '{target.get('title', entry_id)}' is now marked validated with recorded evidence."

    def search_memory(self, query: str, top_k: int = 5, status: str = "all") -> str:
        """Search memory by keywords; expose validation state and provenance."""
        entries = self._load()
        if not entries:
            return "Memory bank is currently empty."

        query_terms = [t.lower() for t in str(query or "").split() if len(t) > 2]
        status = str(status or "all").lower()
        if status not in {"all", "unverified", "validated"}:
            status = "all"
        scored = []
        for entry in entries:
            title = str(entry.get("title", ""))
            content = str(entry.get("content", ""))
            entry_status = str(entry.get("validation_status") or "unverified").lower()
            if status != "all" and entry_status != status:
                continue
            searchable = f"{title} {content} {' '.join(_text_list(entry.get('tags')))}".lower()
            score = sum(1 for term in query_terms if term in searchable)
            if score > 0 or not query_terms:
                scored.append((score, entry))

        scored.sort(key=lambda pair: (pair[0], str(pair[1].get("timestamp", ""))), reverse=True)
        top_matches = scored[:max(1, min(int(top_k), 20))]
        if not top_matches:
            return f"No memories found for query '{query}' with status '{status}'."

        results = [f"Found {len(top_matches)} learning record(s) (filter: {status}):"]
        for _, item in top_matches:
            entry_status = item.get("validation_status") or "unverified"
            confidence = item.get("confidence")
            conf_text = f", confidence {confidence:.2f}" if isinstance(confidence, (int, float)) else ""
            evidence = _text_list(item.get("evidence"))
            validation_evidence = _text_list(item.get("validation_evidence"))
            source = str(item.get("source") or "unspecified")
            results.append(
                f"\n- {item.get('title', 'Untitled')} "
                f"(ID: {self._entry_id(item)}; {item.get('timestamp', 'unknown date')}; "
                f"status: {entry_status}{conf_text}; source: {source})\n"
                f"  {item.get('content', '')}"
            )
            if evidence:
                results.append("  Evidence: " + "; ".join(evidence))
            if item.get("outcome"):
                results.append("  Outcome: " + str(item["outcome"]))
            if item.get("outcome_status"):
                results.append("  Task status: " + str(item["outcome_status"]))
            if isinstance(item.get("reward"), (int, float)):
                results.append(f"  Reward signal: {item['reward']:+.1f}")
            if item.get("user_feedback"):
                results.append("  User feedback: " + str(item["user_feedback"]))
            if validation_evidence:
                results.append("  Validation evidence: " + "; ".join(validation_evidence))
            if item.get("validation_outcome"):
                results.append("  Validation outcome: " + str(item["validation_outcome"]))
        return "\n".join(results)

    def get_recent_summary(self, max_items: int = 5) -> str:
        """Briefly summarize recent records without hiding their validation state."""
        entries = self._load()
        if not entries:
            return ""
        recent = entries[-max(1, min(int(max_items), 20)):]
        titles = [
            f"- {e.get('title', 'Untitled')} "
            f"[{e.get('validation_status') or 'unverified'}] "
            f"({e.get('timestamp', 'unknown date')})"
            for e in recent
        ]
        return "Recent learning records (validate before treating as proven):\n" + "\n".join(titles)


memory_instance = MemoryBank()
