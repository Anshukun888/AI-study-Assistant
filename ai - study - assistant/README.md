# AI Study Assistant

A ChatGPT-style AI web application for studying, with document upload, multiple chat modes, and AI-powered tools. Built with Python 3.11+, FastAPI, SQLAlchemy, MySQL, JWT authentication, and Ollama (qwen2.5:3b).

The AI behaves like **a smart tutor who understands exactly what the student wants**: it detects user intent from each message and responds accordingly—short definitions when asked “What is…?”, detailed explanations when asked “Explain…”, step-by-step breakdowns when asked for steps, and examples when asked for an example. Modes are not mixed; the tutor does not over-explain when a definition was requested.

## AI Response Intelligence (Intent Detection)

The assistant uses **intent detection** on every user message to tailor the response:

| User says… | AI responds with |
|------------|-------------------|
| **“What is X?”, “Define X”** | **DEFINE MODE**: A short, clear definition only (2–3 lines). No long explanation, no steps or examples. |
| **“Explain X”, “How does X?”, “Why X?”** | **EXPLAIN MODE**: A full explanation with (1) simple explanation, (2) step-by-step breakdown, (3) an example, (4) key points. |
| **“Step by step”, “Walk me through”** | **STEP-BY-STEP MODE**: A structured, numbered list of steps. Clear and sequential. |
| **“Example”, “Give an example”** | **EXAMPLE MODE**: A clear, concrete example with brief context. |

**Strict control**: The AI does **not** mix modes (e.g. it will not give a long explanation when the user asked only for a definition), and it does **not** over-explain when a definition was requested.

Implementation: `detect_intent(user_input)` in `backend/ai_service.py` classifies the message; the result is used to modify the AI system prompt dynamically so the model follows the correct response mode.

## Explain Step-by-Step (Smart Modes)

The **Explain** tool has two modes:

- **Topic-based (default)**  
  Enter a topic (e.g. “Binary Search”). The AI explains using **general knowledge** only: definition, step-by-step explanation, example, and a simple student-friendly summary. No document is required.

- **Document-based**  
  Check “Use uploaded document” and select a PDF. The AI explains **only that topic** using the document as the **primary source**, and uses general knowledge only to fill gaps. It does not explain the entire PDF.

Both modes use a structured tutor prompt (definition → steps → example → beginner-friendly). The API accepts `topic` (required) and optional `document_id`; validation returns 400 if the topic is missing or if a selected document has no content.

## AI Exam Intelligence System

The **Exam Question Predictor** is an AI Exam Intelligence System that analyzes past exam papers (PDF/images/text) and optional study materials to generate high-quality predicted exam questions using pattern recognition.

### Analysis

- **Frequently repeated topics** – Identifies topics that appear across papers with evidence (e.g. “appears in 4 of 5 papers”).
- **Question patterns** – Detects types: Theory (define, explain), Practical (steps, demonstrate), Coding (implement, program), Case Study (scenario-based).
- **Difficulty trends** – Easy (short definitions), medium (explain with examples), hard (implement, design).
- **Examiner preferences** – Detects recurring wording (e.g. “define”, “explain”, “implement”).

### Output (exam-ready, human-readable)

For each predicted question you get:

- **Topic** and **Importance** (1–5 scale, based on frequency)
- **Question Type** – Theory / Practical / Coding / Case Study
- **Probability** – High / Medium / Low
- **Question** – Well-structured, exam-level wording
- **Why this is important** – Short reasoning from repetition/pattern

Additional outputs:

- **Most Important Topics** – Top 5–10 topics ranked by importance.
- **Revision Strategy** – What to study first based on probability and patterns.

Predictions are based only on the provided data; the AI is instructed not to hallucinate. Use **Predict Exam Questions** in chat: choose a document or upload a PDF/image, optionally enter a subject/topic (or leave blank to infer from filename), then click **Analyze**. Results are shown in the modal. All predicted questions are **automatically saved** into a new session titled **“Predicted Exam Questions - &lt;Subject/Topic&gt;”** with rich HTML formatting (cards, spacing, timestamps). Use **Open in Chat** to open that session. In chat: styled cards with checkboxes ("Mark as solved"), optional hints ("Show hint"), and Download (PDF/HTML/TXT). Export any chat: **GET** `/chat/{id}/export?format=txt|html|pdf`.

