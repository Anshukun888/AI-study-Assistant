"""
AI Exam Intelligence System: analyze past exam papers (PDF/images/text) and optional study materials.
Extracts questions, detects patterns (theory, coding, case-based, definitions), difficulty trends,
and examiner preferences. Generates high-quality predicted exam questions with importance and revision strategy.
"""
import re
import json
from typing import List, Dict, Any, Optional, Tuple

from backend.ai_service import call_ollama

INSUFFICIENT_DATA_MESSAGE = "I cannot confidently predict based on the provided data."

# Minimum length for a valid question (avoid headers/footers)
MIN_QUESTION_LEN = 15
# Maximum questions to send to AI (avoid token overflow)
MAX_QUESTIONS_FOR_AI = 150

# Question types and probabilities we expect from AI
QUESTION_TYPES = ("Theory", "Practical", "Coding", "Case Study")
PROBABILITIES = ("High", "Medium", "Low")


def extract_questions_from_text(text: str) -> List[str]:
    """
    Extract and clean individual questions from document text.
    Handles common patterns: "Q1.", "1.", "Question 1", "(a)", "Section A", etc.
    """
    if not text or not text.strip():
        return []

    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    parts = re.split(
        r"\n\s*(?=(?:Q\.?\s*\d+\.?|Q\s*\d+[\.\):]|\d+[\.\)]\s+|\d+\.\s+[A-Z]|Question\s+\d+[\.\):]?|QUESTION\s+\d+[\.\):]?|Section\s+[A-Z\d]+[\.\):]?|Part\s+\([a-z]\)|\(\s*[a-z]\s*\)\s+))\s*",
        normalized,
        flags=re.IGNORECASE,
    )

    questions: List[str] = []
    for part in parts:
        cleaned = re.sub(
            r"^(?:Q\.?\s*\d+\.?|Q\s*\d+[\.\):]|\d+[\.\)]\s*|\d+\.\s*|Question\s+\d+[\.\):]?|QUESTION\s+\d+[\.\):]?|Section\s+[A-Z\d]+[\.\):]?|Part\s+\([a-z]\)|\(\s*[a-z]\s*\))\s*",
            "",
            part.strip(),
            count=1,
            flags=re.IGNORECASE,
        )
        cleaned = cleaned.strip()
        if len(cleaned) < MIN_QUESTION_LEN:
            continue
        words = cleaned.split()
        if len(words) < 3:
            continue
        if cleaned.isupper() and len(cleaned) < 80:
            continue
        questions.append(cleaned[:2000])

    if len(questions) <= 1 and len(normalized) > 100:
        by_q = re.split(r"\n\s*\n+", normalized)
        for block in by_q:
            block = block.strip()
            if len(block) >= MIN_QUESTION_LEN and len(block.split()) >= 3:
                questions.append(block[:2000])
    return questions[:MAX_QUESTIONS_FOR_AI]


async def _extract_topics_from_questions(questions: List[str], request_id: Optional[str] = None) -> List[str]:
    """Extract topic names from questions for one paper. Returns list of topic strings."""
    if not questions:
        return []
    blob = "\n".join(f"{i+1}. {q[:500]}" for i, q in enumerate(questions[:50]))
    prompt = f"""From the following exam questions, list ONLY the main topics/subjects covered. One topic per line, no numbering. Use only what is clearly stated or strongly implied. Do not invent topics.

Questions:
---
{blob}
---

Reply with a JSON array of topic strings, e.g. ["Binary Search", "Recursion"]. Nothing else."""
    try:
        response = await call_ollama(prompt, num_predict=512, request_id=request_id)
        start = response.find("[")
        end = response.rfind("]") + 1
        if start != -1 and end > start:
            topics = json.loads(response[start:end])
            if isinstance(topics, list):
                return [str(t).strip() for t in topics if t and str(t).strip()][:30]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _compute_topic_scores(
    topic_frequency: Dict[str, int],
    total_papers: int,
) -> Dict[str, Tuple[int, float]]:
    """
    importance_score (1-5) = round((frequency / total_papers) * 5)
    confidence_score (0-100) = (frequency / total_papers) * 100
    Returns dict: topic -> (importance, confidence).
    """
    if total_papers <= 0:
        return {}
    result: Dict[str, Tuple[int, float]] = {}
    for topic, freq in topic_frequency.items():
        ratio = freq / total_papers
        importance = max(1, min(5, round(ratio * 5)))
        confidence = round(ratio * 100, 1)
        confidence = max(0, min(100, confidence))
        result[topic] = (importance, confidence)
    return result


