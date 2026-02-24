"""
Chat service for AI Study Assistant.
Handles conversation creation, message persistence, and chat mode logic.
"""
import json
import os
import re
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import User, Conversation, Message, Document, ChatMode


# System prompts - never exposed to client
SYSTEM_PROMPT_FREE = (
    "You are a top teacher: explain clearly and intelligently. "
    "Be clear, structured, student-friendly, and high quality. "
    "Avoid unnecessary long text; keep it structured but natural."
)
SYSTEM_PROMPT_DOCUMENT = (
    "Use the provided document as your PRIMARY source. "
    "Use general knowledge as BACKUP to enrich and complete answers. "
    "Do NOT limit your explanation only to the PDF; add clarity and context from general knowledge where helpful. "
    "If the answer is not in the document at all, say so and offer what you can from general knowledge."
)
SYSTEM_PROMPT_NOTES = (
    "Answer only using the provided notes/content. "
    "If the answer is not in the provided content, say: 'The answer is not in the provided content.' "
    "Do not add external information."
)


def sanitize_user_input(text: str, max_length: int = 10000) -> str:
    """
    Sanitize user input to prevent prompt injection.
    Remove or escape suspicious patterns.
    """
    if not text or not isinstance(text, str):
        return ""
    # Limit length
    text = text[:max_length]
    # Remove potential system prompt overrides (case-insensitive)
    patterns = [
        r"ignore\s+(all\s+)?previous\s+instructions?",
        r"disregard\s+(all\s+)?previous",
        r"you\s+are\s+now\s+",
        r"pretend\s+you\s+are",
        r"act\s+as\s+if\s+you\s+are",
        r"\[system\]",
        r"<\|im_start\|>system",
    ]
    for p in patterns:
        text = re.sub(p, "[removed]", text, flags=re.IGNORECASE)
    return text.strip()


def get_system_prompt(mode: str, document: Optional[Document], notes_context: Optional[str]) -> str:
    """Return the system prompt for the given chat mode."""
    if mode == ChatMode.DOCUMENT.value and document:
        return SYSTEM_PROMPT_DOCUMENT
    if mode == ChatMode.NOTES.value and notes_context:
        return SYSTEM_PROMPT_NOTES
    return SYSTEM_PROMPT_FREE


def create_conversation(
    db: Session,
    user: User,
    title: str = "New Chat",
    mode: str = ChatMode.FREE.value,
    document_id: Optional[int] = None,
    notes_context: Optional[str] = None,
) -> Conversation:
    """Create a new conversation for the user."""
    conv = Conversation(
        user_id=user.id,
        title=title,
        mode=mode,
        document_id=document_id,
        notes_context=sanitize_user_input(notes_context or "", 50000),
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def get_conversation_for_user(db: Session, conv_id: int, user_id: int) -> Optional[Conversation]:
    """Get conversation by ID if it belongs to the user."""
    return (
        db.query(Conversation)
        .filter(Conversation.id == conv_id, Conversation.user_id == user_id)
        .first()
    )


def get_user_conversations(db: Session, user_id: int, limit: int = 50) -> list[Conversation]:
    """Get conversations for a user, most recent first."""
    return (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .all()
    )


def add_message(
    db: Session,
    conversation_id: int,
    role: str,
    content: str,
    document_id: Optional[int] = None,
) -> Message:
    """Add a message to a conversation."""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=sanitize_user_input(content),
        document_id=document_id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_messages(db: Session, conversation_id: int) -> list[Message]:
    """Get all messages in a conversation in order."""
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )


def get_context_for_ai(
    db: Session,
    conversation: Conversation,
) -> str:
    """
    Build context string for AI based on mode:
    - FREE: no extra context
    - DOCUMENT: document text loaded from disk
    - NOTES: notes_context
    """
    if conversation.mode == ChatMode.DOCUMENT.value and conversation.document_id:
        doc = db.query(Document).filter(Document.id == conversation.document_id).first()
        if doc and doc.content_path:
            try:
                if os.path.exists(doc.content_path):
                    with open(doc.content_path, "r", encoding="utf-8") as f:
                        return f.read()
            except OSError:
                # Fall through to empty context if file can't be read
                pass
    if conversation.mode == ChatMode.NOTES.value and conversation.notes_context:
        return conversation.notes_context
    return ""


def get_document_text_for_user(
    db: Session,
    document_id: int,
    user_id: int,
) -> Optional[str]:
    """
    Get full text of a document if it exists and belongs to the user.
    Returns None if document not found, not owned by user, or file unreadable.
    """
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.user_id == user_id)
        .first()
    )
    if not doc or not doc.content_path:
        return None
    try:
        if os.path.exists(doc.content_path):
            with open(doc.content_path, "r", encoding="utf-8") as f:
                return f.read()
    except OSError:
        pass
    return None


def update_conversation_title(db: Session, conversation: Conversation, title: str) -> None:
    """Update conversation title."""
    conversation.title = sanitize_user_input(title, 255) or "New Chat"
    db.commit()
