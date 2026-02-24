"""
AI Study Assistant - ChatGPT-style FastAPI Application
"""
import os
import re
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Set, Any
from datetime import datetime, timezone

from backend.cancel_store import (
    create_request_id,
    register as cancel_register,
    cancel as cancel_request,
    remove as cancel_remove,
    GenerationCancelledError,
)

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Request,
    Form,
    Body,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    JSONResponse,
    StreamingResponse,
    PlainTextResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from backend.database import get_db, get_db_session, engine, Base
from sqlalchemy import text
from backend.models import (
    User, Document, Conversation, Message, ChatMode,
    StudyPlan, UserTopicStats,
    StudyGroup, GroupMembership, GroupMessage, GroupDocument, GroupInvite,
)
from backend.auth import (
    get_current_user,
    get_current_user_optional,
    authenticate_user,
    create_access_token,
    get_password_hash,
    verify_google_token,
    get_or_create_user_google,
    decode_access_token,
)
from backend.pdf_service import extract_text_from_pdf, extract_text_with_pages, extract_text_from_image_bytes
from backend.ai_service import (
    chat_completion,
    chat_completion_with_citations,
    chat_completion_stream,
    generate_summary,
    generate_mcq,
    explain_topic,
    generate_study_plan,
    generate_study_plan_stream,
)
from backend.chat_service import (
    create_conversation,
    get_conversation_for_user,
    get_user_conversations,
    add_message,
    get_messages,
    get_context_for_ai,
    get_document_text_for_user,
    get_system_prompt,
    sanitize_user_input,
)
from backend.study_service import (
    create_study_plan,
    get_user_study_plans,
    build_revision_plan,
    generate_practice_questions,
)
from backend.analytics_service import update_topic_stats, get_weak_topics
from backend.schemas import (
    AnalyticsUpdateRequest,
    StudyPlanRequest,
    PracticeGenerateRequest,
)
from backend.exam_service import (
    predict_from_document_text,
    build_formatted_output_html,
    build_formatted_output,
    PREDICTED_QUESTIONS_PREFIX,
    INSUFFICIENT_DATA_MESSAGE,
)
from backend.group_service import (
    create_group,
    get_user_groups,
    get_group,
    join_group,
    get_members,
    get_messages as get_group_messages,
    get_recent_messages_for_context,
    add_message as add_group_message,
    get_context_for_group_ai,
    get_group_document_by_id,
    get_group_files,
    is_member,
    get_user_role,
    get_group_documents_text,
    pin_message as group_pin_message,
    unpin_message as group_unpin_message,
    get_pinned_message,
    vote_message as group_vote_message,
    get_message_vote_count,
    get_message_vote_counts_batch,
    get_usernames_by_ids,
    get_group_insights,
    user_can_pin,
    clear_group_messages,
    create_invite,
    get_invite_by_token,
    use_invite,
    set_message_delivered,
    leave_group,
    delete_group,
)

load_dotenv()


Base.metadata.create_all(bind=engine)


def _migrate_group_messages_if_needed():
    """Ensure group_messages has required columns (MySQL). Run once at startup."""
    database_url = os.getenv("DATABASE_URL", "")
    if "mysql" not in database_url:
        return
    try:
        with engine.connect() as conn:
            r = conn.execute(text("SHOW COLUMNS FROM group_messages LIKE 'sender_type'"))
            if r.fetchone():
                return
    except Exception:
        return
    try:
        with engine.begin() as conn:
            for col, defn in [
                ("sender_type", "VARCHAR(20) NOT NULL DEFAULT 'user'"),
                ("message_type", "VARCHAR(20) NOT NULL DEFAULT 'text'"),
                ("file_path", "VARCHAR(500) NULL"),
                ("file_name", "VARCHAR(255) NULL"),
                ("message_status", "VARCHAR(20) NOT NULL DEFAULT 'sent'"),
                ("group_file_id", "INT NULL"),
            ]:
                try:
                    conn.execute(text("ALTER TABLE group_messages ADD COLUMN {} {}".format(col, defn)))
                except Exception:
                    pass
            conn.execute(text(
                "UPDATE group_messages SET sender_type = 'ai', message_type = 'ai' "
                "WHERE user_id IS NULL"
            ))
    except Exception:
        pass


_migrate_group_messages_if_needed()

app = FastAPI(title="AI Study Assistant")

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
UPLOAD_GROUPS_DIR = UPLOAD_DIR / "groups"
UPLOAD_GROUPS_DIR.mkdir(exist_ok=True)
DOCUMENT_TEXT_DIR = BASE_DIR / "document_text"
DOCUMENT_TEXT_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def validate_file_upload(file: UploadFile) -> None:
    """Validate file type: PDF or image (png, jpg, jpeg)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and images (PNG, JPG) allowed")
    ct = (file.content_type or "").lower()
    if ct and "pdf" not in ct and "image" not in ct and "octet-stream" not in ct:
        raise HTTPException(status_code=400, detail="Invalid file type")


def get_document_for_user(db: Session, doc_id: int, user_id: int) -> Document:
    doc = db.query(Document).filter(Document.id == doc_id, Document.user_id == user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401 and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/", status_code=302)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Surface 500 errors for debugging."""
    import traceback
    tb = traceback.format_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "traceback": tb},
    )


# ==================== Landing & Auth Routes ====================

@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Landing page for guests; redirect logged-in users to chat."""
    if current_user:
        return RedirectResponse(url="/chat", status_code=302)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/auth/login", response_class=HTMLResponse)
async def login_page(request: Request):
    from backend.auth import GOOGLE_CLIENT_ID
    next_url = request.query_params.get("next", "")
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "google_client_id": GOOGLE_CLIENT_ID or "", "next_url": next_url},
    )


@app.post("/auth/login")
async def login(
    request: Request,
    identifier: str = Form(...),
    password: str = Form(...),
    next_url: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, identifier, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password"},
        )
    token = create_access_token(data={"sub": str(user.id)})
    redirect_to = (next_url or request.query_params.get("next") or "/chat").strip()
    if not redirect_to.startswith("/"):
        redirect_to = "/chat"
    response = RedirectResponse(url=redirect_to, status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=30 * 60,
        samesite="lax",
    )
    return response


@app.get("/auth/register", response_class=HTMLResponse)
async def register_page(request: Request):
    from backend.auth import GOOGLE_CLIENT_ID
    return templates.TemplateResponse("register.html", {"request": request, "google_client_id": GOOGLE_CLIENT_ID or ""})


@app.post("/auth/register")
async def register(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    # Basic validation
    if password != confirm_password:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Passwords do not match"},
        )
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Email already registered"},
        )
    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Username already taken"},
        )
    user = User(
        email=email,
        username=username,
        hashed_password=get_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(data={"sub": str(user.id)})
    response = RedirectResponse(url="/chat", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=30 * 60,
        samesite="lax",
    )
    return response


@app.get("/auth/logout")
async def logout():
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@app.post("/auth/google")
async def auth_google(
    credential: str = Form(...),
    db: Session = Depends(get_db),
):
    """Exchange Google ID token for session. Form: credential=<id_token>."""
    email, name = verify_google_token(credential)
    user = get_or_create_user_google(db, email, name)
    token = create_access_token(data={"sub": str(user.id)})
    response = RedirectResponse(url="/chat", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=30 * 60,
        samesite="lax",
    )
    return response


# ==================== Chat Page (ChatGPT-style) ====================

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(
    request: Request,
    conv_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversations = get_user_conversations(db, current_user.id)
    documents = db.query(Document).filter(Document.user_id == current_user.id).order_by(Document.created_at.desc()).all()

    current_conv = None
    messages = []
    if conv_id:
        current_conv = get_conversation_for_user(db, conv_id, current_user.id)
        if current_conv:
            messages = get_messages(db, current_conv.id)

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "user": current_user,
            "conversations": conversations,
            "documents": documents,
            "current_conversation": current_conv,
            "messages": messages,
            "MAX_UPLOAD_SIZE_MB": MAX_UPLOAD_SIZE_MB,
        },
    )


# ==================== AI Cancellation ====================

CANCELLED_MESSAGE = "Response stopped by user"


@app.post("/ai/cancel/{request_id}")
async def ai_cancel(request_id: str):
    """Mark an in-flight AI generation as cancelled. Safe to call multiple times or for unknown id."""
    cancelled = cancel_request(request_id)
    return {"success": True, "cancelled": cancelled}


# ==================== API: Chat ====================

@app.get("/chat/new", response_class=RedirectResponse)
def chat_new_redirect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new conversation and redirect to chat. Used when user clicks 'AI Study Assistant' in navbar."""
    conv = create_conversation(db, current_user, title="New Chat", mode="free")
    return RedirectResponse(url=f"/chat?conv_id={conv.id}", status_code=302)


