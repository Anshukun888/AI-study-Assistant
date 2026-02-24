# Group Study Chat – Mobile & Desktop UX

This document describes the Group Study Chat behavior and how it aligns with single-user Free Chat, including mobile and desktop differences.

## 1. File Management

### Delete / Remove Files
- **Who can delete:** Only the user who uploaded a file can delete it. The delete icon is shown only for files where `uploaded_by` matches the current user.
- **Desktop:** Each file in the sidebar "Files" section shows a trash icon (when you are the uploader). Click to open the confirmation modal.
- **Mobile:** Same behavior; the trash icon is touch-friendly and the confirmation modal is full-width. Files list is scrollable in the sidebar.
- **Confirmation:** Modal text: "Are you sure you want to delete this file? This action cannot be undone." Cancel or Delete. On confirm, the file is removed from the backend and the list refreshes; a success toast is shown.
- **Backend:** `DELETE /groups/{group_id}/files/{file_id}`. Returns 403 if the current user is not the uploader.

## 2. Message Features

### Timestamps
- **Display:** Every message shows the time it was sent (e.g. "2:30 PM" for today, or date + time for older). Rendered below the message body in a small, muted line (`.message-meta` / `.message-time`).
- **Desktop:** Time is visible; no popup or tooltip for time/username.
- **Mobile:** Timestamps use a slightly smaller font (0.75rem) and remain visible. Messages are scrollable; time and edit controls stay visible.

### Message Editing
- **Who can edit:** Only the author can edit their own messages. AI and file messages cannot be edited.
- **How:** An edit (pencil) button appears on your own text messages (desktop: on hover; mobile: always visible for touch). Click to open the "Edit message" modal, change the text, then Save.
- **After edit:** The message body updates in place. An "(edited)" indicator appears next to the timestamp. Other members see the update in real time via WebSocket `message_updated`.
- **Backend:** `POST /groups/{group_id}/messages/{message_id}/edit` with `content=...`. Returns 404 if the message is not yours or not editable.

### Removed Behavior
- Any previous popup or tooltip that showed username/date/time on message click has been removed. The timestamp is shown inline below the message; the UI stays clean.

## 3. Study Plan Generation – Stop / Cancel

### Where It Applies
- **Single-user Free Chat:** "Study Plan" button opens the study plan modal. On "Create Plan", a loading modal appears with "Generating your study plan..." and a **Stop** button.
- **Group Study Chat:** Same flow. A "Study Plan" button is available in the sidebar under AI Tools. Clicking it opens the same study plan modal (topic + plan type; no document in group). "Create Plan" shows the same loading modal with **Stop**.

### Stop Button Behavior
- **Visibility:** The Stop button is visible as soon as "Generating your study plan..." is shown (no need to wait for the first chunk).
- **Desktop:** Stop is a normal button below the spinner.
- **Mobile:** Stop button is touch-friendly (min height/width 44px, padding, `touch-action: manipulation`).
- **On click:**  
  - If a request ID has been received from the stream, the client calls `POST /ai/cancel/{request_id}` and aborts the fetch.  
  - If the request ID is not yet received, the client aborts the fetch (AbortController).  
  - The loading modal closes, a toast shows "Study plan generation stopped.", and the user can start again.
- **Backend:** Cancellation is per `request_id`; only that user’s generation is stopped. On cancel, partial results are not saved (stream yields `cancelled: true`; any in-memory plan is discarded).

## 4. Mobile / UX Summary

| Feature              | Desktop                    | Mobile                                      |
|----------------------|----------------------------|---------------------------------------------|
| File delete          | Trash icon on hover/click  | Trash icon always visible, tappable        |
| Message time         | Below message, small       | Same, slightly smaller font                 |
| Edit message         | Pencil on hover            | Pencil always visible for your messages    |
| Study plan Stop      | Button below spinner       | Large touch target, same placement          |
| Toasts               | Top-end                    | Full-width friendly, no overlap            |
| Copy code (AI)       | Copy button on code blocks | Same; copy buttons kept in group chat       |

### Consistency with Free Chat
- Group chat uses the same patterns as single-user Free Chat for: file delete (with confirmation), message timestamps, message editing with "(edited)", and study plan with Stop. AI responses keep markdown (bold, lists, code blocks) and copy-code buttons.

## 5. Backend Endpoints

| Method | Path | Purpose |
|--------|------|--------|
| GET    | `/groups/{id}/files` | List files (includes `uploaded_by`) |
| DELETE | `/groups/{id}/files/{file_id}` | Delete file (uploader only) |
| GET    | `/groups/{id}/messages` | List messages (includes `created_at`, `updated_at`) |
| POST   | `/groups/{id}/messages/{id}/edit` | Edit message (author only) |
| POST   | `/ai/cancel/{request_id}` | Cancel AI generation (e.g. study plan) |

## 6. WebSocket Events

- **`message`:** New message (includes `created_at`, `updated_at` when relevant).
- **`message_updated`:** After an edit; payload has `id`, `message`, `updated_at`. All clients in the group update the message in place and show "(edited)" if applicable.
