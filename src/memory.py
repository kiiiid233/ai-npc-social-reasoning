import hashlib
import time
import logging
from dataclasses import dataclass, field

import chromadb

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    content: str
    timestamp: float
    importance: float = 0.5  # 0~1, higher = harder to forget

    @property
    def decay(self) -> float:
        """Ebbinghaus-inspired decay: importance × recency."""
        hours_since = (time.time() - self.timestamp) / 3600
        return self.importance * (0.5 ** (hours_since / 24))  # half-life = 24h


class MemorySystem:
    def __init__(self, owner: str, db_path: str | None = None):
        if db_path is None:
            from pathlib import Path as _Path
            db_path = str(_Path(__file__).parent.parent / "data" / "chroma")
        self.owner = owner
        self._client = chromadb.PersistentClient(path=db_path)
        # ChromaDB collection names only allow [a-zA-Z0-9._-], so hash the owner name
        coll_name = "mem_" + hashlib.md5(owner.encode()).hexdigest()[:12]
        self._collection = self._client.get_or_create_collection(
            name=coll_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._entry_count = 0

    def store(self, event: str, importance: float = 0.5):
        """Store a memory with importance weighting."""
        self._entry_count += 1
        entry_id = hashlib.md5(f"{self.owner}_{self._entry_count}".encode()).hexdigest()[:12]
        metadata = {
            "timestamp": time.time(),
            "importance": importance,
            "decay": importance,
        }
        self._collection.add(
            ids=[entry_id],
            documents=[event],
            metadatas=[metadata],
        )

    def search(self, query: str, top_k: int = 5) -> list[str]:
        """Retrieve the most relevant memories for a given query."""
        if self._collection.count() == 0:
            return []

        results = self._collection.query(
            query_texts=[query],
            n_results=min(top_k, self._collection.count()),
        )

        memories = []
        if results["documents"]:
            # Update decay scores
            for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                hours_since = (time.time() - meta["timestamp"]) / 3600
                current_decay = meta["importance"] * (0.5 ** (hours_since / 24))
                if current_decay > 0.05:  # forgotten threshold
                    memories.append(doc)

        return memories

    def forget(self, threshold: float = 0.05):
        """Remove memories below the decay threshold. Call periodically."""
        all_ids = self._collection.get()["ids"]
        if not all_ids:
            return

        all_data = self._collection.get(ids=all_ids, include=["metadatas"])
        ids_to_remove = []

        for entry_id, meta in zip(all_data["ids"], all_data["metadatas"]):
            hours_since = (time.time() - meta["timestamp"]) / 3600
            decay = meta["importance"] * (0.5 ** (hours_since / 24))
            if decay < threshold:
                ids_to_remove.append(entry_id)

        if ids_to_remove:
            self._collection.delete(ids=ids_to_remove)
            logger.info("%s forgot %d memories", self.owner, len(ids_to_remove))

    def get_recent(self, n: int = 3) -> list[str]:
        """Get the N most recent memories."""
        if self._collection.count() == 0:
            return []

        all_data = self._collection.get(
            include=["documents", "metadatas"],
        )
        entries = list(zip(all_data["documents"], all_data["metadatas"]))
        entries.sort(key=lambda x: x[1]["timestamp"], reverse=True)
        return [doc for doc, _ in entries[:n]]