## Recent fixes & improvements (production-quality)

- **Voice AI (call mode)**  
  - **Stop vs End call (strict logic)**: Say **"Stop"** to stop AI speaking and cancel any in-flight response only — call stays active; you can ask a new question immediately. Say **"End call"**, **"Cut call"**, or **"Hang up"** to close the session.  
  - **Clean TTS**: All markdown/symbols (`*`, `**`, `-`, bullets, `#`, etc.) are stripped or converted to natural speech (e.g. "- Machine Learning" → "Machine learning"). No symbol reading.  
  - **No accidental interrupt**: The AI does **not** stop when you speak; only **"Stop"** stops it. Normal speech or noise is ignored until the AI finishes or you say "Stop".  
  - **New question**: After "Stop" or when the AI finishes, the system accepts a new question immediately (no continuation of the old answer).  
  - **Follow-up**: After the AI finishes, it optionally asks: "Would you like a deeper explanation or a practice question?"  
  - **Volume** and **Mute** in the call modal; **End call** button to close the session.  
- **Mobile**  
  - **No overlap**: Empty state and mode selector use flexbox with spacing; no overlapping floating elements.  
  - Safe-area insets, header padding, and touch-friendly (44px) targets.  
- **Chat input bar (ChatGPT-style, mobile-first)**  
  - **Top row**: [📎 Attach] [🎤 Mic]. **Bottom row**: [ Ask anything... ] (full width) [➤ Send].  
  - Attach: PDF/image. Mic: speech-to-text then submit. Send: submit. Fixed bottom on mobile, 12px rounded input.  
- **UI/UX**  
  - Rounded inputs (12px), send button touch target (44px), cards/modals with border-radius, smooth theme transitions.  
- **Dark / light mode**  
  - Toggle (☀️/🌙), preference in `localStorage`, auto-detect from `prefers-color-scheme`.  
- **Performance**  
  - Voice call script is lazy-loaded when you first open the call modal.
- **Group chat**
  - **No PDF/file upload**: Group study chat does not allow PDF or file uploads (single-user Free Chat still supports document upload). Shared Files in the sidebar is read-only in group chat.
  - **Typing indicator**: "User is typing…" (or the username) appears while another member is composing; it disappears when the message is sent. Styled for mobile and desktop without overlap.
  - **Clean messages**: No username, date, or time on message popup/hover; sender color and AI vs user styling are preserved. Copy code buttons on AI code blocks.
  - **Unread indicators**: Small blue dot next to each group in the groups list (sidebar and mobile cards) when there are new messages; dot clears when the user opens the group or scrolls to bottom/focuses input. In-chat blue dot in the header when there are new messages below the fold.
  - **Mobile**: One "Create / Join Groups" entry (sidebar/hamburger only; duplicate removed from main content). Stop/Cancel for AI is visible and tappable. Fixed bottom input, scrollable messages.
- **Upload Files**
  - UI labels use “Upload Files” (replacing “Upload PDF”). Supported types: PDF, images (PNG, JPG, JPEG), DOCX. Group chat does not support file upload.
- **Study plan**
  - **Stop/Cancel**: In both single-user Free Chat and group study chat, a Stop/Cancel button is visible when a study plan is generating. Backend allows graceful termination per user; frontend shows toast "Study plan generation stopped." Partial or incomplete plans are not saved. User can restart generation if needed.

For detailed mobile and desktop chat behavior (typing indicator, unread dots, clean messages, no PDF in group chat), see [docs/CHAT_UX.md](docs/CHAT_UX.md).

## Features

- **User Authentication**: Register, login, logout with JWT (HTTPOnly cookie) and Passlib/bcrypt
  - Login with **email or username**
  - Register with **email, username, password, confirm password**
  - Password **show/hide toggle** on login and register forms