@app.post("/chat/new")
async def chat_new(
    request: Request,
    title: str = Form("New Chat"),
    mode: str = Form("free"),
    document_id: Optional[int] = Form(None),
    notes_context: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if mode not in ("free", "document", "notes"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    if mode == "document" and not document_id:
        raise HTTPException(status_code=400, detail="Document required for document mode")
    if mode == "document" and document_id:
        get_document_for_user(db, document_id, current_user.id)
    if mode == "notes" and not notes_context:
        notes_context = ""

    conv = create_conversation(
        db, current_user, title=title, mode=mode,
        document_id=document_id, notes_context=notes_context,
    )
    if request.headers.get("accept", "").startswith("application/json"):
        return {"success": True, "conversation_id": conv.id}
    return RedirectResponse(url=f"/chat?conv_id={conv.id}", status_code=302)


@app.get("/chat/{conversation_id}", response_class=HTMLResponse)
async def chat_conversation(
    request: Request,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = get_conversation_for_user(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return RedirectResponse(url=f"/chat?conv_id={conversation_id}", status_code=302)


@app.post("/chat/{conversation_id}/delete")
async def delete_conversation(
    request: Request,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = get_conversation_for_user(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Explicitly delete messages first for FK safety, then the conversation
    db.query(Message).filter(Message.conversation_id == conv.id).delete()
    db.delete(conv)
    db.commit()
    if request.headers.get("accept", "").startswith("application/json"):
        return {"success": True}
    return RedirectResponse(url="/chat", status_code=302)


@app.post("/chat/{conversation_id}/clear")
async def clear_conversation_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete all messages in this conversation for the current user. Conversation stays; chat starts fresh."""
    conv = get_conversation_for_user(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    deleted = db.query(Message).filter(Message.conversation_id == conv.id).delete()
    db.commit()
    return {"success": True, "deleted": deleted}


def _html_to_plain_text(html: str) -> str:
    """Strip HTML tags and decode entities for plain text export."""
    if not html:
        return ""
    # Remove predicted-questions comment
    if PREDICTED_QUESTIONS_PREFIX in html:
        html = html.split(PREDICTED_QUESTIONS_PREFIX, 1)[-1].strip()
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p>|</div>|</li>|</h[1-6]>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@app.get("/chat/{conversation_id}/export")
async def export_conversation(
    conversation_id: int,
    format: str = "html",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Export conversation as TXT, HTML, or PDF.
    Preserves styling for predicted-questions and chat content.
    """
    conv = get_conversation_for_user(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = get_messages(db, conv.id)
    export_format = (format or "html").lower().strip()
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if export_format == "txt":
        lines = [
            conv.title or "Chat",
            "Exported: " + timestamp,
            "",
            "---",
            "",
        ]
        for m in messages:
            role = "You" if m.role == "user" else "Assistant"
            lines.append(f"{role}:")
            lines.append(_html_to_plain_text(m.content))
            lines.append("")
        body = "\n".join(lines)
        safe_title = re.sub(r'[^\w\-.]', "-", (conv.title or "export")[:60]).strip("-") or "export"
        return PlainTextResponse(
            body,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="chat-{conversation_id}-{safe_title}.txt"'
            },
        )

    if export_format == "html":
        # Build full HTML document with embedded CSS for download-friendly view
        html_parts = [
            """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>"""
            + (conv.title or "Chat").replace("<", "&lt;").replace(">", "&gt;")
            + """</title>
<style>
body { font-family: system-ui, sans-serif; margin: 20px; background: #f8f9fa; color: #212529; }
.export-header { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #dee2e6; }
.export-title { font-size: 1.5rem; font-weight: 600; margin: 0 0 8px 0; }
.export-meta { font-size: 0.875rem; color: #6c757d; }
.message-block { margin-bottom: 24px; }
.message-role { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; color: #667eea; margin-bottom: 6px; }
.message-body { padding: 12px 16px; border-radius: 12px; background: #fff; border: 1px solid #dee2e6; line-height: 1.6; }
.predicted-questions-block { max-width: 100%; }
.pq-header { margin-bottom: 16px; }
.pq-title { font-size: 1.25rem; margin: 0 0 8px 0; }
.pq-subject, .pq-meta { font-size: 0.9rem; color: #6c757d; margin: 4px 0; }
.pq-list { margin: 16px 0; }
.pq-card { border: 1px solid #dee2e6; border-radius: 10px; padding: 14px; margin-bottom: 12px; background: #fff; }
.pq-question-row { display: flex; gap: 12px; align-items: flex-start; }
.pq-number { font-weight: 700; margin-right: 8px; }
.pq-question-text { margin: 0 0 8px 0; font-weight: 600; }
.pq-meta-row { font-size: 0.85rem; color: #6c757d; margin-bottom: 6px; }
.pq-badge { display: inline-block; padding: 2px 8px; border-radius: 6px; margin-right: 8px; background: #e9ecef; }
.pq-why { font-size: 0.9rem; color: #495057; margin: 8px 0 0 0; }
.pq-section { margin-top: 20px; }
.pq-section-title { font-size: 1.1rem; margin-bottom: 8px; }
.pq-topics-list, .pq-strategy-list { padding-left: 1.25rem; }
</style>
</head>
<body>
<div class="export-header">
<h1 class="export-title">"""
            + (conv.title or "Chat").replace("<", "&lt;").replace(">", "&gt;")
            + """</h1>
<p class="export-meta">Exported: """
            + timestamp
            + """</p>
</div>
"""
        ]
        for m in messages:
            role = "You" if m.role == "user" else "Assistant"
            html_parts.append(f'<div class="message-block"><div class="message-role">{role}</div>')
            content = m.content or ""
            if content.startswith(PREDICTED_QUESTIONS_PREFIX):
                content = content.split(PREDICTED_QUESTIONS_PREFIX, 1)[-1].strip()
                # Remove checkbox and hint toggle for clean export
                content = re.sub(r'<label class="pq-checkbox-wrap">.*?</label>', "", content, flags=re.DOTALL)
                content = re.sub(r'<button[^>]*class="pq-hint-toggle[^"]*"[^>]*>.*?</button>', "", content, flags=re.DOTALL)
                content = re.sub(r'<p class="pq-hint-text" style="display:none;">', '<p class="pq-hint-text">', content)
            html_parts.append(f'<div class="message-body">{content}</div></div>')
        html_parts.append("</body></html>")
        body = "\n".join(html_parts)
        return Response(
            content=body,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="chat-{conversation_id}.html"'
            },
        )

    if export_format == "pdf":
        try:
            from weasyprint import HTML as WeasyHTML
            from io import BytesIO
        except ImportError:
            raise HTTPException(
                status_code=501,
                detail="PDF export requires weasyprint. Install with: pip install weasyprint. Or export as HTML and use Print to PDF in your browser.",
            )
        # Build HTML as above (reuse logic)
        html_parts = [
            """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>"""
            + (conv.title or "Chat").replace("<", "&lt;").replace(">", "&gt;")[:80]
            + """</title><style>body{font-family:system-ui,sans-serif;margin:20px;}</style></head><body><h1>"""
            + (conv.title or "Chat").replace("<", "&lt;").replace(">", "&gt;")[:80]
            + """</h1><p>Exported: """
            + timestamp
            + """</p>"""
        ]
        for m in messages:
            role = "You" if m.role == "user" else "Assistant"
            content = m.content or ""
            if content.startswith(PREDICTED_QUESTIONS_PREFIX):
                content = content.split(PREDICTED_QUESTIONS_PREFIX, 1)[-1].strip()
                content = re.sub(r'<input[^>]*class="pq-solved-checkbox[^"]*"[^>]*>', "", content)
                content = re.sub(r'<button[^>]*class="pq-hint-toggle[^"]*"[^>]*>.*?</button>', "", content, flags=re.DOTALL)
                content = re.sub(r'<p class="pq-hint-text" style="display:none;">', '<p class="pq-hint-text">', content)
            html_parts.append(f"<p><strong>{role}:</strong></p><div>{content}</div>")
        html_parts.append("</body></html>")
        doc_html = "\n".join(html_parts)
        buf = BytesIO()
        WeasyHTML(string=doc_html).write_pdf(buf)
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="chat-{conversation_id}.pdf"'
            },
        )

    raise HTTPException(status_code=400, detail="Format must be txt, html, or pdf")


async def _extract_file_context(file: Optional[UploadFile]) -> tuple[str, Optional[dict]]:
    """Extract text from uploaded PDF or image. Returns (full_text, page_texts or None)."""
    if not file or not file.filename:
        return "", None
    validate_file_upload(file)
    ext = Path(file.filename).suffix.lower()
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        file_content = await file.read()
        if len(file_content) / (1024 * 1024) > MAX_UPLOAD_SIZE_MB:
            raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_SIZE_MB} MB)")
        text = extract_text_from_image_bytes(file_content, file.filename or "")
        return text, {1: text}
    # PDF
    text, page_texts = await extract_text_with_pages(file, max_size_mb=MAX_UPLOAD_SIZE_MB)
    return text, page_texts


@app.post("/chat/send")
async def chat_send(
    conversation_id: int = Form(...),
    content: str = Form(...),
    file: Optional[UploadFile] = File(None),
    system_override: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Ensure optional form fields are always initialized to avoid 500s
    system_override = system_override if system_override is not None else ""

    conv = get_conversation_for_user(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    content = sanitize_user_input(content)
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    user_msg = add_message(db, conv.id, "user", content)

    context = get_context_for_ai(db, conv)
    page_texts = None
    if file and file.filename:
        try:
            file_text, file_pages = await _extract_file_context(file)
            if file_text:
                context = (context + "\n\n--- Attached file content ---\n\n" + file_text).strip()
                page_texts = file_pages
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to process file: {str(e)}")

    doc = conv.document
    system_prompt = get_system_prompt(
        conv.mode,
        doc,
        conv.notes_context,
    )
    if system_override and system_override.strip():
        system_prompt = system_override.strip() + "\n\n" + system_prompt
    if context and "--- Attached file content ---" in context:
        file_instruction = (
            "The user has attached a file; its extracted content is included in the context below. "
            "You MUST use this content to answer. Never respond that no document was found if file content is present."
        )
        system_prompt = file_instruction + "\n\n" + system_prompt

    history_raw = get_messages(db, conv.id)
    history = []
    for m in history_raw[:-1]:  # Exclude just-added user message
        history.append({"role": m.role, "content": m.content})

    # Use citations if document mode (or inline file)
    if page_texts is None and conv.mode == ChatMode.DOCUMENT.value and conv.document_id:
        doc = db.query(Document).filter(Document.id == conv.document_id).first()
        if doc and doc.page_data_path and os.path.exists(doc.page_data_path):
            try:
                with open(doc.page_data_path, "r", encoding="utf-8") as f:
                    page_texts = json.load(f)
            except Exception:
                pass

    request_id = create_request_id()
    await cancel_register(request_id, current_user.id)
    try:
        if page_texts:
            response_text = await chat_completion_with_citations(
                user_message=content,
                system_prompt=system_prompt,
                context=context,
                history=history,
                page_texts=page_texts,
                request_id=request_id,
            )
        else:
            response_text = await chat_completion(
                user_message=content,
                system_prompt=system_prompt,
                context=context,
                history=history,
                request_id=request_id,
            )
    except GenerationCancelledError:
        response_text = CANCELLED_MESSAGE
    finally:
        cancel_remove(request_id)

    assistant_msg = add_message(db, conv.id, "assistant", response_text)

    return {
        "success": True,
        "content": response_text,
        "request_id": request_id,
        "chat_id": conv.id,
        "conversation_id": conv.id,
        "user_message_id": user_msg.id,
        "assistant_message_id": assistant_msg.id,
    }


@app.post("/chat/send/stream")
async def chat_send_stream(
    conversation_id: int = Form(...),
    content: str = Form(...),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream AI response as SSE. First event includes request_id for cancellation. Saves full message when done."""
    conv = get_conversation_for_user(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    content = sanitize_user_input(content)
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    user_msg = add_message(db, conv.id, "user", content)
    context = get_context_for_ai(db, conv)
    page_texts = None
    if file and file.filename:
        try:
            file_text, file_pages = await _extract_file_context(file)
            if file_text:
                context = (context + "\n\n--- Attached file content ---\n\n" + file_text).strip()
                page_texts = file_pages
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to process file: {str(e)}")
    system_prompt = get_system_prompt(conv.mode, conv.document, conv.notes_context)
    if context and "--- Attached file content ---" in context:
        system_prompt = (
            "The user has attached a file; its extracted content is included in the context below. "
            "You MUST use this content to answer. Never respond that no document was found if file content is present.\n\n"
            + system_prompt
        )
    history_raw = get_messages(db, conv.id)
    history = [{"role": m.role, "content": m.content} for m in history_raw[:-1]]

    if page_texts is None and conv.mode == ChatMode.DOCUMENT.value and conv.document_id:
        doc = db.query(Document).filter(Document.id == conv.document_id).first()
        if doc and doc.page_data_path and os.path.exists(doc.page_data_path):
            try:
                with open(doc.page_data_path, "r", encoding="utf-8") as f:
                    page_texts = json.load(f)
            except Exception:
                pass

    request_id = create_request_id()
    await cancel_register(request_id, current_user.id)

    async def event_stream():
        from backend.ai_service import _clean_markdown
        full_content = []
        try:
            # First event: send request_id so client can show Stop and call /ai/cancel
            yield f"data: {json.dumps({'request_id': request_id})}\n\n"
            if page_texts:
                response_text = await chat_completion_with_citations(
                    user_message=content,
                    system_prompt=system_prompt,
                    context=context,
                    history=history,
                    page_texts=page_texts,
                    request_id=request_id,
                )
                full_content.append(response_text)
                yield f"data: {json.dumps({'chunk': response_text})}\n\n"
            else:
                async for chunk in chat_completion_stream(
                    user_message=content,
                    system_prompt=system_prompt,
                    context=context,
                    history=history,
                    request_id=request_id,
                ):
                    full_content.append(chunk)
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            final_text = _clean_markdown("".join(full_content))
            assistant_msg = add_message(db, conv.id, "assistant", final_text)
            yield f"data: {json.dumps({'done': True, 'assistant_message_id': assistant_msg.id, 'chat_id': conv.id, 'conversation_id': conv.id, 'user_message_id': user_msg.id})}\n\n"
        except GenerationCancelledError:
            final_text = _clean_markdown("".join(full_content)) if full_content else ""
            if final_text:
                assistant_msg = add_message(db, conv.id, "assistant", final_text + "\n\n" + CANCELLED_MESSAGE)
            else:
                assistant_msg = add_message(db, conv.id, "assistant", CANCELLED_MESSAGE)
            yield f"data: {json.dumps({'chunk': CANCELLED_MESSAGE, 'cancelled': True})}\n\n"
            yield f"data: {json.dumps({'done': True, 'cancelled': True, 'assistant_message_id': assistant_msg.id, 'chat_id': conv.id, 'conversation_id': conv.id, 'user_message_id': user_msg.id})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            cancel_remove(request_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat/message/{message_id}/edit")
async def edit_message(
    message_id: int,
    content: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a user message and regenerate AI response."""
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    conv = get_conversation_for_user(db, msg.conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    if msg.role != "user":
        raise HTTPException(status_code=400, detail="Can only edit user messages")
    
    content = sanitize_user_input(content)
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    # Update user message
    msg.content = content
    db.commit()
    
    # Delete all messages after this one (including AI response)
    messages_after = (
        db.query(Message)
        .filter(
            Message.conversation_id == conv.id,
            Message.created_at > msg.created_at
        )
        .all()
    )
    for m in messages_after:
        db.delete(m)
    db.commit()
    
    request_id = create_request_id()
    await cancel_register(request_id, current_user.id)
    try:
        context = get_context_for_ai(db, conv)
        doc = conv.document
        system_prompt = get_system_prompt(
            conv.mode,
            doc,
            conv.notes_context,
        )
        history_raw = get_messages(db, conv.id)
        history = []
        for m in history_raw[:-1]:
            history.append({"role": m.role, "content": m.content})
        response_text = await chat_completion(
            user_message=content,
            system_prompt=system_prompt,
            context=context,
            history=history,
            request_id=request_id,
        )
    except GenerationCancelledError:
        response_text = CANCELLED_MESSAGE
    finally:
        cancel_remove(request_id)

    assistant_msg = add_message(db, conv.id, "assistant", response_text)

    return {
        "success": True,
        "content": response_text,
        "request_id": request_id,
        "chat_id": conv.id,
        "conversation_id": conv.id,
        "assistant_message_id": assistant_msg.id,
    }


@app.post("/chat/message/{message_id}/regenerate")
async def regenerate_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Regenerate AI response for a user message."""
    user_msg = db.query(Message).filter(Message.id == message_id).first()
    if not user_msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    conv = get_conversation_for_user(db, user_msg.conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    if user_msg.role != "user":
        raise HTTPException(status_code=400, detail="Can only regenerate responses to user messages")
    
    # Find and delete the AI response after this message
    ai_response = (
        db.query(Message)
        .filter(
            Message.conversation_id == conv.id,
            Message.role == "assistant",
            Message.created_at > user_msg.created_at
        )
        .order_by(Message.created_at.asc())
        .first()
    )
    
    if ai_response:
        db.delete(ai_response)
        db.commit()
    
    request_id = create_request_id()
    await cancel_register(request_id, current_user.id)
    try:
        context = get_context_for_ai(db, conv)
        doc = conv.document
        system_prompt = get_system_prompt(
            conv.mode,
            doc,
            conv.notes_context,
        )
        history_raw = get_messages(db, conv.id)
        history = []
        for m in history_raw:
            if m.id == user_msg.id:
                break
            history.append({"role": m.role, "content": m.content})
        response_text = await chat_completion(
            user_message=user_msg.content,
            system_prompt=system_prompt,
            context=context,
            history=history,
            request_id=request_id,
        )
    except GenerationCancelledError:
        response_text = CANCELLED_MESSAGE
    finally:
        cancel_remove(request_id)

    assistant_msg = add_message(db, conv.id, "assistant", response_text)

    return {
        "success": True,
        "content": response_text,
        "request_id": request_id,
        "chat_id": conv.id,
        "conversation_id": conv.id,
        "assistant_message_id": assistant_msg.id,
    }


# ==================== API: Tools ====================

@app.post("/chat/tools/summarize")
async def tool_summarize(
    conversation_id: int = Form(...),
    request_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = get_conversation_for_user(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    context = get_context_for_ai(db, conv)
    if not context:
        raise HTTPException(status_code=400, detail="No document or notes to summarize")

    request_id = (request_id or "").strip() or create_request_id()
    await cancel_register(request_id, current_user.id)
    try:
        content = await generate_summary(context, request_id=request_id)
    except GenerationCancelledError:
        content = CANCELLED_MESSAGE
    finally:
        cancel_remove(request_id)
    msg = add_message(db, conv.id, "assistant", content)
    return {"success": True, "content": content, "request_id": request_id, "chat_id": conv.id, "conversation_id": conv.id, "assistant_message_id": msg.id}


@app.post("/chat/tools/mcq")
async def tool_mcq(
    conversation_id: int = Form(...),
    request_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = get_conversation_for_user(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    context = get_context_for_ai(db, conv)
    if not context:
        raise HTTPException(status_code=400, detail="No document or notes for MCQs")

    request_id = (request_id or "").strip() or create_request_id()
    await cancel_register(request_id, current_user.id)
    try:
        content_result = await generate_mcq(context, request_id=request_id)
    except GenerationCancelledError:
        content_to_store = CANCELLED_MESSAGE
        content_json = None
        msg = add_message(db, conv.id, "assistant", content_to_store)
        return {"success": True, "content": content_to_store, "content_json": content_json, "request_id": request_id, "chat_id": conv.id, "conversation_id": conv.id, "assistant_message_id": msg.id}
    finally:
        cancel_remove(request_id)
    if isinstance(content_result, dict):
        content_to_store = content_result.get("markdown") or content_result.get("json") or ""
        content_json = content_result.get("json")
    else:
        content_to_store = str(content_result)
        content_json = content_result if isinstance(content_result, str) and content_result.strip().startswith("{") else None
    if isinstance(content_to_store, dict):
        content_to_store = json.dumps(content_to_store)
    msg = add_message(db, conv.id, "assistant", content_to_store)
    return {"success": True, "content": content_to_store, "content_json": content_json, "request_id": request_id, "chat_id": conv.id, "conversation_id": conv.id, "assistant_message_id": msg.id}


@app.post("/chat/tools/explain")
async def tool_explain(
    conversation_id: int = Form(...),
    topic: str = Form(...),
    document_id: Optional[int] = Form(None),
    request_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    topic = sanitize_user_input(topic or "", 500).strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required. Please enter a topic to explain.")

    conv = get_conversation_for_user(db, conversation_id, current_user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    document_context: Optional[str] = None
    if document_id is not None:
        doc_text = get_document_text_for_user(db, document_id, current_user.id)
        if not doc_text or not doc_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Selected document has no content or could not be read. Try another file or use topic-only explanation.",
            )
        document_context = doc_text

    request_id = (request_id or "").strip() or create_request_id()
    await cancel_register(request_id, current_user.id)
    try:
        content = await explain_topic(topic, document_context=document_context, request_id=request_id)
    except GenerationCancelledError:
        content = CANCELLED_MESSAGE
    finally:
        cancel_remove(request_id)
    msg = add_message(db, conv.id, "assistant", content)
    return {"success": True, "content": content, "request_id": request_id, "chat_id": conv.id, "conversation_id": conv.id, "assistant_message_id": msg.id}


# ==================== Exam Question Predictor ====================

def _infer_subject_from_filename(filename: Optional[str]) -> str:
    """Infer subject/topic from document filename (e.g. 'Python exam Pdf.pdf' -> 'Python')."""
    if not filename or not filename.strip():
        return "Exam"
    name = Path(filename).stem.strip()
    for sep in (" - ", "_", " "):
        if sep in name:
            name = name.split(sep)[0].strip()
    return name[:80] if name else "Exam"


@app.post("/exam/predict")
async def exam_predict(
    file: Optional[UploadFile] = File(None),
    document_id: Optional[int] = Form(None),
    subject_or_topic: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    AI Exam Intelligence: analyze past year papers (PDF/images) and optional study materials.
    Predicts important topics, repeated questions, likely exam questions (with importance,
    type, probability), most important topics, and revision strategy. Saves results into
    a new session "Predicted Exam Questions - <Subject/Topic>" for revision.
    """
    text_parts = []
    source_filename: Optional[str] = None

    if file and file.filename:
        validate_file_upload(file)
        source_filename = file.filename
        ext = Path(file.filename).suffix.lower()
        if ext in ALLOWED_IMAGE_EXTENSIONS:
            file_content = await file.read()
            if len(file_content) / (1024 * 1024) > MAX_UPLOAD_SIZE_MB:
                raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_SIZE_MB} MB)")
            text = extract_text_from_image_bytes(file_content, file.filename or "")
            text_parts.append(text)
        else:
            try:
                full_text, _ = await extract_text_with_pages(file, max_size_mb=MAX_UPLOAD_SIZE_MB)
                text_parts.append(full_text)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to process PDF: {str(e)}")

    if document_id is not None:
        doc = get_document_for_user(db, document_id, current_user.id)
        if not source_filename:
            source_filename = doc.filename
        if doc.content_path and os.path.exists(doc.content_path):
            try:
                with open(doc.content_path, "r", encoding="utf-8") as f:
                    text_parts.append(f.read())
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Could not read document: {str(e)}")
        else:
            raise HTTPException(status_code=400, detail="Document has no extracted content")

    if not text_parts:
        raise HTTPException(
            status_code=400,
            detail="Provide a past year paper: upload a PDF/image or select a document from My files.",
        )

    combined_text = "\n\n".join(p for p in text_parts if p and p.strip())
    if not combined_text.strip():
        raise HTTPException(
            status_code=400,
            detail="No text could be extracted. Upload a clearer PDF or image of past year questions.",
        )

    subject = (subject_or_topic or "").strip() or _infer_subject_from_filename(source_filename)
    request_id = create_request_id()
    await cancel_register(request_id, current_user.id)
    try:
        result = await predict_from_document_text(combined_text, subject_or_topic=subject, request_id=request_id)
    except GenerationCancelledError:
        cancel_remove(request_id)
        return {
            "message": CANCELLED_MESSAGE,
            "important_topics": [],
            "repeated_questions": [],
            "predicted_questions": [],
            "most_important_topics": [],
            "revision_strategy": [],
            "formatted_output": "",
            "topic_scores": {},
            "request_id": request_id,
        }
    finally:
        cancel_remove(request_id)
    if result.get("message") == INSUFFICIENT_DATA_MESSAGE:
        raise HTTPException(status_code=400, detail=result["message"])
    if result.get("message") and not result.get("important_topics") and not result.get("predicted_questions"):
        raise HTTPException(status_code=400, detail=result["message"])

    # Save to a new session: store HTML for chat display (cards, hints, styling)
    session_title = f"Predicted Exam Questions - {subject}"
    formatted_plain = result.get("formatted_output") or ""
    if formatted_plain:
        conv = create_conversation(db, current_user, title=session_title, mode="free")
        created_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        formatted_html = build_formatted_output_html(
            result, subject_or_topic=subject, created_at=created_at
        )
        add_message(db, conv.id, "assistant", formatted_html)
        result["conversation_id"] = conv.id
        result["session_title"] = session_title
    return result


# ==================== PDF Upload ====================

@app.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    validate_file_upload(file)
    ext = Path(file.filename or "").suffix.lower()
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        file_content = await file.read()
        if len(file_content) / (1024 * 1024) > MAX_UPLOAD_SIZE_MB:
            raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_SIZE_MB} MB)")
        text = extract_text_from_image_bytes(file_content, file.filename or "")
        page_texts = {1: text}
    else:
        text, page_texts = await extract_text_with_pages(file, max_size_mb=MAX_UPLOAD_SIZE_MB)

    # Persist extracted text on disk
    safe_name = (file.filename or "document").replace("/", "_").replace("\\", "_")
    text_path = DOCUMENT_TEXT_DIR / f"user_{current_user.id}_{safe_name}.txt"
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)

    # Save page data as JSON
    import json
    page_data_path = DOCUMENT_TEXT_DIR / f"user_{current_user.id}_{safe_name}_pages.json"
    with open(page_data_path, "w", encoding="utf-8") as f:
        json.dump(page_texts, f, ensure_ascii=False)

    doc = Document(
        user_id=current_user.id,
        filename=file.filename or "document.pdf",
        content_path=str(text_path),
        page_data_path=str(page_data_path),
        total_pages=len(page_texts),
    )
    db.add(doc)
    db.commit()

    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/chat", status_code=302)
    return {"success": True, "document_id": doc.id, "filename": doc.filename, "total_pages": len(page_texts)}


