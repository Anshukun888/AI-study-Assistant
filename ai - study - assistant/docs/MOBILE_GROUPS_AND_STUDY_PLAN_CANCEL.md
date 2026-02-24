# Mobile Group Management & Study Plan Cancel

This document describes mobile UX for the Collaborative Study Groups pages and the study plan generation stop/cancel behavior.

---

## 1. Mobile UI/UX for Group Management (Create / Join / List)

### Breakpoints

- **360px–768px**: Treated as mobile. Sidebar collapses; main area shows scrollable group cards and action buttons.
- **&lt; 991px**: Sidebar becomes a slide-over panel (hamburger menu). Same behavior as single-user chat layout.

### Groups List Page (`/groups/page/list`)

- **Sidebar** (left):
  - **Create Group** and **Join with invite link** buttons at top (touch-friendly, min 44px height).
  - List of user’s groups with role badge; each row has dropdown (Open, Leave, Delete for admin).
  - On mobile the sidebar is hidden by default and opens via **hamburger button** (top-left). Tapping the overlay or a group card closes it.
- **Main area**:
  - **Desktop**: Centered welcome text (“Collaborative Study Groups”, tips).
  - **Mobile**: 
    - **Create Group** and **Join Group** buttons at the top.
    - **Scrollable cards** for each group showing:
      - Group name
      - Member count
      - Last message snippet (or “No messages yet”)
      - “AI” badge when AI is available in the group
      - Tap/click opens the group chat.
    - Empty state message when there are no groups.

### Create Group

- **Modal**: Group name (required), optional description, and a note that invite link is available after creating.
- **Mobile**: Modal is full-screen (`.modal-fullscreen-mobile`) with body scroll and footer fixed at bottom. Inputs and buttons are touch-friendly (min 44px).
- **Submit**: Fixed at bottom of modal. Success toast and redirect to the new group.

### Join Group

- **Join with invite link**: Modal to paste invite URL or token; submit redirects to `/groups/invite/{token}`.
- **Mobile**: Same full-screen modal treatment and touch-friendly controls.
- **Toasts**: Success/error toasts for all group actions (create, join, leave, delete) and are visible on mobile (positioned with safe area).

### Touch & Accessibility

- Buttons and inputs use `.groups-btn-touch` / `.form-control-touch`: **min-height 44px**, `touch-action: manipulation`.
- Toasts use a container that stays within viewport on small screens.

### Backend Data for Cards

- The groups list page receives **member_count**, **last_message_snippet**, and **ai_enabled** per group (computed in `groups_page` and passed as `groups_with_roles`).
- Helpers: `get_group_member_count()`, `get_group_last_message_snippet()` in `backend/group_service.py`.

---

## 2. Study Plan Generation – Stop / Cancel

### Frontend

- **Loading modal**: Shown when “Generate” is clicked. Displays “Generating your study plan...” and a **Stop** button.
- **Stop button**: Shown after the first streamed chunk (when `request_id` is received). Touch-friendly (min 44×44px, `.study-plan-stop-btn`).
- **On Stop**:
  1. Frontend sets cancelled flag and calls `POST /ai/cancel/{request_id}`.
  2. Modal is closed and removed.
  3. Toast: **“Study plan generation stopped.”**
  4. User can start a new generation from the Study Plan dialog (no partial plan is shown).

### Backend

- **Stream endpoint**: `POST /api/study-plans/create-stream` returns NDJSON: first line `request_id`, then `chunk` lines, then either `done` or `cancelled`.
- **Cancellation**: 
  - A global **cancel store** (`backend/cancel_store.py`) tracks active requests by `request_id`. Each request is registered with the user id.
  - `POST /ai/cancel/{request_id}` marks that request as cancelled. Only that request is affected; other users’ requests are unchanged.
  - The study plan generator (`generate_study_plan_stream` in `ai_service.py`) checks `is_cancelled(request_id)` and raises `GenerationCancelledError` when cancelled.
- **On cancel**:
  - The in-progress study plan row is **deleted** (no partial save).
  - Response sends one NDJSON line: `{"cancelled": true}`.
  - `request_id` is removed from the cancel store in a `finally` block.

### Graceful Termination

- Partial results are **discarded** (plan record deleted on cancel).
- Only the specific user’s stream is terminated; other users’ study plan or chat generations are not affected.
- After stop, the UI immediately reflects that generation has stopped (modal closed, toast shown).

---

## 3. Group Chat Mobile (alignment with Free Chat)

- **Input bar**: [Attach File] and [Mic] in the top row; message input and Send (or Stop) in the bottom row. All controls min 44px on mobile.
- **Mic**: Voice input fills the message box (browser Speech Recognition); user can edit before sending. Same pattern as single-user chat.
- **Sidebar**: On mobile, group chat sidebar (Members, Files, AI Tools) is behind a **hamburger** toggle; overlay closes it.
- **AI Stop**: When the user has triggered an @ai request, the Send button becomes a **Stop** button until the AI finishes. Visible and touch-friendly on mobile.
- **New message badge**: A small “New” badge appears in the header when a new message (from another user or AI) arrives; it hides when the user scrolls to bottom or focuses the message input.
- **Toasts**: New message / AI response toasts (see `GROUP_CHAT_MOBILE_AND_NOTIFICATIONS.md`). Toasts are visible on mobile.
- **Code blocks**: Copy button on code blocks in messages; formatting and markdown preserved.

---

## 4. File Reference

| Area | Files |
|------|--------|
| Groups list template | `templates/groups.html` |
| Groups list JS | `static/js/groups.js` |
| Group chat template | `templates/group_chat.html` |
| Group chat JS | `static/js/group_chat.js` |
| Study plan stream & cancel | `static/js/study-features.js`, `backend/main.py` (`_study_plan_stream_generator`, `POST /api/study-plans/create-stream`, `POST /ai/cancel/{request_id}`) |
| Cancel store | `backend/cancel_store.py` |
| Group list data | `backend/group_service.py` (`get_group_member_count`, `get_group_last_message_snippet`), `backend/main.py` (`groups_page`) |
| Styles | `static/css/style.css` (groups cards, modals, touch, study plan stop button, badge) |
