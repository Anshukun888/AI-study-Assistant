"""
Group service for Collaborative Study Groups.
Handles CRUD, membership, messages, documents, pin, vote, insights, and invite links.
"""
import os
import re
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from backend.models import (
    User,
    StudyGroup,
    GroupMembership,
    GroupMessage,
    GroupDocument,
    MessageVote,
    PinnedGroupMessage,
    GroupInvite,
)
from backend.chat_service import sanitize_user_input

# Token/context limit for 8GB RAM
GROUP_CONTEXT_CHARS = int(os.getenv("GROUP_CONTEXT_CHARS", "8000"))
GROUP_HISTORY_MESSAGES = 10


def _truncate(s: str, max_len: int = GROUP_CONTEXT_CHARS) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + "\n\n[Truncated...]"


def create_group(db: Session, user: User, name: str) -> StudyGroup:
    """Create a new study group; creator becomes admin."""
    name = sanitize_user_input(name or "Study Group", 255).strip() or "Study Group"
    group = StudyGroup(name=name, created_by=user.id)
    db.add(group)
    db.commit()
    db.refresh(group)
    membership = GroupMembership(user_id=user.id, group_id=group.id, role="admin")
    db.add(membership)
    db.commit()
    return group


def get_user_groups(db: Session, user_id: int) -> List[StudyGroup]:
    """Groups the user is a member of, most recent first."""
    return (
        db.query(StudyGroup)
        .join(GroupMembership, GroupMembership.group_id == StudyGroup.id)
        .filter(GroupMembership.user_id == user_id)
        .order_by(desc(StudyGroup.created_at))
        .all()
    )


def get_group(db: Session, group_id: int) -> Optional[StudyGroup]:
    return db.query(StudyGroup).filter(StudyGroup.id == group_id).first()


def is_member(db: Session, group_id: int, user_id: int) -> bool:
    return (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user_id,
        )
        .first()
        is not None
    )


def get_user_role(db: Session, group_id: int, user_id: int) -> Optional[str]:
    """Return 'admin' or 'member' if user is in group, else None."""
    m = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user_id,
        )
        .first()
    )
    return m.role if m else None


def leave_group(db: Session, group_id: int, user_id: int) -> bool:
    """Remove user from group. Returns True if left, False if not a member."""
    m = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user_id,
        )
        .first()
    )
    if not m:
        return False
    db.delete(m)
    db.commit()
    return True


def delete_group(db: Session, group_id: int, user_id: int) -> bool:
    """Delete the group. Only admins can delete. Returns True if deleted, False otherwise."""
    m = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user_id,
        )
        .first()
    )
    if not m or m.role != "admin":
        return False
    group = db.query(StudyGroup).filter(StudyGroup.id == group_id).first()
    if not group:
        return False
    db.delete(group)
    db.commit()
    return True


def get_members(db: Session, group_id: int) -> List[Dict[str, Any]]:
    """Return list of {user_id, username, role} for group."""
    rows = (
        db.query(User.id, User.username, GroupMembership.role)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .filter(GroupMembership.group_id == group_id)
        .all()
    )
    return [{"user_id": r[0], "username": r[1], "role": r[2]} for r in rows]


