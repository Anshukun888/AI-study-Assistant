"""
AI service for interacting with Ollama API.
Handles chat modes, tool prompts, chunking, timeouts, and token limits.
Optimized for 8GB RAM: chunk context, limit tokens.
"""
import httpx
import json
import os
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
from fastapi import HTTPException, status

from backend.pdf_service import chunk_text, find_page_for_text
from backend.cancel_store import is_cancelled, GenerationCancelledError

load_dotenv()

# --- Intent detection: understand what the student wants ---
INTENT_DEFINE = "define"
INTENT_EXPLAIN = "explain"
INTENT_STEP_BY_STEP = "step_by_step"
INTENT_EXAMPLE = "example"
INTENT_GENERAL = "general"


def detect_intent(user_input: str) -> str:
    """
    Detect user intent from the message to tailor AI response.
    - "What is", "Define" → short definition only
    - "Explain", "How", "Why" → detailed explanation with steps, example, key points
    - "Step by step" → structured steps
    - "Example" → include example
    Returns one of: define, explain, step_by_step, example, general.
    """
    if not user_input or not isinstance(user_input, str):
        return INTENT_GENERAL
    text = user_input.strip().lower()
    if len(text) < 2:
        return INTENT_GENERAL
    # Define: short definition only (2–3 lines)
    if any(text.startswith(p) for p in ("what is ", "what are ", "define ", "definition of ")):
        return INTENT_DEFINE
    if " what is " in text or " what are " in text:
        return INTENT_DEFINE
    # Step by step: user explicitly wants steps
    if "step by step" in text or "step-by-step" in text or " steps " in text or "walk me through" in text:
        return INTENT_STEP_BY_STEP
    # Example: user wants an example
    if "example" in text or "give an example" in text or "show me an example" in text or "e.g." in text:
        return INTENT_EXAMPLE
    # Explain: detailed explanation (how, why, explain)
    if any(text.startswith(p) for p in ("explain ", "how ", "why ", "how does ", "why does ", "how do ", "why do ")):
        return INTENT_EXPLAIN
    if " explain " in text or " how " in text or " why " in text:
        return INTENT_EXPLAIN
    return INTENT_GENERAL


def _get_intent_instruction(intent: str) -> str:
    """
    Return strict instruction for the AI based on intent.
    Do NOT mix modes; do NOT over-explain when user asked for definition.
    """
    if intent == INTENT_DEFINE:
        return (
            "\n\nRESPONSE MODE: DEFINITION. The user asked for a definition. "
            "Give ONLY a short, clear definition in 2–3 lines. Do NOT add steps, examples, or long explanation. "
            "Be concise and precise."
        )
    if intent == INTENT_EXPLAIN:
        return (
            "\n\nRESPONSE MODE: EXPLANATION. The user asked for an explanation. "
            "Use this exact structure: "
            "1. Simple Explanation (easy language), "
            "2. Step-by-Step Breakdown, "
            "3. Real-Life Example, "
            "4. Key Points Summary. "
            "Keep it clear, student-friendly, and avoid unnecessary length."
        )
    if intent == INTENT_STEP_BY_STEP:
        return (
            "\n\nRESPONSE MODE: STEP-BY-STEP. The user wants a step-by-step breakdown. "
            "Structure your response as numbered steps (1. 2. 3.). Be clear and sequential. "
            "You may include a brief example if it helps."
        )
    if intent == INTENT_EXAMPLE:
        return (
            "\n\nRESPONSE MODE: EXAMPLE. The user wants an example. "
            "Include a clear, concrete example. Keep explanation around it brief."
        )
    return ""


# --- Response quality: hackathon-winning, top-teacher style ---
RESPONSE_QUALITY_RULES = (
    "Respond like a top teacher: clear, structured, student-friendly, high quality. "
    "Avoid unnecessary long text. Keep it structured but natural. "
)
RESPONSE_FORMAT_CLEAN = (
    "Use clean readable text: avoid markdown symbols like *, -, ** for lists. "
    "Use numbered lists (1. 2. 3.) and clear paragraphs. "
    "No HTML tags. Structure with simple labels (e.g. 'Simple explanation:', 'Key points:') if needed."
)