EXAM_PREDICTOR_SYSTEM = """You are an AI Exam Intelligence System. You analyze past exam papers and optional study materials using pattern recognition.

ANALYSIS REQUIREMENTS:
- Identify frequently repeated topics (cite evidence: e.g. "appears in 4 of 5 papers").
- Detect question patterns: Theory (define, explain, list), Practical (write steps, demonstrate), Coding (implement, program, code), Case Study (scenario-based).
- Analyze difficulty trends: easy (short definitions, one-liners), medium (explain with examples), hard (implement, design).
- Detect examiner preferences: e.g. frequent use of "define", "explain", "implement", "write a program".

OUTPUT RULES:
- Base ALL analysis ONLY on the provided questions. Do NOT invent topics or questions not present or clearly implied.
- Predicted questions must look like REAL exam questions: clean, professional, exam-level wording.
- Do NOT repeat similar questions; cover multiple topics; prioritize high-probability items.
- If past questions are unclear, infer patterns intelligently but do NOT hallucinate.
- Return ONLY valid JSON. No markdown code fences, no extra text before or after."""


def _stars(n: int) -> str:
    """Return 1-5 star string."""
    n = max(1, min(5, int(n)))
    return "".join(["⭐"] * n)


def _normalize_predicted_item(
    item: Any,
    topic_scores: Optional[Dict[str, Tuple[int, float]]] = None,
) -> Dict[str, Any]:
    """
    Ensure one predicted question has topic, importance (1-5), confidence (0-100), question_type,
    probability, question, why_important. confidence_score is always numeric 0-100.
    """
    if isinstance(item, str):
        out = {
            "topic": "General",
            "importance": 3,
            "confidence": 50,
            "question_type": "Theory",
            "probability": "Medium",
            "question": item,
            "why_important": "Based on pattern in past papers.",
            "hint": "",
        }
        return out
    if not isinstance(item, dict):
        return _normalize_predicted_item(str(item), topic_scores)
    importance = item.get("importance")
    if isinstance(importance, str) and "⭐" in importance:
        importance = min(5, max(1, importance.count("⭐") or 3))
    elif isinstance(importance, (int, float)):
        importance = min(5, max(1, int(importance)))
    else:
        importance = 3
    topic = (item.get("topic") or "General").strip() or "General"
    confidence = 50
    if topic_scores and topic in topic_scores:
        imp, conf = topic_scores[topic]
        importance = imp
        confidence = int(round(conf))
    else:
        # Fallback from item if present and numeric
        c = item.get("confidence") or item.get("confidence_score")
        if isinstance(c, (int, float)):
            confidence = max(0, min(100, int(round(c))))
    qt = (item.get("question_type") or "Theory").strip()
    if qt not in QUESTION_TYPES:
        qt = "Theory"
    prob = (item.get("probability") or "Medium").strip()
    if prob not in PROBABILITIES:
        prob = "Medium"
    hint = (item.get("hint") or "").strip()
    return {
        "topic": topic,
        "importance": importance,
        "confidence": confidence,
        "question_type": qt,
        "probability": prob,
        "question": (item.get("question") or item.get("text") or "").strip() or "No question text.",
        "why_important": (item.get("why_important") or item.get("reason") or "Based on pattern in past papers.").strip(),
        "hint": hint,
    }


