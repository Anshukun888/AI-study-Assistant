# Real-Time Collaborative Group AI – Implementation Summary

## DB Schema

### New / updated tables

**group_invites**
| Column      | Type         | Description                    |
|------------|--------------|--------------------------------|
| id         | INT PK       |                                |
| group_id   | INT FK       | study_groups.id                |
| token      | VARCHAR(64)  | Unique, indexed                |
| expires_at | DATETIME     | Invite expiry                  |
| usage_limit| INT NULL     | Max uses (null = unlimited)    |
| used_count | INT          | Default 0                      |
| created_at | DATETIME     |                                |

**group_messages** (new columns)
| Column         | Type         | Description                    |
|----------------|--------------|--------------------------------|
| sender_type    | VARCHAR(20)  | `user` \| `ai` (default `user`) |
| message_status| VARCHAR(20)  | `sent` \| `delivered` (default `sent`) |
| group_file_id  | INT NULL FK  | group_documents.id (file used as AI context) |

**group_documents** (existing, used as shared “group files”)
| Column         | Type   |
|----------------|--------|
| id, group_id  |        |
| file_name, file_path |  |
| extracted_text | TEXT  |
| uploaded_by, created_at |  |

For existing databases, run `migrations/add_group_invites_and_message_fields.sql` (and uncomment/run the ALTERs for `group_messages` if needed).

---

## API Routes

### Invite
- **POST /groups/{group_id}/invite**  
  Body: `expires_days` (Form, default 7), `usage_limit` (Form, optional).  
  Returns: `invite_url`, `token`, `expires_at`, `usage_limit`.
- **GET /groups/invite/{token}**  
  If logged in: consume invite, join group, redirect to `/groups/{group_id}`.  
  If not: redirect to `/auth/login?next=/groups/invite/{token}`; after login, user is sent back to this URL and then joined and redirected to the group.

### Group files
- **GET /groups/{group_id}/files**  
  Returns: `{ "files": [ { id, group_id, file_name, file_path, uploaded_by, created_at } ] }`.  
  Members only.

### Group messages (existing, extended)
- **GET /groups/{group_id}/messages**  
  Response items now include `sender_type`, `message_status`.

### Insights (existing, extended)
- **GET /groups/{group_id}/insights**  
  Now also returns `ai_usage_stats: { ai_message_count }`.

### WebSocket /ws/groups/{group_id}
- **Client → server**
  - `{ "type": "message", "content", "message_type?", "file_path?", "file_name?", "group_file_id?" }` – send message; optional `group_file_id` for “use this file in AI”.
  - `{ "type": "typing" }` – broadcast “user is typing” to others.
  - `{ "type": "delivery_ack", "message_id" }` – mark message delivered; server updates DB and broadcasts status.
  - `{ "type": "leave" }` – disconnect.
- **Server → client**
  - `{ "type": "joined", "user_id", "username" }` – you joined.
  - `{ "type": "online", "users": [ { user_id, username } ] }` – current online list (on join and when someone leaves).
  - `{ "type": "message", ... }` – new message (includes `sender_type`, `message_status` where applicable).
  - `{ "type": "typing", "user_id", "username" }` – someone is typing.
  - `{ "type": "message_status", "message_id", "status": "delivered" }` – message marked delivered.

---

## Backend Logic

### Group AI context priority (group_service + main)
1. **Attached/selected file** – `group_file_id` (or primary file) text first.
2. **Other group documents** – remaining group files’ `extracted_text`.
3. **Group conversation** – last N messages.
4. **General knowledge** – when no document context or to enrich.

### _handle_group_ai (main.py)
- Accepts `group_file_id` and passes it to `get_context_for_group_ai(..., primary_file_id=group_file_id)`.
- **Intent-based tools (no mixing):**
  - **Summarize** – “summarize” / “summary” → `generate_summary(context)`.
  - **MCQ/Quiz** – “quiz” / “mcq” → `generate_mcq(context)`.
  - **Exam prediction** – “exam” + “predict” / “predict questions” → `predict_from_document_text(context, ...)`.
  - **Explain** – intent explain/step_by_step/example/define → `explain_topic(prompt, document_context=context or None)`.
  - **Chat** – else `chat_completion(...)` with context; in document mode, system prompt instructs: base answer on context first, say when not in context before using general knowledge (no hallucination in document mode).
- All AI replies are stored with `sender_type="ai"` and `message_type="ai"`.

### Invite flow
- `create_invite()` – secure token, expiry, optional usage limit.
- `get_invite_by_token()` – valid only if not expired and under usage limit.
- `use_invite()` – `join_group()` (idempotent) + increment `used_count`.

### Message status
- New messages stored with `message_status="sent"`.
- On WS `delivery_ack`, `set_message_delivered()` sets `message_status="delivered"` and broadcast `message_status` to the group.

---

## Frontend (group_chat.js + group_chat.html)

- **Members sidebar** – Rendered from template `members`; **online list** from WS `online` events and displayed (e.g. “N online” + names).
- **Files panel** – Fetches `GET /groups/{id}/files`; list with **Upload** (sidebar file input → `POST /groups/{id}/upload`) and **Use** to set “use this file in AI” (sets `selectedGroupFileId`; sent as `group_file_id` with next `@ai` message).
- **AI tools panel** – Buttons: Summarize, Explain, MCQ, Exam; each sets input to the corresponding `@ai ...` prefix.
- **Invite** – Button calls `POST /groups/{id}/invite` and copies `invite_url` to clipboard.
- **Typing** – On input, send WS `typing`; on receive, show “X is typing” (with short timeout).
- **Message status** – On receive of own message, send `delivery_ack`; on receive `message_status`, update UI (e.g. ✓✓ for delivered).
- **Insights** – Modal shows most active users, top topics, and **AI usage** (`ai_message_count`).
- **Selected file for AI** – “Using file: …” and Clear; `group_file_id` included in WS message when set.

---

## Auth and invite

- **Login** – Supports `?next=` and form field `next_url`; after success, redirects to `next` (e.g. `/groups/invite/{token}`) so invite link → login → back to invite → auto-join → redirect to group.
- **Duplicate joins** – `join_group` is idempotent; `use_invite` only increments `used_count` once per use (user can already be member).

---

## Rules (as requested)

- **No hallucination in document mode** – When context comes from file(s), system prompt tells AI to base answers on context first and to state when the answer is not in the context before using general knowledge.
- **Intent and modes** – Summarize, MCQ, exam prediction, explain, and chat are handled by separate branches; modes are not mixed.
- **AI messages** – Always stored with `sender_type="ai"` and `message_type="ai"` in the DB and exposed in API/WS.
