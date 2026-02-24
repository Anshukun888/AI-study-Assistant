# Chat UX – Group & Single-User (Mobile & Desktop)

This document describes the current chat UI/UX behavior for **Group Study Chat** and **Single-User Free Chat** after the ChatGPT-style updates.

## Group Study Chat

### PDF / File Upload
- **PDF and file upload is removed** from group study chat. There is no "Upload PDF" or "Attach file" in the group chat input or sidebar.
- The **Shared Files** section in the sidebar is **read-only**: it lists existing files only; no upload control.
- Single-user Free Chat still supports document/PDF upload as before.

### Typing Indicator
- When another member is composing a message, **"User is typing…"** (or their username) appears below the message list.
- It appears dynamically and disappears after the message is sent or after a short timeout (~3s).
- Styled so it does not overlap messages on mobile (360px–768px) or desktop.

### Message Display
- **No username, date, or time** on message popup or hover. Messages are minimal; **sender color and AI vs user styling** are preserved.
- AI messages keep **formatting** (bold, italics, lists, code blocks) with **copy code** buttons on code blocks.

### Study Plan – Stop / Cancel
- When a study plan is generating (e.g. from a tool or @ai), a **Stop / Cancel** button is visible.
- Clicking it **stops** the AI generation for that user and shows the toast: **"Study plan generation stopped."**
- The backend terminates the run gracefully; **partial or incomplete plans are not saved**. The user can start a new generation if needed.

### Unread Message Indicators
- **No floating message toasts** (the previous blue notification toasts are removed).
- **Blue dot (unread indicator)**:
  - **Groups list (sidebar and mobile cards)**: A small blue dot appears next to a group when there are new messages. The dot **disappears** when the user opens that group or scrolls to bottom / focuses the input in that group.
  - **In the group chat header**: A small blue dot appears when there are new messages below the current scroll; it disappears when the user scrolls to bottom or focuses the input.
- Multiple new messages are indicated by a **single dot** (no stacking).

### Mobile
- **One "Create / Invite Group" entry**: The duplicate on the main content area is removed. The only entry is in the **sidebar (hamburger menu)** and is fully functional and mobile-friendly.
- Stop/Cancel for AI generation is **visible and accessible** (touch-friendly).
- Layout is responsive (360px–768px); input fixed at bottom; messages scrollable.

---

## Single-User Free Chat

### Message Display
- Messages are **minimal** (no extra username/date/time popup or hover clutter). Sender color and AI vs user styling are preserved.
- AI messages keep **formatting** and **copy code** buttons on code blocks.

### Study Plan – Stop / Cancel
- Same as group: **Stop / Cancel** button is visible when a study plan is generating; toast **"Study plan generation stopped."**; no partial save; user can restart.

### Unread
- Unread indicators for **conversations in the chat sidebar** can be added in a future update (e.g. blue dot when a conversation has new messages since last view).

---

## Responsive Behavior

- **Desktop**: Full sidebar; typing indicator and unread dot clearly visible; stop/cancel and copy code buttons easy to use.
- **Mobile (360px–768px)**: Sidebar becomes hamburger; one Create/Join Groups entry; typing indicator and unread dot visible without overlap; touch-friendly stop/cancel and copy code buttons.

---

## Backend

- **AI cancellation**: `POST /ai/cancel/{request_id}` marks the in-flight AI generation as cancelled for that request. Used by both single-user and group study plan (and group @ai) flows. Per-user; other users’ requests are unaffected.
- **Study plan stream**: `POST /api/study-plans/create-stream` returns `request_id` in the first line so the client can show Stop and call cancel. On cancel, no partial plan is saved.
- **Group list unread**: The groups list endpoint includes `last_message_id` per group so the frontend can show the blue dot when `last_message_id` is greater than the user’s stored "last read" (e.g. in `localStorage`).