# Ollama configuration
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_MODEL_FAST = os.getenv("OLLAMA_MODEL_FAST", "qwen2.5:3b")  # Fast model for quick responses
OLLAMA_MODEL_REASONING = os.getenv("OLLAMA_MODEL_REASONING", "qwen2.5:3b")  # Reasoning-heavy model
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "12000"))  # ~3k tokens
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))


def _ollama_url() -> str:
    return f"{OLLAMA_BASE.rstrip('/')}/api/generate"


async def call_ollama(
    prompt: str,
    system_prompt: Optional[str] = None,
    num_predict: int = 2048,
    model: Optional[str] = None,
    request_id: Optional[str] = None,
) -> str:
    """
    Call Ollama API with a prompt. Raises GenerationCancelledError if request_id was cancelled.
    """
    if request_id and is_cancelled(request_id):
        raise GenerationCancelledError("Cancelled")
    model_to_use = model or OLLAMA_MODEL
    payload = {
        "model": model_to_use,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "top_p": 0.9,
            "num_predict": num_predict,
        },
    }
    if system_prompt:
        payload["system"] = system_prompt

    try:
        # Explicit 300s timeout window for long generations
        timeout = httpx.Timeout(OLLAMA_TIMEOUT, read=OLLAMA_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(_ollama_url(), json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get("response", "").strip()
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI service timeout. The request took too long to process.",
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI service unavailable: {str(e)}. Make sure Ollama is running.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error calling AI service: {str(e)}",
        )


def _clean_markdown(text: str) -> str:
    """Clean HTML tags from response, ensure pure Markdown."""
    import re
    if not text:
        return ""
    # Remove HTML tags but preserve Markdown
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<div[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)  # Remove any remaining HTML tags
    # Clean up multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _truncate_context(text: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """Truncate context to fit token budget."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[Content truncated for length...]"


def _build_context_for_mode(
    mode: str,
    document_text: Optional[str],
    notes_context: Optional[str],
) -> str:
    """Build context string for AI based on mode."""
    if mode == "document" and document_text:
        return _truncate_context(document_text)
    if mode == "notes" and notes_context:
        return _truncate_context(notes_context)
    return ""


async def call_ollama_stream(
    prompt: str,
    system_prompt: Optional[str] = None,
    num_predict: int = 2048,
    model: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """Stream Ollama response. Yields text chunks. Stops yielding if request_id is cancelled."""
    if request_id and is_cancelled(request_id):
        raise GenerationCancelledError("Cancelled")
    model_to_use = model or OLLAMA_MODEL
    payload = {
        "model": model_to_use,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": 0.7,
            "top_p": 0.9,
            "num_predict": num_predict,
        },
    }
    if system_prompt:
        payload["system"] = system_prompt

    timeout = httpx.Timeout(OLLAMA_TIMEOUT, read=OLLAMA_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", _ollama_url(), json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if request_id and is_cancelled(request_id):
                    raise GenerationCancelledError("Cancelled")
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    chunk = data.get("response", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    pass


async def chat_completion(
    user_message: str,
    system_prompt: str,
    context: str,
    history: List[Dict[str, str]],
    request_id: Optional[str] = None,
) -> str:
    """
    Generate chat response with optional document/notes context.
    Returns clean Markdown (no HTML tags).
    history: list of {"role": "user"|"assistant", "content": "..."}
    """
    # Limit history for 8GB RAM
    history = history[-MAX_HISTORY_MESSAGES:]

    # Intent-based instruction: respond like a smart tutor who understands what the student wants
    intent = detect_intent(user_message)
    intent_instruction = _get_intent_instruction(intent)

    # Enhanced system prompt: top-teacher quality + clean readable text
    enhanced_system = (
        RESPONSE_QUALITY_RULES
        + system_prompt
        + intent_instruction
        + "\n\n"
        + RESPONSE_FORMAT_CLEAN
    )

    prompt_parts = []
    if context:
        prompt_parts.append(f"Context (use only this for answers):\n{context}\n\n")
    for h in history:
        role = h.get("role", "")
        content = h.get("content", "")
        if role == "user":
            prompt_parts.append(f"User: {content}\n")
        else:
            prompt_parts.append(f"Assistant: {content}\n")
    prompt_parts.append(f"User: {user_message}\nAssistant:")

    full_prompt = "".join(prompt_parts)
    response = await call_ollama(full_prompt, system_prompt=enhanced_system, request_id=request_id)
    return _clean_markdown(response)


async def chat_completion_stream(
    user_message: str,
    system_prompt: str,
    context: str,
    history: List[Dict[str, str]],
    request_id: Optional[str] = None,
):
    """Stream chat response. Yields raw text chunks (caller can clean with _clean_markdown on full result)."""
    history = history[-MAX_HISTORY_MESSAGES:]
    intent = detect_intent(user_message)
    intent_instruction = _get_intent_instruction(intent)
    enhanced_system = (
        RESPONSE_QUALITY_RULES
        + system_prompt
        + intent_instruction
        + "\n\n"
        + RESPONSE_FORMAT_CLEAN
    )
    prompt_parts = []
    if context:
        prompt_parts.append(f"Context (use only this for answers):\n{context}\n\n")
    for h in history:
        role = h.get("role", "")
        content = h.get("content", "")
        if role == "user":
            prompt_parts.append(f"User: {content}\n")
        else:
            prompt_parts.append(f"Assistant: {content}\n")
    prompt_parts.append(f"User: {user_message}\nAssistant:")
    full_prompt = "".join(prompt_parts)
    async for chunk in call_ollama_stream(full_prompt, system_prompt=enhanced_system, request_id=request_id):
        yield chunk


# --- Tool: Summarize ---
async def generate_summary(text: str, request_id: Optional[str] = None) -> str:
    """Generate structured summary from text. Returns clean Markdown."""
    chunks = chunk_text(text, chunk_size=3000, overlap=200)

    if len(chunks) == 1:
        prompt = f"""Summarize the following academic content into structured bullet points with key concepts and definitions.

Content:
{chunks[0]}

Provide a clear, structured summary using Markdown format:
- Use ## for main sections
- Use - for bullet points
- Use **bold** for key terms
- Do NOT use HTML tags

Format your response as clean Markdown."""
        result = await call_ollama(prompt, request_id=request_id)
        return _clean_markdown(result)

    summaries = []
    for i, chunk in enumerate(chunks):
        if request_id and is_cancelled(request_id):
            raise GenerationCancelledError("Cancelled")
        prompt = f"""Summarize this academic content (part {i+1} of {len(chunks)}) into bullet points using Markdown.

Content:
{chunk}

Provide key points and definitions in Markdown format (use - for bullets, ## for sections)."""
        s = await call_ollama(prompt, request_id=request_id)
        summaries.append(f"## Part {i+1}\n\n{_clean_markdown(s)}")

    if request_id and is_cancelled(request_id):
        raise GenerationCancelledError("Cancelled")
    combined = "\n\n".join(summaries)
    final_prompt = f"""Combine these summary parts into one structured summary with bullet points using Markdown:

{combined}

Provide final, comprehensive summary in clean Markdown format (use ## for sections, - for bullets)."""
    result = await call_ollama(final_prompt, request_id=request_id)
    return _clean_markdown(result)


# --- Tool: MCQs (exam-quality: conceptual, scenario-based, balanced options) ---
MCQ_SYSTEM = """You are an expert exam writer for university, IELTS, and competitive exams.
Create MULTIPLE-CHOICE QUESTIONS that are:
- EXAM-QUALITY: conceptual, scenario-based, and sometimes tricky (no obvious answers).
- OPTIONS: Use keys A, B, C, D. Each option must be a full sentence or phrase, similar in length and plausibility. No giveaways.
- Include a brief explanation for the correct answer.
- Return ONLY valid JSON. No markdown code fences, no extra text."""

def _mcq_json_to_markdown(data: Dict[str, Any], show_answers: bool = True) -> str:
    """Convert MCQ JSON to beautiful Markdown for UI (review mode can show_answers)."""
    questions = data.get("questions") or []
    lines = ["## Multiple Choice Questions\n"]
    for i, q in enumerate(questions, 1):
        qid = q.get("id", f"q{i}")
        question_text = q.get("question", "")
        options = q.get("options") or {}
        if isinstance(options, list):
            options = {chr(65 + j): opt for j, opt in enumerate(options[:4])}
        correct = (q.get("correct_answer") or "").strip().upper()
        explanation = q.get("explanation", "")
        lines.append(f"### Question {i}\n")
        lines.append(f"{question_text}\n")
        for key in ["A", "B", "C", "D"]:
            opt_text = options.get(key, "")
            if not opt_text and isinstance(options, list):
                continue
            if show_answers and key == correct:
                lines.append(f"- **{key}.** {opt_text} ✓ (Correct)\n")
            else:
                lines.append(f"- {key}. {opt_text}\n")
        if show_answers and explanation:
            lines.append(f"\n**Explanation:** {explanation}\n")
        lines.append("\n")
    return "".join(lines)


async def generate_mcq(text: str, request_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate exam-quality MCQs. Returns dict with:
    - "json": strict JSON string for backend (id, question, options A-D, correct_answer, explanation)
    - "markdown": beautiful Markdown for frontend (review mode shows correct answer + explanation)
    """
    chunks = chunk_text(text, chunk_size=5000, overlap=300)
    content = chunks[0]
    if len(chunks) > 1:
        content += "\n\n" + chunks[1][:1500]

    prompt = f"""From the content below, generate 8-10 exam-quality multiple-choice questions.

RULES:
- Mix conceptual, scenario-based, and application questions. Avoid trivial recall.
- Each question must have exactly 4 options labeled A, B, C, D. Options must be balanced in length and plausibility.
- Do NOT make the correct answer obvious (e.g. longest option, "all of the above").
- Include a short explanation for why the correct answer is right.

Content:
{content}

Return ONLY a single JSON object in this EXACT format (no other text, no code fences):
{{
  "questions": [
    {{
      "id": "q1",
      "question": "Full question text here?",
      "options": {{
        "A": "First option text",
        "B": "Second option text",
        "C": "Third option text",
        "D": "Fourth option text"
      }},
      "correct_answer": "A",
      "explanation": "Brief explanation of why A is correct."
    }}
  ]
}}"""

    response = await call_ollama(prompt, system_prompt=MCQ_SYSTEM, num_predict=4096, request_id=request_id)
    json_str = ""
    try:
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            raw = response[json_start:json_end]
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            questions = parsed.get("questions") or []
            # Normalize: ensure options is object A-D, id, explanation
            for i, q in enumerate(questions):
                if not q.get("id"):
                    q["id"] = f"q{i + 1}"
                opts = q.get("options") or {}
                if isinstance(opts, list):
                    q["options"] = {chr(65 + j): str(v) for j, v in enumerate(opts[:4])}
                else:
                    q["options"] = {k: str(v) for k, v in list(opts.items())[:4]}
                q["correct_answer"] = (q.get("correct_answer") or "A").strip().upper()[:1]
                if not q.get("explanation"):
                    q["explanation"] = "See course material."
            json_str = json.dumps({"questions": questions}, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        json_str = json.dumps({
            "questions": [{
                "id": "q1",
                "question": "Could not parse AI response. Please try again.",
                "options": {"A": "", "B": "", "C": "", "D": ""},
                "correct_answer": "A",
                "explanation": "",
            }]
        })

    data = json.loads(json_str) if isinstance(json_str, str) else json_str
    markdown = _mcq_json_to_markdown(data, show_answers=True)
    return {"json": json_str, "markdown": markdown}


# --- Tool: Exam Answer ---
async def generate_exam_answer(text: str, question: str, request_id: Optional[str] = None) -> str:
    """Generate exam-style answer. Returns clean Markdown."""
    chunks = chunk_text(text, chunk_size=3000, overlap=200)
    ql = question.lower()
    relevant = [c for c in chunks if any(w in c.lower() for w in ql.split() if len(w) > 3)]
    content = "\n\n".join(relevant[:2]) if relevant else "\n\n".join(chunks[:2])

    prompt = f"""Write a structured exam-ready answer based on the content using Markdown format.

Question: {question}

Content:
{content}

Provide in Markdown:
## Introduction
Brief overview

## Main Explanation
Detailed explanation

## Conclusion
Summary

Use Markdown formatting (## for headers, - for lists, **bold** for emphasis). Do NOT use HTML tags."""

    result = await call_ollama(prompt, request_id=request_id)
    return _clean_markdown(result)


# --- Tool: Explain Step-by-Step (Topic-based vs Document-based) ---

EXPLAIN_SYSTEM = """You are a top teacher: clear, structured, student-friendly, high quality.
Use this structure for explanations:
1. Simple Explanation (easy language)
2. Step-by-Step Breakdown
3. Real-Life Example
4. Key Points Summary
Use clean readable text: avoid markdown symbols (*, -, **). Use numbered lists (1. 2. 3.) and clear paragraphs. No HTML. Keep it structured but natural; avoid unnecessary long text."""


async def explain_topic_general(topic: str, request_id: Optional[str] = None) -> str:
    """Explain a topic using general knowledge only (no document). Returns clean text."""
    prompt = f"""Topic: {topic}

Explain using this structure:
1. Simple Explanation (easy language)
2. Step-by-Step Breakdown
3. Real-Life Example
4. Key Points Summary
Keep it clear, student-friendly, and avoid unnecessary length."""
    result = await call_ollama(prompt, system_prompt=EXPLAIN_SYSTEM, num_predict=2048, request_id=request_id)
    return _clean_markdown(result)


def _extract_relevant_chunks_for_topic(full_text: str, topic: str, max_chars: int = 6000) -> str:
    """Extract chunks that are relevant to the topic, to avoid sending entire PDF."""
    chunks = chunk_text(full_text, chunk_size=3000, overlap=200)
    tl = topic.lower()
    words = [w for w in tl.split() if len(w) > 2]
    relevant = [c for c in chunks if any(w in c.lower() for w in words)] if words else []
    combined = "\n\n".join(relevant[:3]) if relevant else "\n\n".join(chunks[:2])
    return _truncate_context(combined, max_chars)


async def explain_topic_from_document(topic: str, document_text: str, request_id: Optional[str] = None) -> str:
    """
    Explain the requested topic using the PDF as primary source and general knowledge as backup.
    Do NOT limit the explanation only to the PDF; use general knowledge to enrich and complete it.
    Returns clean text.
    """
    doc_context = _extract_relevant_chunks_for_topic(document_text, topic)

    system_prompt = (
        EXPLAIN_SYSTEM
        + "\n\nPDF rule: Use the document content as your PRIMARY source. "
        "Use general knowledge as BACKUP to enrich and complete the explanation. "
        "Do NOT limit the explanation only to the PDF; add clarity, examples, and context from general knowledge where helpful."
    )
    prompt = f"""Topic: {topic}

Document content (primary source; explain the topic above; add general knowledge to enrich and complete):
---
{doc_context}
---

Explain using: 1. Simple Explanation, 2. Step-by-Step Breakdown, 3. Real-Life Example, 4. Key Points Summary. Use the document first, then general knowledge to make the explanation full and clear."""
    result = await call_ollama(prompt, system_prompt=system_prompt, num_predict=2048, request_id=request_id)
    return _clean_markdown(result)


async def explain_topic(topic: str, document_context: Optional[str] = None, request_id: Optional[str] = None) -> str:
    """
    Smart explain: topic-based (general knowledge) or document-based.
    - If document_context is None or empty: use general AI explanation.
    - If document_context is provided: explain only the topic using document as primary source.
    """
    if document_context and document_context.strip():
        return await explain_topic_from_document(topic, document_context, request_id=request_id)
    return await explain_topic_general(topic, request_id=request_id)


async def chat_completion_with_citations(
    user_message: str,
    system_prompt: str,
    context: str,
    history: List[Dict[str, str]],
    page_texts: Optional[Dict[int, str]] = None,
    request_id: Optional[str] = None,
) -> str:
    """
    Generate chat response with page citations when using PDFs.
    Returns Markdown with 📄 Source: Page X citations.
    """
    history = history[-MAX_HISTORY_MESSAGES:]
    intent = detect_intent(user_message)
    intent_instruction = _get_intent_instruction(intent)
    enhanced_system = (
        RESPONSE_QUALITY_RULES
        + system_prompt
        + intent_instruction
        + "\n\n"
        + RESPONSE_FORMAT_CLEAN
    )
    if page_texts:
        enhanced_system += (
            "\nWhen referencing information from the document, include citations like:\n"
            "📄 Source: Page X\n"
            "or\n"
            "📄 Sources: Pages X, Y, Z\n"
            "at the end of relevant paragraphs or sections.\n"
        )
    
    prompt_parts = []
    if context:
        prompt_parts.append(f"Context (use only this for answers):\n{context}\n\n")
    for h in history:
        role = h.get("role", "")
        content = h.get("content", "")
        if role == "user":
            prompt_parts.append(f"User: {content}\n")
        else:
            prompt_parts.append(f"Assistant: {content}\n")
    prompt_parts.append(f"User: {user_message}\nAssistant:")
    
    full_prompt = "".join(prompt_parts)
    response = await call_ollama(full_prompt, system_prompt=enhanced_system, request_id=request_id)
    
    # Add page citations if page_texts available
    if page_texts:
        # Find relevant pages for the user message
        relevant_pages = find_page_for_text(user_message, page_texts)
        if relevant_pages:
            # Add citation at the end if not already present
            if "📄" not in response:
                pages_str = ", ".join(map(str, relevant_pages))
                response += f"\n\n📄 Source: Page{'s' if len(relevant_pages) > 1 else ''} {pages_str}"
    
    return _clean_markdown(response)


async def generate_study_plan(
    topic: str,
    plan_type: str = "weekly",
    document_text: Optional[str] = None,
    duration_days: int = 7,
    request_id: Optional[str] = None,
) -> str:
    """
    Generate a structured study plan in Markdown format.
    plan_type: "daily", "weekly", or "monthly"
    """
    duration_map = {
        "daily": 1,
        "weekly": 7,
        "monthly": 30,
    }
    days = duration_map.get(plan_type, duration_days)
    
    context_part = ""
    if document_text:
        context_part = f"\n\nUse this content as reference:\n{document_text[:5000]}"
    
    prompt = f"""Create a comprehensive {plan_type} study plan for the following topic. Format your response in clean Markdown.

Topic: {topic}
Duration: {days} days
Plan Type: {plan_type}{context_part}

Provide a structured study plan with:
## Overview
Brief introduction to the topic and learning objectives

## Study Schedule
Break down into {days} days with:
- Day 1: [Topic/Chapter] - [Learning objectives]
- Day 2: [Topic/Chapter] - [Learning objectives]
- etc.

## Daily Tasks
For each day, include:
- Reading materials
- Practice exercises
- Key concepts to master
- Review questions

## Resources
- Recommended readings
- Practice problems
- Additional materials

## Assessment
- Self-assessment questions
- Progress checkpoints
- Final review

Use Markdown formatting:
- ## for main sections
- ### for subsections
- - for bullet points
- 1. 2. 3. for numbered lists
- **bold** for emphasis

Do NOT use HTML tags."""
    
    result = await call_ollama(prompt, num_predict=4096, request_id=request_id)
    return _clean_markdown(result)


async def generate_study_plan_stream(
    topic: str,
    plan_type: str = "weekly",
    document_text: Optional[str] = None,
    duration_days: int = 7,
    request_id: Optional[str] = None,
):
    """Stream study plan content. Yields Markdown chunks."""
    context_part = ""
    if document_text:
        context_part = f"\n\nUse this content as reference:\n{document_text[:5000]}"
    prompt = f"""Create a comprehensive {plan_type} study plan for the following topic. Format your response in clean Markdown.

Topic: {topic}
Duration: {duration_days} days
Plan Type: {plan_type}{context_part}

Provide a structured study plan with:
## Overview
## Study Schedule
## Daily Tasks
## Resources
## Assessment

Use ## for sections, - for bullets, **bold** for emphasis. Do NOT use HTML tags."""
    async for chunk in call_ollama_stream(prompt, num_predict=4096, request_id=request_id):
        yield chunk


async def generate_exam_questions(
    text: str,
    num_questions: int = 10,
    question_type: str = "mcq",  # "mcq", "short_answer", "mixed"
    request_id: Optional[str] = None,
) -> str:
    """
    Generate exam questions from text. Returns JSON string.
    """
    chunks = chunk_text(text, chunk_size=4000, overlap=300)
    content = chunks[0]
    if len(chunks) > 1:
        content += "\n\n" + chunks[1][:1000]
    
    q_type_desc = {
        "mcq": "multiple-choice questions with 4 options each",
        "short_answer": "short answer questions",
        "mixed": "a mix of multiple-choice and short answer questions",
    }.get(question_type, "multiple-choice questions")
    
    prompt = f"""Generate {num_questions} {q_type_desc} from the following content. Return ONLY valid JSON.

Content:
{content}

Return JSON in this exact format:
{{
  "questions": [
    {{
      "id": 1,
      "type": "mcq",
      "question": "Question text",
      "options": ["A", "B", "C", "D"],
      "correct_answer": "A",
      "explanation": "Why this is correct"
    }},
    {{
      "id": 2,
      "type": "short_answer",
      "question": "Question text",
      "correct_answer": "Expected answer",
      "explanation": "Key points"
    }}
  ]
}}

For MCQs, provide exactly 4 options. For short answers, provide a sample correct answer."""
    
    response = await call_ollama(prompt, num_predict=2048, request_id=request_id)
    
    # Extract JSON from response
    try:
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            json_str = response[json_start:json_end]
            json.loads(json_str)  # Validate
            return json_str
    except json.JSONDecodeError:
        pass
    
    # Fallback: return basic structure
    return json.dumps({
        "questions": [{
            "id": 1,
            "type": "mcq",
            "question": "Could not parse AI response. Please try again.",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "",
            "explanation": ""
        }]
    })


# --- Legacy: ask_question (for document Q&A) ---
async def ask_question(text: str, question: str, request_id: Optional[str] = None) -> str:
    """Answer using only document content."""
    chunks = chunk_text(text, chunk_size=3000, overlap=200)
    qw = [w for w in question.lower().split() if len(w) > 3]
    scored = [(sum(1 for w in qw if w in c.lower()), c) for c in chunks]
    scored.sort(reverse=True, key=lambda x: x[0])
    selected = [c for _, c in scored[:2]] if scored else chunks[:1]
    content = "\n\n".join(selected)

    prompt = f"""Answer using ONLY the document content. If not in the document, say: "The answer is not available in the provided document."

Question: {question}

Document:
{content}

Answer:"""

    return await call_ollama(prompt, request_id=request_id)
