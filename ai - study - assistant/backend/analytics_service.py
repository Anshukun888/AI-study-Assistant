"""
Analytics service for weak topic detection and user performance tracking.
"""
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from backend.models import UserTopicStats
from backend.chat_service import sanitize_user_input


# Weak score thresholds: weak_score = wrong_attempts / total_attempts
LEVEL_WEAK = "Weak"
LEVEL_MEDIUM = "متوسط"  # Medium
LEVEL_STRONG = "Strong"


def update_topic_stats(
    db: Session,
    user_id: int,
    topic: str,
    is_correct: bool,
) -> UserTopicStats:
    """
    Update or create user topic stats for one attempt.
    Returns the updated/created UserTopicStats row.
    """
    topic = sanitize_user_input(topic or "", 255).strip()
    if not topic:
        raise ValueError("Topic cannot be empty")

    row = (
        db.query(UserTopicStats)
        .filter(UserTopicStats.user_id == user_id, UserTopicStats.topic == topic)
        .first()
    )
    if not row:
        row = UserTopicStats(
            user_id=user_id,
            topic=topic,
            total_attempts=0,
            correct_attempts=0,
            wrong_attempts=0,
        )
        db.add(row)
        db.flush()

    row.total_attempts += 1
    if is_correct:
        row.correct_attempts += 1
    else:
        row.wrong_attempts += 1
    db.commit()
    db.refresh(row)
    return row


def get_weak_topics(db: Session, user_id: int) -> List[Dict[str, Any]]:
    """
    Return topics with weak_score and level (Weak / Medium / Strong).
    weak_score = wrong_attempts / total_attempts; avoid division by zero.
    """
    rows = (
        db.query(UserTopicStats)
        .filter(UserTopicStats.user_id == user_id, UserTopicStats.total_attempts > 0)
        .all()
    )
    result: List[Dict[str, Any]] = []
    for row in rows:
        total = row.total_attempts
        if total <= 0:
            continue
        wrong = row.wrong_attempts or 0
        weak_score = round(wrong / total, 2)
        if weak_score > 0.6:
            level = LEVEL_WEAK
        elif weak_score >= 0.3:
            level = LEVEL_MEDIUM
        else:
            level = LEVEL_STRONG
        result.append({
            "topic": row.topic,
            "weak_score": weak_score,
            "level": level,
        })
    return result