- **AI Response Intelligence**: Intent detection on every message—definitions stay short (2–3 lines), explanations get steps + example + key points, step-by-step and example requests get the right format. No mixing modes; no over-explaining when a definition was asked.
- **Chat Modes**:
  - **Free Chat**: General AI assistant, no document required
  - **Document Chat**: Chat limited to uploaded PDF content (rejects hallucinations)
  - **Notes Mode**: Paste text and chat using it as context
- **PDF Handling**: Upload PDFs, extract text with PyMuPDF, chunk for processing
- **AI Tools**: Summarize, Generate MCQs, **Explain Step-by-Step** (topic-based or document-based), **AI Exam Intelligence** (analyze past papers; predict important topics, repeated questions, likely exam questions with importance/type/probability; most important topics; revision strategy; auto-save to a session for revision)
- **Attach file in chat**: Send a PDF or image with your message in one request; AI uses extracted text automatically
- **Voice call**: Real-time voice conversation with AI (speak → AI responds with voice + text, interrupt support). Voice output is cleaned for natural speech: markdown (e.g. `*`, `**`, `-`, `#`) is stripped and bullet lists are converted to conversational sentences so the AI sounds like a real human tutor explaining, not reading raw text.
- **Google Sign-In**: Optional “Continue with Google” on login/register (set `GOOGLE_CLIENT_ID` in `.env`)
- **File management**: Delete uploaded files from the sidebar (My files → ✕). A confirmation modal asks: "Are you sure you want to permanently delete this file? This action cannot be undone." with **Cancel** and **Confirm** buttons.
- **Conversation History**: Sidebar with previous chats, resume any conversation
  - Per-chat **three-dots menu** to delete a conversation safely (confirmation modal with Cancel/Confirm)
  - When the AI is generating, a temporary bubble shows **“AI is thinking...”**

- **Clear History (single chat)**: **Clear History** button in chat header deletes all messages in the current conversation (conversation stays). **Clear History (groups)**: Group admins can clear all group messages; all connected members see the chat clear in real time via WebSocket.
- **Favicon**: Favicon on all pages: place `favicon.ico` in `static/` (and optionally `favicon.svg`). Used on `/`, `/chat`, `/groups`, `/auth/*`, and group chat.
- **New chat on app click**: After login, clicking **"AI Study Assistant"** in the navbar opens a new single-user chat (creates a new conversation and redirects to it). Session and WebSocket/SSE remain ready.
- **Group management**:
  - **Leave group**: Any member can leave via "Leave" (group chat header or groups list dropdown). Confirmation modal; database and WebSocket updated; other members see "X left the group".
  - **Delete group**: Only group admins can delete. Confirmation modal before delete. On delete: all group WebSocket connections are closed, `group_deleted` is broadcast, database is updated (group and related data removed). Members are redirected to the groups list when the group is deleted.
- **Free AI chat in study groups**: Full AI features in group chat: text and file attachment, summarize, MCQ generation, step-by-step explain, exam prediction, and general chat. All features work per-user and per-group context. **Multiple members can use AI at once**; each request runs in a background task so the WebSocket is not blocked and other users can keep chatting. The loading/Stop indicator shows only for the user who triggered the request; others see a short "X is generating..." toast. Stop/cancel works via `request_id` and `POST /ai/cancel/{request_id}`. Pin message updates the UI without a full page reload.
- **Alerts and errors**: Consistent toast notifications; failed uploads or AI calls show meaningful messages instead of generic 500 errors.

## Tech Stack

- Python 3.11+
- FastAPI
- SQLAlchemy ORM
- MySQL
- JWT authentication (HTTPOnly cookie)
- Passlib (bcrypt)
- Jinja2 templates
- Bootstrap 5
- Ollama local API (model: qwen2.5:3b)

## Setup

### 1. Prerequisites