# ==================== Documents list & delete ====================

@app.get("/api/documents")
async def api_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    docs = db.query(Document).filter(Document.user_id == current_user.id).order_by(Document.created_at.desc()).all()
    return [{"id": d.id, "filename": d.filename, "created_at": d.created_at.isoformat(), "total_pages": d.total_pages} for d in docs]


@app.delete("/api/files/{document_id}")
async def api_delete_file(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an uploaded document (PDF/image) and its extracted text files."""
    doc = db.query(Document).filter(Document.id == document_id, Document.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    for path_attr in ("content_path", "page_data_path"):
        path = getattr(doc, path_attr, None)
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
    db.delete(doc)
    db.commit()
    return {"success": True}


# ==================== Collaborative Study Groups ====================

# Active WebSocket connections per group_id -> { id(websocket): (websocket, user_id, username) }
group_connections: Dict[int, Dict[int, tuple]] = {}


def _get_user_from_ws_cookie(websocket: WebSocket, db: Session) -> Optional[User]:
    """Get current user from access_token cookie in WebSocket request."""
    cookie_header = websocket.headers.get("cookie") or ""
    token = None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("access_token="):
            token = part.split("=", 1)[1].strip()
            break
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        return None
    return db.query(User).filter(User.id == user_id).first()


@app.post("/groups/create")
async def groups_create(
    name: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new study group."""
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    group = create_group(db, current_user, name)
    return {"success": True, "group_id": group.id, "name": group.name}


@app.get("/groups")
async def groups_list(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List groups the user is a member of."""
    groups = get_user_groups(db, current_user.id)
    return [
        {
            "id": g.id,
            "name": g.name,
            "created_by": g.created_by,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        }
        for g in groups
    ]


@app.post("/groups/{group_id}/join")
async def groups_join(
    request: Request,
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Join a group (idempotent)."""
    group = get_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    join_group(db, group_id, current_user)
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url=f"/groups/{group_id}", status_code=302)
    return {"success": True, "group_id": group_id}


@app.post("/groups/{group_id}/invite")
async def groups_create_invite(
    request: Request,
    group_id: int,
    expires_days: int = Form(7),
    usage_limit: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a shareable invite link. Only members can create."""
    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a member of this group")
    group = get_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    inv = create_invite(db, group_id, current_user.id, expires_in_days=min(expires_days, 365), usage_limit=usage_limit)
    base_url = os.getenv("BASE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
    invite_url = f"{base_url}/groups/invite/{inv.token}"
    return {
        "success": True,
        "invite_url": invite_url,
        "token": inv.token,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        "usage_limit": inv.usage_limit,
    }


@app.get("/groups/invite/{token}")
async def groups_invite_landing(
    request: Request,
    token: str,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """
    Invite link: if logged in -> join group and redirect to group.
    If not logged in -> redirect to login with next=invite URL so after login we auto-join.
    """
    inv = get_invite_by_token(db, token)
    if not inv:
        raise HTTPException(status_code=404, detail="Invite link invalid or expired")
    group = get_group(db, inv.group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if current_user:
        use_invite(db, inv, current_user)
        return RedirectResponse(url=f"/groups/{inv.group_id}", status_code=302)
    login_url = f"/auth/login?next={request.url.path}"
    return RedirectResponse(url=login_url, status_code=302)


@app.get("/groups/{group_id}/messages")
async def groups_get_messages(
    group_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get messages for a group (lazy load). Only members allowed. Batched queries for usernames and votes."""
    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a member of this group")
    messages = get_group_messages(db, group_id, limit=limit, offset=offset)
    message_ids = [m.id for m in messages]
    user_ids = list({m.user_id for m in messages if m.user_id})
    usernames = get_usernames_by_ids(db, user_ids)
    vote_counts = get_message_vote_counts_batch(db, message_ids)
    out = []
    for m in messages:
        username = "AI" if (getattr(m, "sender_type", None) == "ai" or getattr(m, "message_type", None) == "ai") else (usernames.get(m.user_id) if m.user_id else None)
        if username is None:
            username = "User"
        out.append({
            "id": m.id,
            "group_id": m.group_id,
            "user_id": m.user_id,
            "username": username,
            "sender_type": getattr(m, "sender_type", "user"),
            "message_status": getattr(m, "message_status", "sent"),
            "message": m.message,
            "message_type": getattr(m, "message_type", "text"),
            "file_path": getattr(m, "file_path", None),
            "file_name": getattr(m, "file_name", None),
            "group_file_id": getattr(m, "group_file_id", None),
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "vote_count": vote_counts.get(m.id, 0),
        })
    pinned = get_pinned_message(db, group_id)
    return {"messages": out, "pinned_message_id": pinned.id if pinned else None}


@app.get("/groups/{group_id}/files")
async def groups_list_files(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List shared files (group documents) for the group. Members only."""
    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a member of this group")
    return {"files": get_group_files(db, group_id)}


@app.post("/groups/{group_id}/upload")
async def groups_upload(
    group_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a PDF or image to a group. Only members allowed. Stored under uploads/groups/{group_id}/."""
    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a member of this group")
    validate_file_upload(file)
    ext = Path(file.filename or "").suffix.lower()
    file_content = await file.read()
    if len(file_content) / (1024 * 1024) > MAX_UPLOAD_SIZE_MB:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_SIZE_MB} MB)")
    group_dir = UPLOAD_GROUPS_DIR / str(group_id)
    group_dir.mkdir(exist_ok=True)
    safe_name = (file.filename or "file").replace("/", "_").replace("\\", "_")
    file_path = group_dir / safe_name
    with open(file_path, "wb") as f:
        f.write(file_content)
    relative_path = f"groups/{group_id}/{safe_name}"
    extracted_text = ""
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        extracted_text = extract_text_from_image_bytes(file_content, file.filename or "")
    else:
        try:
            from backend.pdf_service import extract_text_with_pages
            class AsyncFileLike:
                def __init__(self, data: bytes, filename: str):
                    self._data = data
                    self.filename = filename
                async def read(self):
                    return self._data
            file_like = AsyncFileLike(file_content, file.filename or safe_name)
            extracted_text, _ = await extract_text_with_pages(file_like, max_size_mb=MAX_UPLOAD_SIZE_MB)
        except Exception:
            extracted_text = ""
    doc = GroupDocument(
        group_id=group_id,
        file_name=file.filename or safe_name,
        file_path=relative_path,
        extracted_text=extracted_text[:100000] if extracted_text else None,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"success": True, "document_id": doc.id, "file_name": doc.file_name, "file_path": relative_path}


@app.get("/groups/{group_id}/join", response_class=HTMLResponse)
async def group_join_page(
    request: Request,
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Show 'Join this group?' page for non-members."""
    group = get_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if is_member(db, group_id, current_user.id):
        return RedirectResponse(url=f"/groups/{group_id}", status_code=302)
    return templates.TemplateResponse(
        "group_join.html",
        {"request": request, "user": current_user, "group": group},
    )


@app.get("/groups/{group_id}")
async def group_detail(
    request: Request,
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Group detail page (chat UI). Only members allowed; non-members redirected to join page."""
    if not is_member(db, group_id, current_user.id):
        return RedirectResponse(url=f"/groups/{group_id}/join", status_code=302)
    group = get_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    members = get_members(db, group_id)
    pinned = get_pinned_message(db, group_id)
    is_group_admin = user_can_pin(db, group_id, current_user.id)
    return templates.TemplateResponse(
        "group_chat.html",
        {
            "request": request,
            "user": current_user,
            "group": group,
            "members": members,
            "pinned_message": pinned,
            "is_group_admin": is_group_admin,
            "MAX_UPLOAD_SIZE_MB": MAX_UPLOAD_SIZE_MB,
        },
    )


@app.get("/groups/page/list", response_class=HTMLResponse)
async def groups_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Groups list page (sidebar + create). Pass groups with role for Leave/Delete UI."""
    groups = get_user_groups(db, current_user.id)
    groups_with_roles = [
        {"group": g, "role": get_user_role(db, g.id, current_user.id) or "member"}
        for g in groups
    ]
    return templates.TemplateResponse(
        "groups.html",
        {"request": request, "user": current_user, "groups": groups, "groups_with_roles": groups_with_roles},
    )


@app.post("/groups/{group_id}/pin")
async def groups_pin(
    group_id: int,
    message_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a member")
    if not user_can_pin(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Only admins can pin messages")
    try:
        group_pin_message(db, group_id, message_id, current_user.id)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/groups/{group_id}/unpin")
async def groups_unpin(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_member(db, group_id, current_user.id) or not user_can_pin(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not allowed")
    group_unpin_message(db, group_id)
    return {"success": True}


@app.post("/groups/{group_id}/messages/{message_id}/vote")
async def groups_vote(
    group_id: int,
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a member")
    try:
        voted = group_vote_message(db, message_id, current_user.id, group_id)
        count = get_message_vote_count(db, message_id)
        return {"success": True, "voted": voted, "vote_count": count}
    except ValueError:
        raise HTTPException(status_code=404, detail="Message not found")


@app.post("/groups/{group_id}/leave")
async def groups_leave(
    request: Request,
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Leave the group. Any member can leave. Broadcasts member_left to remaining WebSocket clients."""
    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a member of this group")
    leave_group(db, group_id, current_user.id)
    # Notify remaining connected clients
    for _wid, (ws, _uid, _uname) in list((group_connections.get(group_id) or {}).items()):
        try:
            await ws.send_json({
                "type": "member_left",
                "user_id": current_user.id,
                "username": current_user.username,
            })
        except Exception:
            pass
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/groups/page/list", status_code=302)
    return {"success": True}


@app.post("/groups/{group_id}/delete")
async def groups_delete(
    request: Request,
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete the group. Admin only. Closes all WebSocket connections and broadcasts group_deleted."""
    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a member of this group")
    if get_user_role(db, group_id, current_user.id) != "admin":
        raise HTTPException(status_code=403, detail="Only group admins can delete the group")
    group = get_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    # Broadcast group_deleted to all connected clients, then close their connections
    conns = list((group_connections.get(group_id) or {}).items())
    for _wid, (ws, _uid, _uname) in conns:
        try:
            await ws.send_json({"type": "group_deleted", "group_id": group_id})
        except Exception:
            pass
        try:
            await ws.close(code=4000)
        except Exception:
            pass
    group_connections.pop(group_id, None)
    delete_group(db, group_id, current_user.id)
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/groups/page/list", status_code=302)
    return {"success": True}


@app.post("/groups/{group_id}/clear")
async def groups_clear_history(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clear all messages in the group. Admin only. Broadcasts history_cleared to all WebSocket clients."""
    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a member of this group")
    if not user_can_pin(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Only group admins can clear chat history")
    clear_group_messages(db, group_id)
    # Notify all connected WebSocket clients so they clear the UI in real time
    for _wid, (ws, _uid, _uname) in list((group_connections.get(group_id) or {}).items()):
        try:
            await ws.send_json({"type": "history_cleared"})
        except Exception:
            pass
    return {"success": True}


@app.get("/groups/{group_id}/insights")
async def groups_insights(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_member(db, group_id, current_user.id):
        raise HTTPException(status_code=403, detail="Not a member")
    return get_group_insights(db, group_id)


async def _run_group_ai_background(
    group_id: int,
    request_id: str,
    initiator_id: int,
    initiator_username: str,
    ai_query: str,
    group_file_id: Optional[int],
) -> None:
    """
    Run group AI in a background task so the WebSocket is not blocked.
    Uses its own DB session; does not block other users or other @ai requests.
    """
    db = get_db_session()
    try:
        ai_text = await _handle_group_ai(
            db, group_id, ai_query, initiator_username,
            request_id=request_id,
            group_file_id=group_file_id,
        )
        ai_msg = add_group_message(db, group_id, None, ai_text, message_type="ai", sender_type="ai")
        ai_payload = {
            "type": "message",
            "id": ai_msg.id,
            "user_id": None,
            "username": "AI",
            "sender_type": "ai",
            "message_status": "sent",
            "message": ai_msg.message,
            "message_type": "ai",
            "file_path": None,
            "file_name": None,
            "created_at": ai_msg.created_at.isoformat() if ai_msg.created_at else None,
            "vote_count": 0,
        }
        for _wid, (ws2, _u2, _n2) in list((group_connections.get(group_id) or {}).items()):
            try:
                await ws2.send_json(ai_payload)
            except Exception:
                pass
    except GenerationCancelledError:
        new_db = get_db_session()
        try:
            ai_msg = add_group_message(new_db, group_id, None, CANCELLED_MESSAGE, message_type="ai", sender_type="ai")
            ai_payload = {
                "type": "message",
                "id": ai_msg.id,
                "user_id": None,
                "username": "AI",
                "sender_type": "ai",
                "message_status": "sent",
                "message": ai_msg.message,
                "message_type": "ai",
                "file_path": None,
                "file_name": None,
                "created_at": ai_msg.created_at.isoformat() if ai_msg.created_at else None,
                "vote_count": 0,
            }
            for _wid, (ws2, _u2, _n2) in list((group_connections.get(group_id) or {}).items()):
                try:
                    await ws2.send_json(ai_payload)
                except Exception:
                    pass
        finally:
            new_db.close()
    except Exception as e:
        err_db = get_db_session()
        try:
            err_msg = add_group_message(err_db, group_id, None, f"AI error: {str(e)}", message_type="ai", sender_type="ai")
            err_payload = {
                "type": "message",
                "id": err_msg.id,
                "user_id": None,
                "username": "AI",
                "sender_type": "ai",
                "message_status": "sent",
                "message": err_msg.message,
                "message_type": "ai",
                "created_at": err_msg.created_at.isoformat() if err_msg.created_at else None,
                "vote_count": 0,
            }
            for _wid, (ws2, _u2, _n2) in list((group_connections.get(group_id) or {}).items()):
                try:
                    await ws2.send_json(err_payload)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try:
                err_db.close()
            except Exception:
                pass
    finally:
        try:
            db.close()
        except Exception:
            pass
        for _wid, (ws2, _u2, _n2) in list((group_connections.get(group_id) or {}).items()):
            try:
                await ws2.send_json({"type": "ai_finished", "request_id": request_id})
            except Exception:
                pass
        cancel_remove(request_id)


async def _handle_group_ai(
    db: Session,
    group_id: int,
    user_message: str,
    username: str,
    request_id: Optional[str] = None,
    group_file_id: Optional[int] = None,
) -> str:
    """
    Handle @ai in group: intent-based tools (summarize, explain, MCQ, exam prediction, chat).
    Context priority: 1) attached/selected file, 2) other group files, 3) conversation, 4) general.
    AI messages stored with sender_type='ai'. No hallucination in document mode.
    """
    from backend.ai_service import detect_intent, chat_completion, generate_mcq, generate_summary, explain_topic, _clean_markdown
    prompt = user_message.strip()
    if not prompt:
        return "Please ask a question after @ai."
    lower = prompt.lower()
    recent_list = get_recent_messages_for_context(db, group_id, count=10)
    context = get_context_for_group_ai(db, group_id, recent_messages=recent_list, primary_file_id=group_file_id)

    # Summarize
    if "summarize" in lower or "summary" in lower or "summarise" in lower:
        if not context or context.strip() in ("", "No specific context."):
            return "Share or select a document first, then ask to summarize."
        out = await generate_summary(context, request_id=request_id)
        return _clean_markdown(out)

    # MCQ / Quiz
    if "quiz" in lower or "mcq" in lower or "multiple choice" in lower:
        text = context.strip() or "General knowledge."
        result = await generate_mcq(text, request_id=request_id)
        md = result.get("markdown") or result.get("json") or str(result)
        return _clean_markdown(md)

    # Exam prediction
    if ("exam" in lower and ("predict" in lower or "question" in lower)) or "predict questions" in lower:
        if not context or context.strip() in ("", "No specific context."):
            return "Share or select a document first, then ask for exam prediction."
        subject = "the document" if "topic" not in lower else prompt
        result = await predict_from_document_text(context, subject_or_topic=subject, request_id=request_id)
        if isinstance(result, dict):
            if result.get("message") == INSUFFICIENT_DATA_MESSAGE:
                return result.get("message", INSUFFICIENT_DATA_MESSAGE)
            return result.get("formatted_output") or result.get("message") or build_formatted_output(result, subject)
        return str(result)

    # Explain (intent or keyword)
    intent = detect_intent(prompt)
    if intent in ("explain", "step_by_step", "example", "define"):
        if context and context.strip() and context.strip() != "No specific context.":
            out = await explain_topic(prompt, document_context=context, request_id=request_id)
        else:
            out = await explain_topic(prompt, document_context=None, request_id=request_id)
        return _clean_markdown(out)

    # Chat: use context priority; in document mode do not hallucinate
    doc_mode = bool(group_file_id or (context and context.strip() and "No specific context" not in context))
    system_prompt = (
        "You are a helpful study assistant in a group chat. "
        "Answer clearly and concisely. Use the group's shared documents as context when relevant."
    )
    if doc_mode:
        system_prompt += (
            " When using document context, base your answer primarily on it; "
            "if the answer is not in the context, say so and only then use general knowledge."
        )
    history = []
    for m in recent_list[:-1]:
        if getattr(m, "message_type", None) == "ai" or getattr(m, "sender_type", None) == "ai":
            history.append({"role": "assistant", "content": m.message})
        elif m.user_id:
            history.append({"role": "user", "content": m.message})
    response_text = await chat_completion(
        user_message=prompt,
        system_prompt=system_prompt,
        context=context,
        history=history,
        request_id=request_id,
    )
    return response_text


@app.websocket("/ws/groups/{group_id}")
async def websocket_group_chat(websocket: WebSocket, group_id: int):
    """Real-time group chat. Auth via cookie. Broadcast messages, persist, handle @ai."""
    await websocket.accept()
    db = next(get_db())
    user = _get_user_from_ws_cookie(websocket, db)
    if not user:
        await websocket.close(code=4001)
        return
    if not is_member(db, group_id, user.id):
        await websocket.close(code=4003)
        return
    group_connections[group_id] = group_connections.get(group_id) or {}
    group_connections[group_id][id(websocket)] = (websocket, user.id, user.username)

    def _online_list():
        return [{"user_id": uid, "username": uname} for (_, uid, uname) in (group_connections.get(group_id) or {}).values()]

    try:
        await websocket.send_json({"type": "joined", "user_id": user.id, "username": user.username})
        # Broadcast online list to all in group
        for wid, (ws, _, _) in list(group_connections.get(group_id, {}).items()):
            try:
                await ws.send_json({"type": "online", "users": _online_list()})
            except Exception:
                pass
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type") or "message"
            if msg_type == "message":
                content = (data.get("content") or "").strip()
                if not content:
                    continue
                message_type = data.get("message_type") or "text"
                file_path = data.get("file_path")
                file_name = data.get("file_name")
                group_file_id = data.get("group_file_id")
                # Persist (include group_file_id so AI context is stored with the message)
                gm = add_group_message(
                    db, group_id, user.id, content,
                    message_type=message_type,
                    file_path=file_path,
                    file_name=file_name,
                    group_file_id=group_file_id,
                )
                # Broadcast to all in group
                payload = {
                    "type": "message",
                    "id": gm.id,
                    "user_id": user.id,
                    "username": user.username,
                    "sender_type": "user",
                    "message_status": "sent",
                    "message": gm.message,
                    "message_type": gm.message_type,
                    "file_path": gm.file_path,
                    "file_name": gm.file_name,
                    "group_file_id": getattr(gm, "group_file_id", None),
                    "created_at": gm.created_at.isoformat() if gm.created_at else None,
                    "vote_count": 0,
                }
                for wid, (ws, uid, uname) in list(group_connections.get(group_id, {}).items()):
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        pass
                # @ai: run AI in background so WebSocket is not blocked; multiple users can generate at once
                if content.lower().startswith("@ai"):
                    ai_query = content[3:].strip() or content
                    group_request_id = create_request_id()
                    await cancel_register(group_request_id, user.id)
                    # Notify all clients: initiated_by so only that user sees loading/stop
                    for _wid2, (ws2, _u2, _n2) in list((group_connections.get(group_id) or {}).items()):
                        try:
                            await ws2.send_json({
                                "type": "ai_started",
                                "request_id": group_request_id,
                                "initiated_by": user.id,
                                "initiated_username": user.username,
                            })
                        except Exception:
                            pass
                    asyncio.create_task(_run_group_ai_background(
                        group_id, group_request_id, user.id, user.username, ai_query, group_file_id,
                    ))
            elif msg_type == "typing":
                # Broadcast typing indicator to others in group
                for wid, (ws, _, _) in list(group_connections.get(group_id, {}).items()):
                    if wid != id(websocket):
                        try:
                            await ws.send_json({"type": "typing", "user_id": user.id, "username": user.username})
                        except Exception:
                            pass
            elif msg_type == "delivery_ack":
                message_id = data.get("message_id")
                if message_id is not None and set_message_delivered(db, message_id, group_id):
                    for wid, (ws, _, _) in list(group_connections.get(group_id, {}).items()):
                        try:
                            await ws.send_json({"type": "message_status", "message_id": message_id, "status": "delivered"})
                        except Exception:
                            pass
            elif msg_type == "leave":
                break
    except WebSocketDisconnect:
        pass
    finally:
        conns = group_connections.get(group_id, {})
        conns.pop(id(websocket), None)
        for wid, (ws, _, _) in list(group_connections.get(group_id, {}).items()):
            try:
                await ws.send_json({"type": "online", "users": _online_list()})
            except Exception:
                pass
        if not conns:
            group_connections.pop(group_id, None)
        try:
            db.close()
        except Exception:
            pass


# ==================== Study Plans ====================

@app.post("/api/study-plans/create")
async def api_create_study_plan(
    topic: str = Form(...),
    plan_type: str = Form("weekly"),
    document_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new study plan and save it as a new chat (conversation) with title = plan title."""
    try:
        plan = create_study_plan(db, current_user, topic, plan_type, document_id)

        document_text = None
        if document_id:
            doc = db.query(Document).filter(Document.id == document_id, Document.user_id == current_user.id).first()
            if doc and doc.content_path and os.path.exists(doc.content_path):
                with open(doc.content_path, "r", encoding="utf-8") as f:
                    document_text = f.read()

        duration_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(plan_type, 7)
        request_id = create_request_id()
        await cancel_register(request_id, current_user.id)
        try:
            plan_content = await generate_study_plan(topic, plan_type, document_text, duration_days, request_id=request_id)
        except GenerationCancelledError:
            cancel_remove(request_id)
            raise HTTPException(status_code=400, detail=CANCELLED_MESSAGE)
        finally:
            cancel_remove(request_id)

        plan.content = plan_content
        db.commit()

        # Save as new chat: conversation title = study plan title, first message = plan content
        conv = create_conversation(db, current_user, title=plan.title, mode="free")
        add_message(db, conv.id, "assistant", plan_content)

        return {
            "success": True,
            "study_plan_id": plan.id,
            "content": plan_content,
            "title": plan.title,
            "conversation_id": conv.id,
            "chat_id": conv.id,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/study-plans")
async def api_get_study_plans(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's study plans."""
    plans = get_user_study_plans(db, current_user.id)
    return [
        {
            "id": p.id,
            "title": p.title,
            "topic": p.topic,
            "plan_type": p.plan_type,
            "content": p.content,
            "created_at": p.created_at.isoformat(),
        }
        for p in plans
    ]


@app.get("/api/study-plans/{plan_id}")
async def api_get_study_plan(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific study plan."""
    plan = db.query(StudyPlan).filter(StudyPlan.id == plan_id, StudyPlan.user_id == current_user.id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Study plan not found")
    return {
        "id": plan.id,
        "title": plan.title,
        "topic": plan.topic,
        "plan_type": plan.plan_type,
        "content": plan.content,
        "created_at": plan.created_at.isoformat(),
    }


# ==================== Analytics (Weak Topic Detection) ====================

@app.post("/analytics/update", status_code=status.HTTP_200_OK)
async def analytics_update(
    body: AnalyticsUpdateRequest = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a topic attempt (correct/wrong) for weak topic detection."""
    try:
        update_topic_stats(db, current_user.id, body.topic, body.is_correct)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/analytics/weak-topics")
async def analytics_weak_topics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's weak topics with weak_score and level (Weak / Medium / Strong)."""
    items = get_weak_topics(db, current_user.id)
    return items


# ==================== Smart Revision Planner ====================

@app.post("/study/plan", status_code=status.HTTP_200_OK)
async def study_plan_revision(
    body: StudyPlanRequest = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a revision plan from today until exam_date (weak topics first, 2-3 per day)."""
    result = build_revision_plan(db, current_user.id, body.exam_date)
    return result


# ==================== Practice Mode ====================

@app.post("/practice/generate", status_code=status.HTTP_200_OK)
async def practice_generate(
    body: PracticeGenerateRequest = Body(...),
    current_user: User = Depends(get_current_user),
):
    """Generate 3 MCQs and 2 short questions for the given topic and difficulty."""
    request_id = create_request_id()
    await cancel_register(request_id, current_user.id)
    try:
        result = await generate_practice_questions(body.topic, body.difficulty, request_id=request_id)
        result["request_id"] = request_id
        return result
    except GenerationCancelledError:
        raise HTTPException(status_code=400, detail=CANCELLED_MESSAGE)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cancel_remove(request_id)


# ==================== Voice Input/Output ====================

@app.post("/api/voice/transcribe")
async def api_voice_transcribe(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Transcribe audio to text.
    Note: This is a placeholder. For production, integrate with Whisper API or similar.
    For hackathon demo, returns a message suggesting browser Speech Recognition API.
    """
    # In production, you would:
    # 1. Save audio file
    # 2. Call Whisper API or similar service
    # 3. Return transcribed text
    
    # For now, return a helpful message
    return {
        "success": True,
        "message": "Voice transcription is available via browser Speech Recognition API. See frontend implementation.",
        "text": ""  # Would contain transcribed text
    }


@app.post("/api/voice/synthesize")
async def api_voice_synthesize(
    text: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    """
    Convert text to speech.
    Note: This is a placeholder. For production, use TTS service.
    For hackathon demo, returns a message suggesting browser Speech Synthesis API.
    """
    # In production, you would:
    # 1. Call TTS service (e.g., Google TTS, Azure TTS)
    # 2. Generate audio file
    # 3. Return audio URL
    
    # For now, return a helpful message
    return {
        "success": True,
        "message": "Text-to-speech is available via browser Speech Synthesis API. See frontend implementation.",
        "audio_url": None  # Would contain audio file URL
    }