def build_formatted_output(result: Dict[str, Any], subject_or_topic: str = "Exam") -> str:
    """
    Build a clean, human-readable formatted string for saving to a session.
    No code blocks, no raw JSON; exam-ready revision format.
    """
    lines: List[str] = []
    lines.append("Predicted Exam Questions")
    lines.append("")
    lines.append("Subject/Topic: " + (subject_or_topic or "Exam"))
    lines.append("")

    topic_scores = result.get("topic_scores")
    predicted = result.get("predicted_questions") or []
    for i, item in enumerate(predicted, 1):
        p = _normalize_predicted_item(item, topic_scores)
        stars = _stars(p["importance"])
        lines.append(f"{i}. Topic: {p['topic']}")
        lines.append(f"   Importance: {stars} (1-5 scale based on frequency)")
        lines.append(f"   Confidence: {p.get('confidence', 50)}%")
        lines.append(f"   Question Type: {p['question_type']}")
        lines.append(f"   Probability: {p['probability']}")
        lines.append("")
        lines.append("   Question:")
        lines.append("   " + p["question"])
        lines.append("")
        lines.append("   Why this is important:")
        lines.append("   " + p["why_important"])
        lines.append("")

    most = result.get("most_important_topics") or []
    if most:
        lines.append("Most Important Topics")
        lines.append("")
        for t in most:
            name = t if isinstance(t, str) else (t.get("topic") or t.get("name") or str(t))
            lines.append("- " + name)
        lines.append("")

    strategy = result.get("revision_strategy") or []
    if isinstance(strategy, str):
        strategy = [strategy] if strategy.strip() else []
    if strategy:
        lines.append("Revision Strategy")
        lines.append("")
        for s in strategy:
            line = s if isinstance(s, str) else str(s)
            if line.strip():
                lines.append("- " + line.strip())
        lines.append("")

    return "\n".join(lines).strip()


# Prefix for messages that contain predicted-questions HTML (for chat/export detection)
PREDICTED_QUESTIONS_PREFIX = "<!-- PREDICTED_QUESTIONS -->"


def _escape_html(s: str) -> str:
    """Escape for safe HTML."""
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_formatted_output_html(
    result: Dict[str, Any],
    subject_or_topic: str = "Exam",
    created_at: Optional[str] = None,
) -> str:
    """
    Build HTML for predicted questions to display in chat and export.
    Includes numbered questions, optional hints (toggleable), and styling classes.
    """
    lines: List[str] = []
    subject = (subject_or_topic or "Exam").strip() or "Exam"
    lines.append('<div class="predicted-questions-block">')
    lines.append('<div class="pq-header">')
    lines.append("<h3 class=\"pq-title\">Predicted Exam Questions</h3>")
    lines.append(f"<p class=\"pq-subject\">Subject/Topic: {_escape_html(subject)}</p>")
    if created_at:
        lines.append(f"<p class=\"pq-meta pq-timestamp\">Generated: {_escape_html(created_at)}</p>")
    lines.append("</div>")

    topic_scores = result.get("topic_scores")
    predicted = result.get("predicted_questions") or []
    lines.append('<div class="pq-list">')
    for i, item in enumerate(predicted, 1):
        p = _normalize_predicted_item(item, topic_scores)
        stars = _stars(p["importance"])
        hint = (p.get("hint") or "").strip()
        lines.append('<div class="pq-card pq-question-item" data-question-index="' + str(i - 1) + '">')
        lines.append('  <div class="pq-question-row">')
        lines.append('    <label class="pq-checkbox-wrap">')
        lines.append('      <input type="checkbox" class="pq-solved-checkbox" data-index="' + str(i - 1) + '" aria-label="Mark as solved">')
        lines.append('      <span class="pq-number">' + str(i) + ".</span>")
        lines.append("    </label>")
        lines.append('    <div class="pq-question-body">')
        lines.append('      <p class="pq-question-text"><strong>' + _escape_html(p["question"]) + "</strong></p>")
        lines.append('      <div class="pq-meta-row">')
        lines.append('        <span class="pq-topic">Topic: ' + _escape_html(p["topic"]) + "</span>")
        lines.append('        <span class="pq-importance">' + _escape_html(stars) + "</span>")
        lines.append('        <span class="pq-confidence">Confidence: ' + str(p.get("confidence", 50)) + "%</span>")
        lines.append('        <span class="pq-badge pq-type">' + _escape_html(p["question_type"]) + "</span>")
        lines.append('        <span class="pq-badge pq-prob">' + _escape_html(p["probability"]) + "</span>")
        lines.append("      </div>")
        lines.append('      <p class="pq-why">' + _escape_html(p["why_important"]) + "</p>")
        if hint:
            lines.append('      <div class="pq-hint-wrap">')
            lines.append('        <button type="button" class="pq-hint-toggle btn btn-sm btn-outline-secondary">Show hint</button>')
            lines.append('        <p class="pq-hint-text" style="display:none;">' + _escape_html(hint) + "</p>")
            lines.append("      </div>")
        lines.append("    </div>")
        lines.append("  </div>")
        lines.append("</div>")
    lines.append("</div>")

    most = result.get("most_important_topics") or []
    if most:
        lines.append('<div class="pq-section">')
        lines.append("<h4 class=\"pq-section-title\">Most Important Topics</h4>")
        lines.append("<ul class=\"pq-topics-list\">")
        for t in most:
            name = t if isinstance(t, str) else (t.get("topic") or t.get("name") or str(t))
            lines.append("<li>" + _escape_html(name) + "</li>")
        lines.append("</ul>")
        lines.append("</div>")

    strategy = result.get("revision_strategy") or []
    if isinstance(strategy, str):
        strategy = [strategy] if strategy.strip() else []
    if strategy:
        lines.append('<div class="pq-section">')
        lines.append("<h4 class=\"pq-section-title\">Revision Strategy</h4>")
        lines.append("<ul class=\"pq-strategy-list\">")
        for s in strategy:
            line = s if isinstance(s, str) else str(s)
            if line.strip():
                lines.append("<li>" + _escape_html(line.strip()) + "</li>")
        lines.append("</ul>")
        lines.append("</div>")

    lines.append("</div>")
    return PREDICTED_QUESTIONS_PREFIX + "\n" + "\n".join(lines)