- Python 3.11+
- MySQL 8+
- [Ollama](https://ollama.ai) with `qwen2.5:3b` model

```bash
# Install Ollama, then:
ollama pull qwen2.5:3b
```

### 2. Clone and Install

```bash
cd ai-study-assistant
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment

```bash
cp .env.example .env
```

Edit `.env` and set your MySQL credentials. For example, if your root password contains `$`:

```env
DATABASE_URL=mysql+pymysql://root:YourPass$$@localhost:3306/ai_study_assistant
```

> Note: In `.env` you do **not** need to escape `$`; just write the full URL.

Other important envs (already in `.env.example`):

- `SECRET_KEY` – long random string for JWT
- `OLLAMA_BASE`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`
- `MAX_CONTEXT_CHARS`, `MAX_HISTORY_MESSAGES`
- `MAX_UPLOAD_SIZE_MB`
- `GOOGLE_CLIENT_ID` – (optional) Google OAuth 2.0 Client ID for “Continue with Google”. Leave empty to hide the button. Create at [Google Cloud Console](https://console.cloud.google.com/apis/credentials).

### 4. Database (MySQL)

Create the database:

```sql
CREATE DATABASE IF NOT EXISTS ai_study_assistant
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

Then either:

- **Option A – SQLAlchemy (recommended)**  
  Start the app once; `backend/main.py` runs `Base.metadata.create_all(bind=engine)` and creates:
  - `users`
  - `documents`
  - `conversations`
  - `messages`

- **Option B – Manual schema**

  ```bash
  mysql -u root -p ai_study_assistant < schema.sql
  ```

To verify the DB in MySQL Workbench:

```sql
USE ai_study_assistant;
SHOW TABLES;
DESCRIBE users;
DESCRIBE documents;
DESCRIBE conversations;
DESCRIBE messages;
```

You can also run the helper script:

```bash
python verify_db.py
```

It checks that `DATABASE_URL` works and that all four tables exist.

### 5. Run

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000

## API Routes

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Redirect to login |
| GET | `/auth/login` | Login page |
| POST | `/auth/login` | Login |
| GET | `/auth/register` | Register page |
| POST | `/auth/register` | Register |
| GET | `/auth/logout` | Logout |
| GET | `/chat` | Chat page (ChatGPT-style) |
| GET | `/chat/new` | Create new conversation and redirect to chat (e.g. navbar "AI Study Assistant" click) |
| POST | `/chat/new` | Create new conversation (API) |
| GET | `/chat/{id}` | Open conversation |
| POST | `/chat/{conversation_id}/delete` | Delete a conversation and all its messages |
| POST | `/chat/{conversation_id}/clear` | Clear all messages in a conversation (conversation stays; owner only) |
| POST | `/chat/send` | Send message (optional `file` in same request; text-only or text+file) |
| POST | `/chat/send/stream` | Send message with streaming AI response (optional `file`) |
| POST | `/chat/tools/summarize` | Summarize document/notes |
| POST | `/chat/tools/mcq` | Generate MCQs |
| POST | `/chat/tools/explain` | Explain a topic step-by-step. Body: `topic` (required), `document_id` (optional). Two modes: **Topic-based** (general knowledge) or **Document-based** (explain only the topic using the selected PDF). |
| POST | `/exam/predict` | **AI Exam Intelligence.** Body: `file` (optional PDF/image), `document_id` (optional), `subject_or_topic` (optional). Returns 10–15 `predicted_questions` (with topic, importance, question_type, probability, why_important, optional hint), `most_important_topics`, `revision_strategy`, and on success `conversation_id`, `session_title`. Saves results to a new chat session with HTML formatting. |
| GET | `/chat/{conversation_id}/export` | Export conversation as file. Query: `format=txt|html|pdf`. Returns attachment with styling preserved (PDF requires optional weasyprint). |
| POST | `/upload` | Upload PDF or image to “My files” |
| POST | `/auth/google` | Google Sign-In (form: `credential` = ID token) |
| DELETE | `/api/files/{id}` | Delete uploaded document |
| GET | `/groups` | List user’s groups (JSON) |
| GET | `/groups/page/list` | Groups list page |
| GET | `/groups/{id}` | Group chat page |
| POST | `/groups/create` | Create group |
| POST | `/groups/{id}/join` | Join group |
| POST | `/groups/{id}/leave` | Leave group (any member); redirects to groups list if HTML |
| POST | `/groups/{id}/delete` | Delete group (admin only); closes WebSockets, broadcasts `group_deleted` |
| POST | `/groups/{id}/clear` | Clear all group messages (admin only; broadcasts to WebSocket clients) |
| GET | `/groups/{id}/messages` | Get group messages (lazy load) |
| POST | `/groups/{id}/invite` | Create invite link |
| WebSocket | `/ws/groups/{id}` | Real-time group chat (messages, typing, online list, history_cleared, member_left, group_deleted, ai_started with request_id/initiated_by/initiated_username, ai_finished, ai_busy) |

## Project Structure

```
ai-study-assistant/
├── backend/
│   ├── main.py         # FastAPI app, routes, WebSocket group chat
│   ├── database.py     # SQLAlchemy engine, session (MySQL)
│   ├── models.py       # User, Document, Conversation, Message, StudyPlan, StudyGroup, GroupMessage, etc.
│   ├── auth.py         # JWT, Passlib, Google token verification
│   ├── ai_service.py   # Ollama integration
│   ├── pdf_service.py  # PDF/image extraction, chunking
│   ├── chat_service.py # Chat logic, modes
│   ├── group_service.py# Groups: CRUD, leave, delete, messages, pin, vote, clear, invite
│   ├── voice_utils.py  # clean_text_for_voice() for natural TTS (strip markdown, bullets → speech)
│   ├── study_service.py
│   └── exam_service.py # AI Exam Intelligence: extraction, pattern analysis, predicted questions
├── templates/
│   ├── base.html       # Favicon, nav, common scripts
│   ├── index.html      # Landing (logged-out)
│   ├── login.html
│   ├── register.html
│   ├── chat.html       # Single-user chat (Clear History in header)
│   ├── groups.html     # Groups list
│   ├── group_chat.html # Group chat (Clear History for admins)
│   └── group_join.html
├── static/
│   ├── favicon.ico     # App favicon (all pages; add favicon.svg optionally)
│   ├── css/style.css
│   ├── js/chat.js      # Chat UI, clear history, toasts
│   ├── js/group_chat.js# Group WebSocket, clear history, history_cleared handler
│   ├── js/groups.js
│   ├── js/study-features.js
│   └── js/voice-call.js
├── requirements.txt
├── .env.example
├── .env              # Local environment (ignored in VCS)
├── schema.sql        # MySQL schema (optional if using create_all)
├── document_text/    # Extracted text from uploaded PDFs (per user)
├── uploads/          # Uploaded files; uploads/groups/{id}/ for group files
└── README.md
```

## Voice Response (TTS)

Before text is sent to the browser’s speech synthesis (voice call and “Read response” button), it is cleaned so the AI sounds like **a real human tutor explaining naturally**, not like someone reading raw markdown:

- **Markdown/symbols removed**: `*`, `**`, `-`, `#`, `_`, `` ` ``, `~`, `^`, `|` are stripped so the engine never says “star” or “asterisk”.
- **Bullet lists → speech**: Lists like “- Machine Learning\n- NLP” are turned into: “Machine Learning, and NLP.” (or “A, B, and C.” for three or more items).
- **Flow**: Commas and periods are used for natural pauses. A final pass removes any remaining stray symbols.

Backend: `backend/voice_utils.py` exposes `clean_text_for_voice(text: str) -> str`. Frontend: `cleanTextForVoice(text)` in `study-features.js` is applied before every TTS call in the voice call modal and the read-aloud button.

## Security

- File uploads validated (PDF only, size limit)
- Sanitization to reduce prompt injection risk
- System prompts not exposed to client
- CORS configured via env
- JWT in HTTPOnly cookie

## Performance (8GB RAM)

- Chunked context (configurable limit)
- Limited message history
- Token limits for Ollama

### Group chat performance

- **Non-blocking AI**: Group @ai requests run in background asyncio tasks with a dedicated DB session. The WebSocket handler returns immediately so multiple users can generate at the same time and the chat stays responsive.
- **No per-group lock**: No "one AI at a time per group" limit; each request has its own `request_id` and can be cancelled independently.
- **Efficient message load**: `GET /groups/{id}/messages` uses batched queries for usernames and vote counts (no N+1). AI context uses only the last 10 messages and group documents; no full history fetch during generation.
- **UI**: Loading/Stop is shown only to the user who triggered the request; pin updates in-place without reload.