def join_group(db: Session, group_id: int, user: User) -> GroupMembership:
    """Add user as member. Idempotent if already member."""
    if is_member(db, group_id, user.id):
        return (
            db.query(GroupMembership)
            .filter(
                GroupMembership.group_id == group_id,
                GroupMembership.user_id == user.id,
            )
            .first()
        )
    m = GroupMembership(user_id=user.id, group_id=group_id, role="member")
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def get_messages(
    db: Session,
    group_id: int,
    limit: int = 50,
    offset: int = 0,
) -> List[GroupMessage]:
    """Lazy-load messages, newest last (chronological order)."""
    return (
        db.query(GroupMessage)
        .filter(GroupMessage.group_id == group_id)
        .order_by(GroupMessage.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_recent_messages_for_context(db: Session, group_id: int, count: int = GROUP_HISTORY_MESSAGES) -> List[GroupMessage]:
    """Last N messages for AI context (oldest to newest)."""
    return (
        db.query(GroupMessage)
        .filter(GroupMessage.group_id == group_id)
        .order_by(GroupMessage.created_at.desc())
        .limit(count)
        .all()
    )[::-1]


def add_message(
    db: Session,
    group_id: int,
    user_id: Optional[int],
    message: str,
    message_type: str = "text",
    file_path: Optional[str] = None,
    file_name: Optional[str] = None,
    sender_type: str = "user",
    message_status: str = "sent",
    group_file_id: Optional[int] = None,
) -> GroupMessage:
    """Add a group message. user_id None and sender_type='ai' for AI messages."""
    msg = GroupMessage(
        group_id=group_id,
        user_id=user_id,
        sender_type=sender_type,
        message=sanitize_user_input(message, 15000),
        message_type=message_type or "text",
        file_path=file_path,
        file_name=file_name,
        message_status=message_status,
        group_file_id=group_file_id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_group_documents_text(db: Session, group_id: int, exclude_file_id: Optional[int] = None) -> str:
    """Concatenate extracted_text from all group documents for AI context. Optionally exclude one file (when used as primary)."""
    q = db.query(GroupDocument).filter(
        GroupDocument.group_id == group_id,
        GroupDocument.extracted_text.isnot(None),
    )
    if exclude_file_id is not None:
        q = q.filter(GroupDocument.id != exclude_file_id)
    docs = q.all()
    parts = []
    for d in docs:
        if d.extracted_text and d.extracted_text.strip():
            parts.append(f"--- Document: {d.file_name} ---\n\n{d.extracted_text}")
    return _truncate("\n\n".join(parts)) if parts else ""


def get_group_document_by_id(db: Session, group_id: int, file_id: int) -> Optional[GroupDocument]:
    """Get a single group document by id if it belongs to the group."""
    return (
        db.query(GroupDocument)
        .filter(GroupDocument.id == file_id, GroupDocument.group_id == group_id)
        .first()
    )


def get_group_files(db: Session, group_id: int) -> List[Dict[str, Any]]:
    """List group files (documents) for the files panel. Returns id, file_name, file_path, uploaded_by, created_at."""
    docs = (
        db.query(GroupDocument)
        .filter(GroupDocument.group_id == group_id)
        .order_by(desc(GroupDocument.created_at))
        .all()
    )
    return [
        {
            "id": d.id,
            "group_id": d.group_id,
            "file_name": d.file_name,
            "file_path": d.file_path,
            "uploaded_by": d.uploaded_by,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


def get_context_for_group_ai(
    db: Session,
    group_id: int,
    recent_messages: Optional[List[GroupMessage]] = None,
    primary_file_id: Optional[int] = None,
) -> str:
    """
    Build context for group AI with priority:
    1) Attached/selected file (primary_file_id)
    2) Other group documents
    3) Group conversation
    4) (Caller adds general knowledge if needed)
    """
    primary_text = ""
    if primary_file_id:
        doc = get_group_document_by_id(db, group_id, primary_file_id)
        if doc and doc.extracted_text and doc.extracted_text.strip():
            primary_text = f"--- Primary document (use this first): {doc.file_name} ---\n\n{_truncate(doc.extracted_text, max_len=GROUP_CONTEXT_CHARS // 2)}"
    other_docs = get_group_documents_text(db, group_id, exclude_file_id=primary_file_id)
    if recent_messages is None:
        recent_messages = get_recent_messages_for_context(db, group_id)
    lines = []
    for m in recent_messages:
        if getattr(m, "message_type", None) == "ai" or getattr(m, "sender_type", None) == "ai":
            lines.append(f"Assistant: {m.message}")
        elif m.user_id:
            u = db.query(User).filter(User.id == m.user_id).first()
            name = u.username if u else "User"
            lines.append(f"{name}: {m.message}")
        else:
            lines.append(f"User: {m.message}")
    dialogue = "\n".join(lines)
    parts = []
    if primary_text:
        parts.append(primary_text)
    if other_docs:
        parts.append(f"Other group documents:\n{other_docs}")
    if dialogue:
        parts.append(f"Recent chat:\n{dialogue}")
    combined = "\n\n".join(parts) if parts else "No specific context."
    return _truncate(combined)


def pin_message(db: Session, group_id: int, message_id: int, user_id: int) -> PinnedGroupMessage:
    """Pin a message; only one per group (replaces previous)."""
    msg = db.query(GroupMessage).filter(GroupMessage.id == message_id, GroupMessage.group_id == group_id).first()
    if not msg:
        raise ValueError("Message not found")
    existing = db.query(PinnedGroupMessage).filter(PinnedGroupMessage.group_id == group_id).first()
    if existing:
        db.delete(existing)
        db.commit()
    pin = PinnedGroupMessage(group_id=group_id, message_id=message_id, pinned_by=user_id)
    db.add(pin)
    db.commit()
    db.refresh(pin)
    return pin


def unpin_message(db: Session, group_id: int) -> None:
    """Remove pinned message for group."""
    db.query(PinnedGroupMessage).filter(PinnedGroupMessage.group_id == group_id).delete()
    db.commit()


def get_pinned_message(db: Session, group_id: int) -> Optional[GroupMessage]:
    """Get the currently pinned message for the group."""
    pin = db.query(PinnedGroupMessage).filter(PinnedGroupMessage.group_id == group_id).first()
    if not pin:
        return None
    return db.query(GroupMessage).filter(GroupMessage.id == pin.message_id).first()


def vote_message(db: Session, message_id: int, user_id: int, group_id: int) -> bool:
    """Toggle upvote on message. Returns True if voted, False if removed."""
    msg = db.query(GroupMessage).filter(GroupMessage.id == message_id, GroupMessage.group_id == group_id).first()
    if not msg:
        raise ValueError("Message not found")
    existing = (
        db.query(MessageVote)
        .filter(MessageVote.message_id == message_id, MessageVote.user_id == user_id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        return False
    v = MessageVote(message_id=message_id, user_id=user_id)
    db.add(v)
    db.commit()
    return True


def get_message_vote_count(db: Session, message_id: int) -> int:
    return db.query(MessageVote).filter(MessageVote.message_id == message_id).count()


def get_message_vote_counts_batch(db: Session, message_ids: List[int]) -> Dict[int, int]:
    """Return {message_id: vote_count} for the given message IDs. Reduces N+1 queries."""
    if not message_ids:
        return {}
    rows = (
        db.query(MessageVote.message_id, func.count(MessageVote.id).label("cnt"))
        .filter(MessageVote.message_id.in_(message_ids))
        .group_by(MessageVote.message_id)
        .all()
    )
    return {r[0]: r[1] for r in rows}


def get_usernames_by_ids(db: Session, user_ids: List[int]) -> Dict[int, str]:
    """Return {user_id: username} for the given user IDs. Reduces N+1 queries."""
    if not user_ids:
        return {}
    users = db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()
    return {u[0]: (u[1] or "") for u in users}


def get_group_insights(db: Session, group_id: int) -> Dict[str, Any]:
    """
    Group insights: most active users, top discussed topics, AI usage stats.
    """
    # Most active users (human messages only)
    active = (
        db.query(User.username, func.count(GroupMessage.id).label("cnt"))
        .join(GroupMessage, GroupMessage.user_id == User.id)
        .filter(GroupMessage.group_id == group_id, GroupMessage.message_type == "text")
        .group_by(User.id, User.username)
        .order_by(desc("cnt"))
        .limit(10)
        .all()
    )
    # AI usage stats
    ai_count = (
        db.query(func.count(GroupMessage.id))
        .filter(GroupMessage.group_id == group_id, GroupMessage.message_type == "ai")
        .scalar() or 0
    )
    # Simple "topics": words from non-AI messages
    messages = (
        db.query(GroupMessage.message)
        .filter(GroupMessage.group_id == group_id, GroupMessage.message_type == "text", GroupMessage.message.isnot(None))
        .all()
    )
    word_count: Dict[str, int] = {}
    for (text,) in messages:
        if not text:
            continue
        words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
        for w in words:
            word_count[w] = word_count.get(w, 0) + 1
    top_words = sorted(word_count.items(), key=lambda x: -x[1])[:15]
    return {
        "most_active_users": [{"username": a[0], "message_count": a[1]} for a in active],
        "top_discussed_topics": [{"topic": t[0], "count": t[1]} for t in top_words],
        "ai_usage_stats": {
            "ai_message_count": ai_count,
        },
    }


def user_can_pin(db: Session, group_id: int, user_id: int) -> bool:
    """Only admin can pin (or we could allow any member)."""
    m = (
        db.query(GroupMembership)
        .filter(GroupMembership.group_id == group_id, GroupMembership.user_id == user_id)
        .first()
    )
    return m is not None and m.role == "admin"


def clear_group_messages(db: Session, group_id: int) -> int:
    """
    Delete all messages in a group. Unpins first, then deletes all GroupMessage rows.
    Returns the number of messages deleted.
    """
    pinned = db.query(PinnedGroupMessage).filter(PinnedGroupMessage.group_id == group_id).first()
    if pinned:
        db.delete(pinned)
        db.commit()
    count = db.query(GroupMessage).filter(GroupMessage.group_id == group_id).delete()
    db.commit()
    return count


# ---------- Invite links ----------

def create_invite(
    db: Session,
    group_id: int,
    user_id: int,
    expires_in_days: int = 7,
    usage_limit: Optional[int] = None,
) -> GroupInvite:
    """Create a secure invite link for the group. Only members can create; typically admin."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    inv = GroupInvite(
        group_id=group_id,
        token=token,
        expires_at=expires_at,
        usage_limit=usage_limit,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def get_invite_by_token(db: Session, token: str) -> Optional[GroupInvite]:
    """Get invite by token. Returns None if not found, expired, or usage limit reached."""
    inv = db.query(GroupInvite).filter(GroupInvite.token == token).first()
    if not inv:
        return None
    if inv.expires_at and inv.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None
    if inv.usage_limit is not None and inv.used_count >= inv.usage_limit:
        return None
    return inv


def use_invite(db: Session, invite: GroupInvite, user: User) -> GroupMembership:
    """Consume invite: add user to group (idempotent), increment used_count. Returns membership."""
    inv = db.query(GroupInvite).filter(GroupInvite.id == invite.id).first()
    if not inv:
        raise ValueError("Invite not found")
    membership = join_group(db, inv.group_id, user)
    inv.used_count += 1
    db.commit()
    return membership


def set_message_delivered(db: Session, message_id: int, group_id: int) -> bool:
    """Mark a group message as delivered. Returns True if updated."""
    msg = db.query(GroupMessage).filter(
        GroupMessage.id == message_id,
        GroupMessage.group_id == group_id,
    ).first()
    if not msg:
        return False
    msg.message_status = "delivered"
    db.commit()
    return True