async def predict_exam_from_questions(
    questions: List[str],
    topic_scores: Optional[Dict[str, Tuple[int, float]]] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Use AI to analyze extracted questions. Returns important topics, repeated questions,
    predicted questions (with topic, importance, type, probability, why_important),
    most_important_topics (top 5-10), and revision_strategy.
    """
    if not questions:
        return {
            "important_topics": [],
            "repeated_questions": [],
            "predicted_questions": [],
            "most_important_topics": [],
            "revision_strategy": [],
            "message": "No questions to analyze.",
        }

    questions_blob = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions[:MAX_QUESTIONS_FOR_AI]))

    prompt = f"""Analyze these past exam questions. Identify frequently repeated topics, question patterns (Theory, Practical, Coding, Case Study), difficulty trends, and examiner preferences (e.g. "define", "explain", "implement").

List of questions from past papers:
---
{questions_blob}
---

Return a single JSON object with exactly this structure (no other text):
{{
  "important_topics": [
    {{ "topic": "<topic name>", "frequency": "High|Medium|Low", "reason": "<brief evidence>" }}
  ],
  "repeated_questions": [
    {{ "question": "<exact or representative question>", "times_asked": <number >= 2> }}
  ],
  "predicted_questions": [
    {{
      "topic": "<Topic Name>",
      "importance": <1 to 5>,
      "question_type": "Theory|Practical|Coding|Case Study",
      "probability": "High|Medium|Low",
      "question": "<Well-structured exam-level question>",
      "why_important": "<Short reasoning based on repetition/pattern>",
      "hint": "<Optional one-line hint for the student>"
    }}
  ],
  "most_important_topics": [
    "<topic 1>",
    "<topic 2>",
    ...
  ],
  "revision_strategy": [
    "<Suggest what to study first based on probability>",
    ...
  ]
}}

Rules: Only include topics and questions justified from the list. Do not hallucinate. Give exactly 10-15 predicted_questions (aim for 12); 5-10 most_important_topics; 3-6 revision_strategy items. Questions must look like real exam questions. For each predicted_questions item you may add an optional "hint" (one short line) to help the student without giving the full answer."""

    response = await call_ollama(
        prompt,
        system_prompt=EXAM_PREDICTOR_SYSTEM,
        num_predict=4096,
        request_id=request_id,
    )

    out: Dict[str, Any] = {
        "important_topics": [],
        "repeated_questions": [],
        "predicted_questions": [],
        "most_important_topics": [],
        "revision_strategy": [],
    }
    try:
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            raw = response[json_start:json_end]
            parsed = json.loads(raw)
            out["important_topics"] = parsed.get("important_topics") or []
            out["repeated_questions"] = parsed.get("repeated_questions") or []
            raw_pred = parsed.get("predicted_questions") or []
            normalized = [_normalize_predicted_item(x, topic_scores) for x in raw_pred if x]
            # Enforce 10-15: take first 15; if we have fewer than 10, keep as-is (AI may return fewer)
            out["predicted_questions"] = normalized[:15]
            out["most_important_topics"] = parsed.get("most_important_topics") or []
            out["revision_strategy"] = parsed.get("revision_strategy") or []

            if not isinstance(out["important_topics"], list):
                out["important_topics"] = []
            if not isinstance(out["repeated_questions"], list):
                out["repeated_questions"] = []
            if not isinstance(out["most_important_topics"], list):
                out["most_important_topics"] = list(out["most_important_topics"]) if out["most_important_topics"] else []
            if not isinstance(out["revision_strategy"], list):
                out["revision_strategy"] = [out["revision_strategy"]] if out["revision_strategy"] else []

            for t in out["important_topics"]:
                if isinstance(t, dict):
                    continue
                if isinstance(t, str):
                    out["important_topics"] = [
                        {"topic": x, "frequency": "Medium", "reason": "From analysis"} if isinstance(x, str) else x
                        for x in out["important_topics"]
                    ]
                break
            for r in out["repeated_questions"]:
                if isinstance(r, dict) and "times_asked" in r:
                    r["times_asked"] = int(r["times_asked"]) if r["times_asked"] else 2
                break
    except (json.JSONDecodeError, TypeError):
        out["message"] = "Could not parse AI response. Try again or add more question content."
    if topic_scores:
        out["topic_scores"] = topic_scores
    return out


async def predict_from_document_text(
    text: str,
    subject_or_topic: Optional[str] = None,
    additional_texts: Optional[List[str]] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full pipeline: extract questions from document text(s), compute topic frequency across papers,
    assign importance_score (1-5) and confidence_score (0-100), run prediction. Returns structured
    result with strict JSON-style predicted_questions (topic, importance, confidence, question_type,
    probability, question, why_important). If insufficient data, returns explicit message.
    """
    paper_texts = [text]
    if additional_texts:
        paper_texts.extend(t for t in additional_texts if t and t.strip())
    all_questions: List[str] = []
    topic_frequency: Dict[str, int] = {}
    for paper_text in paper_texts:
        questions = extract_questions_from_text(paper_text)
        if not questions:
            continue
        all_questions.extend(questions)
        topics = await _extract_topics_from_questions(questions, request_id=request_id)
        for t in topics:
            topic_frequency[t] = topic_frequency.get(t, 0) + 1

    total_papers = len(paper_texts)
    if total_papers == 0 or not all_questions:
        return {
            "important_topics": [],
            "repeated_questions": [],
            "predicted_questions": [],
            "most_important_topics": [],
            "revision_strategy": [],
            "formatted_output": "",
            "topic_scores": {},
            "message": INSUFFICIENT_DATA_MESSAGE,
        }

    topic_scores = _compute_topic_scores(topic_frequency, total_papers)
    result = await predict_exam_from_questions(all_questions, topic_scores=topic_scores, request_id=request_id)
    result["extracted_count"] = len(all_questions)
    result["topic_scores"] = topic_scores
    subject = (subject_or_topic or "Exam").strip() or "Exam"
    result["formatted_output"] = build_formatted_output(result, subject)
    return result
