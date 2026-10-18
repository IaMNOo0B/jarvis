"""
JARVIS Memory Subsystem
Provides persistent memory bank stored in JSON & Markdown files:
- Real-time fact saving
- Topic & keyword recall
- Summarized context feeding for prompt injection
"""

import os
import json
import time

MEMORY_DIR = os.path.join(os.path.dirname(__file__), "memory_bank")
MEMORY_FILE = os.path.join(MEMORY_DIR, "knowledge.json")
NOTES_FILE = os.path.join(MEMORY_DIR, "notes.md")

class MemoryBank:
    def __init__(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)
        if not os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)

    def _load(self):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self, entries):
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)

    def save_knowledge(self, title: str, content: str, source: str = "web") -> str:
        """Stores a new piece of learned knowledge."""
        entries = self._load()
        item = {
            "id": len(entries) + 1,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "title": title.strip(),
            "content": content.strip(),
            "source": source
        }
        entries.append(item)
        self._save(entries)

        # Also append human-readable format to notes.md
        with open(NOTES_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n## [{item['timestamp']}] {item['title']}\n")
            f.write(f"**Source:** {item['source']}\n\n")
            f.write(f"{item['content']}\n\n---\n")

        return f"Successfully saved knowledge: '{title}' into memory bank (Entry #{item['id']})."

    def search_memory(self, query: str, top_k: int = 3) -> str:
        """Searches memory entries matching keywords."""
        entries = self._load()
        if not entries:
            return "Memory bank is currently empty."

        query_terms = [t.lower() for t in query.split() if len(t) > 2]
        scored = []
        for e in entries:
            text = f"{e['title']} {e['content']}".lower()
            score = sum(1 for term in query_terms if term in text)
            if score > 0 or not query_terms:
                scored.append((score, e))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_matches = scored[:top_k]

        if not top_matches:
            return f"No memories found matching '{query}'."

        results = [f"Found {len(top_matches)} memory item(s):"]
        for _, item in top_matches:
            results.append(
                f"\n- **{item['title']}** ({item['timestamp']}) [Source: {item['source']}]:\n  {item['content']}"
            )
        return "\n".join(results)

    def get_recent_summary(self, max_items: int = 5) -> str:
        """Returns brief titles of recently stored memories to keep the model aware."""
        entries = self._load()
        if not entries:
            return ""
        recent = entries[-max_items:]
        titles = [f"- {e['title']} ({e['timestamp']})" for e in recent]
        return "Recent Learned Topics in Memory:\n" + "\n".join(titles)

# Global singleton
memory_instance = MemoryBank()
