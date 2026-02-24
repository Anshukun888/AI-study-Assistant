# Enhancements: Group File Upload, AI Performance, Study Plan Cancel

## 1. Group Study File Upload

### Backend
- **Storage**: Extracted text from group uploads is stored under `document_text/group/{group_id}/{filename}.txt` in addition to the `GroupDocument.extracted_text` DB column.
- **Upload**: `POST /groups/{group_id}/upload` unchanged; after saving the document, the backend writes the extracted text to disk under `GROUP_DOCUMENT_TEXT_DIR / str(group_id) / f"{safe_name}.txt"`.
- **Delete**: When a group file is deleted, the corresponding `.txt` file in `document_text/group/{group_id}/` is removed.
- **Validation**: Existing `validate_file_upload()` is used (PDF, DOCX, PNG, JPG, JPEG; max size from `MAX_UPLOAD_SIZE_MB`).

### Frontend
- **Sidebar**: "Upload" button and file input in the Files section; "Use for AI" (robot icon) and delete per file; "Using for AI: …" with Clear.
- **Input area**: Attach button (paperclip) and hidden file input; drag-and-drop on the message input wrapper.
- **Flow**: Selecting/dropping files triggers upload to `POST /groups/{group_id}/upload` with progress chips; on success, file list is refreshed and "Use for AI" is set to the new file; `group_file_id` is sent with the next WebSocket message when set.
- **Limits**: Client-side validation for extension (PDF, DOCX, PNG, JPG, JPEG) and size (from `MAX_UPLOAD_SIZE_MB`); toasts for errors.

---

## 2. AI Generation Performance in Group Chat

### Backend
- **Streaming**: Group AI uses an async generator `_stream_group_ai_response()` that:
  - For **chat** (general @ai): streams chunks via `chat_completion_stream()` and yields `("chunk", chunk)` then `("full", cleaned_text)`.
  - For **summarize / MCQ / explain / exam**: yields a single `("full", text)`.
- **Context**: Limited to last **10 messages** (`get_recent_messages_for_context(..., count=10)`) plus group documents; `GROUP_CONTEXT_CHARS` and `_truncate()` unchanged.
- **Non-blocking**: `_run_group_ai_background()` runs as `asyncio.create_task`; each @ai request gets its own task and DB session so multiple users can trigger AI without blocking each other.
- **WebSocket**: Server sends `ai_chunk` events (`type: "ai_chunk", request_id, chunk`) during streaming, then the final `message` and `ai_finished`.

### Frontend
- **Streaming UI**: On `ai_started`, `groupStreamingRequestId` is set. On `ai_chunk`, a single streaming message bubble is created/updated and markdown is rendered progressively. On final `message` (AI), the streaming bubble is removed and the final message is appended. On `ai_finished`, streaming state is cleared.
- **Stop**: Send button becomes Stop while the current user’s request is in progress; Stop calls `POST /ai/cancel/{request_id}` and shows "Generation stopped".

---

## 3. Study Plan Generation – Stop/Cancel

### Backend (unchanged behavior)
- Study plan stream already supports cancellation via `request_id` and `cancel_request()`; on `GenerationCancelledError`, the plan is deleted and `{"cancelled": true}` is yielded; no partial save.

### Frontend
- **Button**: Study plan loading modal shows **"Stop / Cancel"** (rounded-pill) and calls `POST /ai/cancel/{request_id}` and `AbortController.abort()`.
- **Toasts**: "Study plan generation stopped." is shown when the user stops or when the stream sends `cancelled`.

---

## 4. Frontend/UX Consistency

- **Group upload**: Same allowed types and size limits as single-user; drag-over styling and attachment chips; error toasts.
- **Study plan**: Stop/Cancel in the loading modal for both single-user and group (group reuses `window.createStudyPlan(topic, planType, null)`).
- **Group AI**: Progressive streaming in one bubble; Stop on the send button for the initiator.

---

## 5. Performance & Safety

- **Non-blocking**: Group AI runs in background tasks; WebSocket remains responsive.
- **Context**: Last 10 messages + group documents; long PDFs/many attachments are truncated via `GROUP_CONTEXT_CHARS` and do not block other requests.
- **Validation**: Group uploads use `validate_file_upload()` (type and size); no change to prompt-injection mitigations (context is passed as document text, not raw user HTML).
- **Memory**: Chunked/truncated context and per-request DB sessions keep usage suitable for 8GB RAM.

---

## Files Touched (summary)

| Area | Files |
|------|--------|
| Backend | `backend/main.py` (group upload text storage, streaming generator, `_run_group_ai_background`, group file delete cleanup), `backend/group_service.py` (unchanged; already uses last 10 messages and group docs) |
| Frontend | `templates/group_chat.html` (Files section upload + "Use for AI", input area attach + drag-drop), `static/js/group_chat.js` (upload, drag-drop, `group_file_id`, streaming `ai_chunk` handling), `static/js/study-features.js` (Stop/Cancel label, toast on cancelled) |
| Docs | `docs/ENHANCEMENTS_GROUP_UPLOAD_AND_AI.md` (this file) |

---

## Compatibility

- Ollama local API (e.g. `qwen2.5:3b`) is unchanged; streaming uses existing `chat_completion_stream` and `call_ollama_stream`.
- Bootstrap 5 and existing styles (e.g. `.btn-attach`, `.drag-over`, `.attachment-chip`, rounded buttons, toasts) are reused.
