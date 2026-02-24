# Group Chat: Mobile UX, Notifications & Feature Parity with Free Chat

This document describes mobile-responsive behavior, message notifications, and **feature parity** between Group Chat and single-user Free Chat.

---

## Feature Parity with Free Chat

| Feature | Free Chat | Group Chat |
|--------|-----------|------------|
| **AI response formatting** | Markdown (bold, italics, headings, lists, tables, code blocks) | ✅ Same: `marked` with `breaks`, `gfm` |
| **Code block syntax highlighting** | Prism | ✅ Same: `highlightCode()` after render |
| **Copy code (one click)** | `.copy-code-btn` on each `pre` | ✅ Same: `addCopyButtonsToContainer()` |
| **Stop / Cancel AI** | Per-user; `POST /ai/cancel/{request_id}` | ✅ Per-user: only initiator sees Stop; cancel only that `request_id` |
| **Input bar** | [Attach] [Mic] + textarea + Send/Stop | ✅ Same layout; fixed at bottom on mobile |
| **Attach files** | PDF, images, DOCX; context for AI | ✅ Group upload + “Use in AI” for context |
| **Voice input (mic)** | Speech-to-text into input | ✅ Same in group input bar |
| **Auto-scroll** | Scroll to bottom on new message | ✅ Only when user is near bottom (`userScrolledUp` logic) |
| **Floating notifications** | N/A (single user) | ✅ New message toasts (sender + preview) |
| **Toasts** | Errors, success, info | ✅ Same: errors, “Generation stopped”, pin, clear, etc. |
| **Clear history** | Clear conversation messages | ✅ Admin: Clear group chat history |
| **Pin message** | N/A | ✅ Pin one message; shown in header strip |
| **Vote (upvote)** | N/A | ✅ Upvote messages (all non-file, including AI) |
| **Mark as solved** | In predicted-questions block (chat) | ✅ Per-message “Mark as solved” (localStorage) |
| **Multiple AI at once** | Single stream per user | ✅ Multiple members can trigger @ai in parallel; each has own `request_id` |

---

## AI Response Handling in Group Chat

- **Rich formatting**: AI messages are rendered with **marked.js** (same options as Free Chat: `breaks`, `gfm`, no `headerIds`/`mangle`). Bold, italics, headings, bullet/numbered lists, tables, and code blocks are preserved.
- **Code blocks**:
  - **Copy**: One-click copy via `.copy-code-btn` on each `pre`; clipboard icon switches to check on success; toast on copy failure.
  - **Highlighting**: **Prism** is applied with `highlightCode(container)` after render (same as Free Chat).
  - **Layout**: `max-width: 100%`, `overflow-x: auto` so long code scrolls horizontally on small screens; copy button remains visible.
- **Readability**: `.message-text` uses shared `.markdown-content` styles (spacing, font size, contrast). Text is selectable and copyable.
- **Stop/Cancel**:
  - **Visibility**: Only the user who sent the @ai message sees the Send button turn into **Stop**.
  - **Backend**: `POST /ai/cancel/{request_id}` marks only that `request_id` as cancelled; other users’ AI requests are unaffected.
  - **UI**: On stop, a “Response stopped by user” message is stored and broadcast; client shows toast “Generation stopped” and clears Stop state.

---

## Message Notifications

- **When**: Floating notification for each new message (user or AI) received over WebSocket (not when loading history).
- **Content**: Sender name (username or “AI”) + truncated preview (single line, ~80 chars).
- **Dismissal**: Auto-dismiss after **5.5 s**; max **5** visible; older ones removed as new ones appear.
- **Placement**: Fixed container bottom-right on desktop; on mobile (≤768px) full width at bottom with padding.
- **Implementation**: `showMessageNotification(senderName, truncatedMessage)` in `group_chat.js`; container `#groupMessageNotificationContainer` with class `group-message-notification-container` in CSS.

---

## Mobile UX / Responsive Design

### Layout (360–768px and below)

- **Input bar**: Fixed at bottom with `position: sticky; bottom: 0` and safe-area padding. Always shows:
  - **Top row**: [Attach File], [Mic].
  - **Bottom row**: Textarea + [Send] or [Stop].
- **Messages**: `.chat-messages` is scrollable (`overflow-y: auto`, `-webkit-overflow-scrolling: touch`). Messages use `max-width: 95%` (100% at 360px).
- **Auto-scroll**: New messages scroll into view only when the user is “at bottom” (within ~80px of bottom). If the user has scrolled up, we do not auto-scroll; “New” badge appears; scrolling to bottom or focusing input hides the badge.
- **Sender/meta**: Each message shows sender name, AI/user tag (via avatar/icon), and timestamp in `.message-meta`; tooltip gives full timestamp.

### Code Blocks on Mobile

- Long code blocks scroll horizontally with a visible copy button; `pre` has `overflow-x: auto` and `max-width: 100%`.

### Breakpoints

- **768px**: Sticky input, flex column for `.chat-main`, message max-width 95%, smaller meta/text.
- **576px**: Tighter padding on input and message area.
- **360px**: Message max-width 100%, slightly smaller code font.

---

## Backend: Per-User AI Cancel

- Each @ai run is registered with a unique `request_id` and the initiating **user id** (`cancel_register(group_request_id, user.id)`).
- **Cancel**: `POST /ai/cancel/{request_id}` only marks that `request_id` as cancelled. Other users’ in-flight requests are unchanged.
- On cancel, the group AI task raises `GenerationCancelledError`, persists “Response stopped by user”, broadcasts that message, and in `finally` sends `ai_finished` to all clients and calls `cancel_remove(request_id)`.

---

## Testing Checklist

- **Mobile (360–768px)**:
  - Input bar fixed at bottom; [Attach] and [Mic] visible and tappable.
  - Messages scroll; auto-scroll only when near bottom; “New” badge when scrolled up.
  - AI messages: markdown, code blocks with horizontal scroll and copy.
- **Multiple users**:
  - User A and B each send @ai; both get responses; A’s Stop only stops A’s request.
- **Notifications**:
  - New messages (user/AI) show floating toast; disappear after ~5.5s; no overlap.
- **Actions**:
  - Pin, vote, Mark as solved, Clear history (admin); toasts for success/errors and “Generation stopped” on cancel.
