"""
Universal generation cancellation store.
Tracks active AI requests so they can be cancelled by request_id.
Thread-safe for async use; no memory leaks (explicit remove).
"""
import asyncio
import os
from typing import Optional, Dict, Any
from uuid import uuid4

# Optional: max age in seconds; after this a request is considered stale and can be cleaned
CANCEL_STORE_MAX_AGE_SEC = int(os.getenv("AI_REQUEST_MAX_AGE_SEC", "300"))
# Optional: only one active generation per user (cancel previous when starting new)
ONE_ACTIVE_PER_USER = os.getenv("AI_ONE_ACTIVE_PER_USER", "true").lower() in ("1", "true", "yes")

_active_requests: Dict[str, Dict[str, Any]] = {}
_lock = asyncio.Lock()


class GenerationCancelledError(Exception):
    """Raised when an AI generation was cancelled by the user or system."""
    pass


def create_request_id() -> str:
    return str(uuid4())


async def register(request_id: str, user_id: Optional[int] = None) -> None:
    """Register an active request. If ONE_ACTIVE_PER_USER, cancel any previous request for this user."""
    async with _lock:
        if ONE_ACTIVE_PER_USER and user_id is not None:
            to_remove = [
                rid for rid, data in _active_requests.items()
                if data.get("user_id") == user_id and rid != request_id
            ]
            for rid in to_remove:
                _active_requests[rid]["cancelled"] = True
        _active_requests[request_id] = {
            "cancelled": False,
            "user_id": user_id,
        }


def cancel(request_id: str) -> bool:
    """Mark request as cancelled. Returns True if request was found and not already cancelled."""
    if request_id not in _active_requests:
        return False
    if _active_requests[request_id].get("cancelled"):
        return False
    _active_requests[request_id]["cancelled"] = True
    return True


def is_cancelled(request_id: Optional[str]) -> bool:
    """Return True if request_id is registered and has been cancelled."""
    if not request_id:
        return False
    return _active_requests.get(request_id, {}).get("cancelled", False)


def remove(request_id: str) -> None:
    """Remove request from store (call after completion or cancel). Prevents memory leaks."""
    _active_requests.pop(request_id, None)


def get_active_request_ids() -> list:
    """Return list of active request IDs (for debugging/admin)."""
    return list(_active_requests.keys())
