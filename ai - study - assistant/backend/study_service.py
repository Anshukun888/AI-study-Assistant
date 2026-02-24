"""
Study service for AI Study Assistant.
Handles study plans, smart revision planner, and practice question generation.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from backend.models import User, StudyPlan
from backend.chat_service import sanitize_user_input
from backend.analytics_service import get_weak_topics
from backend.ai_service import call_ollama


def create_study_plan(
    db: Session,
    user: User,
    topic: str,
    plan_type: str = "weekly",
    document_id: Optional[int] = None,
) -> StudyPlan:
    """Create a new study plan."""
    topic = sanitize_user_input(topic, 1000)
    if not topic:
        raise ValueError("Topic cannot be empty")

    if plan_type not in ("daily", "weekly", "monthly"):
        plan_type = "weekly"

    plan = StudyPlan(
        user_id=user.id,
        title=f"{plan_type.capitalize()} Study Plan: {topic[:50]}",
        topic=topic,
        plan_type=plan_type,
        content="",  # Will be filled by AI
        document_id=document_id,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def get_user_study_plans(db: Session, user_id: int, limit: int = 50) -> List[StudyPlan]:
    """Get study plans for a user."""
    return (
        db.query(StudyPlan)
        .filter(StudyPlan.user_id == user_id)
        .order_by(StudyPlan.created_at.desc())
        .limit(limit)
        .all()
    )


# Max topics per day in revision plan
MAX_TOPICS_PER_DAY = 3
MIN_TOPICS_PER_DAY = 2


def build_revision_plan(
    db: Session,
    user_id: int,
    exam_date_str: str,
    topic_importance: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    Generate a study plan from today until exam_date: weak topics first, then by importance.
    Sort by weakness DESC, then importance DESC. Distribute 2-3 topics per day.
    """
    topic_importance = topic_importance or {}
    weak = get_weak_topics(db, user_id)
    # Sort by weak_score DESC (weakest first), then importance DESC
    weak.sort(
        key=lambda x: (
            -x["weak_score"],
            -(topic_importance.get(x["topic"], 0)),
        ),
    )
    topics_ordered = [x["topic"] for x in weak]
    if not topics_ordered:
        return {"plan": [], "message": "No weak topics to plan. Complete practice to get recommendations."}

    try:
        exam_date = datetime.strptime(exam_date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        exam_date = (datetime.now(timezone.utc) + timedelta(days=30)).date()
    today = datetime.now(timezone.utc).date()
    if exam_date <= today:
        return {"plan": [], "message": "Exam date must be in the future."}
    days_count = (exam_date - today).days
    if days_count <= 0:
        return {"plan": [], "message": "No days until exam."}

    plan: List[Dict[str, Any]] = []
    idx = 0
    for day_num in range(1, days_count + 1):
        if idx >= len(topics_ordered):
            break
        # 2-3 topics per day
        n = min(MAX_TOPICS_PER_DAY, len(topics_ordered) - idx)
        if n < MIN_TOPICS_PER_DAY and idx + n < len(topics_ordered):
            n = min(MAX_TOPICS_PER_DAY, len(topics_ordered) - idx)
        day_topics = topics_ordered[idx : idx + n]
        idx += n
        plan.append({"day": day_num, "topics": day_topics})
    return {"plan": plan}


async def generate_practice_questions(
    topic: str,
    difficulty: str = "medium",
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate 3 MCQs and 2 short-answer questions for the given topic and difficulty.
    Each question includes correct answer and explanation.
    """
    topic = sanitize_user_input(topic or "", 255).strip()
    if not topic:
        raise ValueError("Topic cannot be empty")
    difficulty = (difficulty or "medium").strip().lower()
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "medium"

    prompt = f"""Generate practice questions for the topic: "{topic}", difficulty: {difficulty}.

Output a single JSON object with this exact structure (no other text):
{{
  "mcqs": [
    {{
      "question": "Question text?",
      "options": ["A", "B", "C", "D"],
      "correct_index": 0,
      "correct_answer": "A",
      "explanation": "Brief explanation of the correct answer."
    }}
  ],
  "short_questions": [
    {{
      "question": "Short question text?",
      "correct_answer": "Expected answer.",
      "explanation": "Brief explanation."
    }}
  ]
}}

Rules:
- Provide exactly 3 items in "mcqs" and exactly 2 items in "short_questions".
- For mcqs, correct_index is 0-based (0 = first option). Include correct_answer as the text of the right option.
- All questions must be on the topic "{topic}" and at {difficulty} level.
- Return only valid JSON, no markdown fences."""

    import json
    response = await call_ollama(prompt, num_predict=4096, request_id=request_id)
    out: Dict[str, Any] = {"mcqs": [], "short_questions": []}
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start != -1 and end > start:
            parsed = json.loads(response[start:end])
            mcqs = parsed.get("mcqs") or []
            shorts = parsed.get("short_questions") or []
            for m in mcqs[:3]:
                if isinstance(m, dict) and m.get("question"):
                    out["mcqs"].append({
                        "question": str(m.get("question", "")).strip(),
                        "options": m.get("options") or [],
                        "correct_index": int(m.get("correct_index", 0)) if m.get("correct_index") is not None else 0,
                        "correct_answer": str(m.get("correct_answer", "")).strip(),
                        "explanation": str(m.get("explanation", "")).strip(),
                    })
            for s in shorts[:2]:
                if isinstance(s, dict) and s.get("question"):
                    out["short_questions"].append({
                        "question": str(s.get("question", "")).strip(),
                        "correct_answer": str(s.get("correct_answer", "")).strip(),
                        "explanation": str(s.get("explanation", "")).strip(),
                    })
    except (json.JSONDecodeError, TypeError):
        pass
    return out
