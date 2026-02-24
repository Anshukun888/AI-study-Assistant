/**
 * AI Study Assistant - Premium Chat UI with Markdown Support
 * Features: Markdown rendering, syntax highlighting, copy buttons, inline editing, dark mode
 */
(function () {
    'use strict';

    // Initialize Marked.js with safe options
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
            headerIds: false,
            mangle: false,
        });
    }

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const convIdEl = document.getElementById('conversationId');
    const chatForm = document.getElementById('chatForm');
    const messageInput = document.getElementById('messageInput');
    const chatMessages = document.getElementById('chatMessages');
    const emptyState = document.getElementById('emptyState');
    const btnSend = document.getElementById('btnSend');
    const btnNewChat = document.getElementById('btnNewChat');
    const modeRadios = document.querySelectorAll('input[name="chatMode"]');
    const modeDocumentSelect = document.getElementById('modeDocumentSelect');
    const selectDocument = document.getElementById('selectDocument');
    const notesPanel = document.getElementById('notesPanel');
    const notesContext = document.getElementById('notesContext');
    const btnApplyNotes = document.getElementById('btnApplyNotes');
    const toolInputModal = document.getElementById('toolInputModal');
    const toolModalTitle = document.getElementById('toolModalTitle');
    const toolInputLabel = document.getElementById('toolInputLabel');
    const toolInput = document.getElementById('toolInput');
    const btnToolSubmit = document.getElementById('btnToolSubmit');
    const darkModeToggle = document.getElementById('darkModeToggle');
    const darkModeIcon = document.getElementById('darkModeIcon');
    const chatContainer = document.getElementById('chatContainer');
    const editMessageModal = document.getElementById('editMessageModal');
    const editMessageInput = document.getElementById('editMessageInput');
    const btnSaveEdit = document.getElementById('btnSaveEdit');
    const fileInput = document.getElementById('fileInput');
    const attachmentPreview = document.getElementById('attachmentPreview');
    const btnClearHistory = document.getElementById('btnClearHistory');
    const clearHistoryModal = document.getElementById('clearHistoryModal');

    let editingMessageId = null;
    let attachments = [];

    // Dark mode: localStorage + prefers-color-scheme
    function initDarkMode() {
        const saved = localStorage.getItem('darkMode');
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const isDark = saved === 'true' || (saved === null && prefersDark);
        setDarkMode(isDark);
    }

    function setDarkMode(enabled) {
        document.body.classList.toggle('dark-mode', enabled);
        chatContainer?.classList.toggle('dark-mode', enabled);
        localStorage.setItem('darkMode', enabled ? 'true' : 'false');
        if (darkModeIcon) {
            darkModeIcon.className = enabled ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
        }
        const prismDarkTheme = document.getElementById('prism-dark-theme');
        if (prismDarkTheme) {
            prismDarkTheme.media = enabled ? 'all' : '(prefers-color-scheme: dark)';
        }
    }

    darkModeToggle?.addEventListener('click', () => {
        const isDark = document.body.classList.contains('dark-mode');
        setDarkMode(!isDark);
    });

    initDarkMode();

    // Utility functions
    function getConversationId() {
        const v = convIdEl?.value?.trim();
        return v ? parseInt(v, 10) : null;
    }

    function setConversationId(id) {
        if (convIdEl) convIdEl.value = id ? String(id) : '';
        updateClearHistoryButtonVisibility();
    }

    function updateClearHistoryButtonVisibility() {
        if (btnClearHistory) btnClearHistory.style.display = getConversationId() ? '' : 'none';
    }

    function showToast(message, type) {
        type = type || 'info';
        const container = document.getElementById('alertToastContainer');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = 'toast align-items-center text-bg-' + type + ' border-0 show';
        toast.setAttribute('role', 'alert');
        toast.innerHTML = '<div class="d-flex"><div class="toast-body">' + escapeHtml(message) + '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
        container.appendChild(toast);
        const bsToast = new bootstrap.Toast(toast, { delay: 4000 });
        bsToast.show();
        toast.addEventListener('hidden.bs.toast', () => toast.remove());
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    function typeOutEffect(element, rawText, options) {
        options = options || {};
        const wordDelay = options.wordDelay !== undefined ? options.wordDelay : 35;
        const onDone = options.onDone || (function() {});
        if (!element || !rawText) {
            onDone();
            return { stop: function() {} };
        }
        const words = rawText.split(/(\s+)/);
        let index = 0;
        let stopped = false;
        function tick() {
            if (stopped || index >= words.length) {
                element.setAttribute('data-raw-content', escapeHtml(rawText));
                element.innerHTML = renderMarkdown(rawText);
                addCopyButtons(element);
                highlightCode(element);
                onDone();
                return;
            }
            const slice = words.slice(0, index + 1).join('');
            element.setAttribute('data-raw-content', escapeHtml(slice));
            element.innerHTML = renderMarkdown(slice);
            index++;
            addCopyButtons(element);
            highlightCode(element);
            timeoutId = setTimeout(tick, wordDelay);
        }
        let timeoutId = setTimeout(tick, wordDelay);
        return {
            stop: function() {
                stopped = true;
                if (timeoutId) clearTimeout(timeoutId);
                element.setAttribute('data-raw-content', escapeHtml(rawText));
                element.innerHTML = renderMarkdown(rawText);
                addCopyButtons(element);
                highlightCode(element);
                onDone();
            }
        };
    }

    function addConversationToSidebar(id, title) {
        const list = document.getElementById('conversationList');
        if (!list) return;
        const wrapper = document.createElement('div');
        wrapper.className = 'conversation-item-wrapper d-flex align-items-center';
        wrapper.innerHTML = `
            <a href="/chat?conv_id=${id}" class="conversation-item flex-grow-1 active" data-id="${id}">
                <i class="bi bi-chat-dots me-2"></i>
                <span class="conv-title">${escapeHtml(title || 'New Chat')}</span>
            </a>
            <div class="dropdown ms-1">
                <button class="btn btn-sm btn-link text-muted px-1" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                    <i class="bi bi-three-dots-vertical"></i>
                </button>
                <ul class="dropdown-menu dropdown-menu-end">
                    <li>
                        <button class="dropdown-item text-danger btn-delete-conversation" type="button" data-conversation-id="${id}">
                            <i class="bi bi-trash me-1"></i>Delete chat
                        </button>
                    </li>
                </ul>
            </div>
        `;
        list.insertBefore(wrapper, list.firstChild);
        list.querySelectorAll('.conversation-item').forEach((x, i) => {
            if (i > 0) x.classList.remove('active');
        });
        bindDeleteButtons(wrapper);
    }

    window.openStudyPlanChat = function(conversationId, title, content) {
        setConversationId(conversationId);
        if (emptyState) emptyState.style.display = 'none';
        chatMessages.querySelectorAll('.message').forEach(m => m.remove());
        addConversationToSidebar(conversationId, title);
        const contentEl = appendMessage('assistant', 'AI is thinking…', null, true);
        const msgWrap = contentEl && contentEl.closest('.message');
        if (contentEl && content && typeof typeOutEffect === 'function') {
            if (msgWrap) msgWrap.classList.remove('streaming');
            typeOutEffect(contentEl, content, { wordDelay: 25 });
        } else if (contentEl) {
            contentEl.setAttribute('data-raw-content', escapeHtml(content || ''));
            contentEl.innerHTML = renderMarkdown(content || '');
            addCopyButtons(contentEl);
            highlightCode(contentEl);
            if (msgWrap) msgWrap.classList.remove('streaming');
        }
        if (history.pushState) history.pushState({ convId: conversationId }, '', `/chat?conv_id=${conversationId}`);
    };

    function getCurrentMode() {
        const r = document.querySelector('input[name="chatMode"]:checked');
        return r ? r.value : 'free';
    }

    // Render Markdown content
    function renderMarkdown(content) {
        if (!content) return '';
        if (typeof marked === 'undefined') {
            // Fallback if marked.js not loaded
            return escapeHtml(content).replace(/\n/g, '<br>');
        }
        try {
            return marked.parse(content);
        } catch (e) {
            console.error('Markdown parsing error:', e);
            return escapeHtml(content).replace(/\n/g, '<br>');
        }
    }

    // Add copy button to code blocks
    function addCopyButtons(container) {
        if (!container) return;
        container.querySelectorAll('pre code').forEach((codeBlock) => {
            const pre = codeBlock.parentElement;
            if (pre.querySelector('.copy-code-btn')) return; // Already has button

            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-code-btn btn btn-sm';
            copyBtn.innerHTML = '<i class="bi bi-clipboard"></i>';
            copyBtn.title = 'Copy code';
            copyBtn.onclick = async () => {
                const text = codeBlock.textContent || codeBlock.innerText;
                try {
                    await navigator.clipboard.writeText(text);
                    copyBtn.innerHTML = '<i class="bi bi-check"></i>';
                    copyBtn.classList.add('copied');
                    setTimeout(() => {
                        copyBtn.innerHTML = '<i class="bi bi-clipboard"></i>';
                        copyBtn.classList.remove('copied');
                    }, 2000);
                } catch (err) {
                    console.error('Failed to copy:', err);
                }
            };
            pre.style.position = 'relative';
            pre.appendChild(copyBtn);
        });
    }

    // Highlight code blocks with Prism
    function highlightCode(container) {
        if (!container || typeof Prism === 'undefined') return;
        container.querySelectorAll('pre code').forEach((block) => {
            Prism.highlightElement(block);
        });
    }

    // Append message to chat
    function appendMessage(role, content, messageId = null, isStreaming = false) {
        const wrap = document.createElement('div');
        wrap.className = `message message-${role}${isStreaming ? ' streaming' : ''}`;
        if (messageId) {
            wrap.setAttribute('data-message-id', messageId);
            wrap.setAttribute('data-role', role);
        }
        const icon = role === 'user' ? 'bi-person-circle' : 'bi-robot';
        const actionsHtml = role === 'user' 
            ? `<button class="btn-edit-message btn btn-sm btn-link text-muted" data-message-id="${messageId || ''}" title="Edit message">
                <i class="bi bi-pencil"></i>
            </button>`
            : `<button class="btn-regenerate btn btn-sm btn-link text-muted" data-message-id="${messageId || ''}" title="Regenerate response">
                <i class="bi bi-arrow-clockwise"></i>
            </button>`;
        
        wrap.innerHTML = `
            <div class="message-avatar"><i class="bi ${icon}"></i></div>
            <div class="message-content">
                <div class="message-actions">${actionsHtml}</div>
                <div class="message-text markdown-content" data-raw-content="${escapeHtml(content)}">${renderMarkdown(content)}</div>
            </div>
        `;
        chatMessages.appendChild(wrap);
        if (emptyState) emptyState.style.display = 'none';
        
        // Add copy buttons and highlight code
        const contentEl = wrap.querySelector('.message-text');
        addCopyButtons(contentEl);
        highlightCode(contentEl);
        
        // Bind edit/regenerate buttons
        bindMessageActions(wrap);
        
        wrap.scrollIntoView({ behavior: 'smooth', block: 'end' });
        return wrap.querySelector('.message-text');
    }

    // Bind message action buttons
    function bindMessageActions(scope) {
        (scope || document).querySelectorAll('.btn-edit-message').forEach(btn => {
            if (btn.dataset.bound === '1') return;
            btn.dataset.bound = '1';
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const msgId = parseInt(btn.getAttribute('data-message-id'), 10);
                editMessage(msgId);
            });
        });
        
        (scope || document).querySelectorAll('.btn-regenerate').forEach(btn => {
            if (btn.dataset.bound === '1') return;
            btn.dataset.bound = '1';
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const msgId = parseInt(btn.getAttribute('data-message-id'), 10);
                regenerateMessage(msgId);
            });
        });
    }

    // Edit message
    function editMessage(messageId) {
        const msgEl = document.querySelector(`[data-message-id="${messageId}"][data-role="user"]`);
        if (!msgEl) return;
        const contentEl = msgEl.querySelector('.message-text');
        const rawContent = contentEl.getAttribute('data-raw-content') || contentEl.textContent;
        editingMessageId = messageId;
        editMessageInput.value = rawContent;
        const modal = new bootstrap.Modal(editMessageModal);
        modal.show();
    }

    // Save edited message and regenerate
    btnSaveEdit?.addEventListener('click', async () => {
        if (!editingMessageId) return;
        const newContent = editMessageInput.value.trim();
        if (!newContent) {
            alert('Message cannot be empty');
            return;
        }
        const modal = bootstrap.Modal.getInstance(editMessageModal);
        modal.hide();
        
        const userMsgEl = document.querySelector(`[data-message-id="${editingMessageId}"][data-role="user"]`);
        const aiMsgEl = userMsgEl?.nextElementSibling;
        
        try {
            const formData = new FormData();
            formData.append('content', newContent);
            const resp = await fetch(`/chat/message/${editingMessageId}/edit`, {
                method: 'POST',
                body: formData,
                credentials: 'include',
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.detail || 'Failed to edit message');
            
            // Update UI dynamically (no reload)
            if (userMsgEl) {
                const textEl = userMsgEl.querySelector('.message-text');
                if (textEl) {
                    textEl.setAttribute('data-raw-content', escapeHtml(newContent));
                    textEl.innerHTML = renderMarkdown(newContent);
                }
            }
            // Remove any messages after the user message (backend deletes them)
            let next = userMsgEl?.nextElementSibling;
            while (next) {
                const toRemove = next;
                next = next.nextElementSibling;
                toRemove.remove();
            }
            // Append new AI response
            const rawContent = data.content || '';
            const aiContentEl = appendMessage('assistant', rawContent, data.assistant_message_id || null);
            if (aiContentEl) {
                addCopyButtons(aiContentEl);
                highlightCode(aiContentEl);
                const msgWrap = aiContentEl.closest('.message');
                if (msgWrap) {
                    msgWrap.setAttribute('data-message-id', data.assistant_message_id || '');
                    msgWrap.setAttribute('data-role', 'assistant');
                    const actionsEl = msgWrap.querySelector('.message-actions');
                    if (actionsEl) {
                        actionsEl.innerHTML = `<button class="btn-regenerate btn btn-sm btn-link text-muted" data-message-id="${editingMessageId}" title="Regenerate response"><i class="bi bi-arrow-clockwise"></i></button>`;
                        bindMessageActions(msgWrap);
                    }
                }
            }
        } catch (e) {
            alert('Error: ' + (e.message || 'Failed to edit message'));
        }
    });

    // Regenerate AI response (dynamic update, no reload)
    async function regenerateMessage(messageId) {
        if (!confirm('Regenerate AI response for this message?')) return;
        
        const targetUserMsg = document.querySelector(`[data-message-id="${messageId}"][data-role="user"]`);
        if (!targetUserMsg) {
            alert('Message not found');
            return;
        }
        
        // Find the AI message that follows this user message
        let nextAiMsg = targetUserMsg.nextElementSibling;
        while (nextAiMsg && !nextAiMsg.classList.contains('message-assistant')) {
            nextAiMsg = nextAiMsg.nextElementSibling;
        }
        
        // Show loading state
        if (nextAiMsg) {
            const contentEl = nextAiMsg.querySelector('.message-text');
            if (contentEl) {
                contentEl.innerHTML = '<em>Regenerating...</em>';
            }
        }
        
        try {
            const resp = await fetch(`/chat/message/${messageId}/regenerate`, {
                method: 'POST',
                credentials: 'include',
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.detail || 'Failed to regenerate');
            
            // Update AI message in place
            if (nextAiMsg && nextAiMsg.classList.contains('message-assistant')) {
                const contentEl = nextAiMsg.querySelector('.message-text');
                if (contentEl) {
                    const rawContent = data.content || '';
                    contentEl.setAttribute('data-raw-content', escapeHtml(rawContent));
                    contentEl.innerHTML = renderMarkdown(rawContent);
                    addCopyButtons(contentEl);
                    highlightCode(contentEl);
                    
                    // Update message ID if provided
                    if (data.assistant_message_id) {
                        nextAiMsg.setAttribute('data-message-id', data.assistant_message_id);
                    }
                }
            } else {
                // If AI message doesn't exist, append it
                const rawContent = data.content || '';
                const aiContentEl = appendMessage('assistant', rawContent, data.assistant_message_id || null);
                if (aiContentEl) {
                    addCopyButtons(aiContentEl);
                    highlightCode(aiContentEl);
                    const msgWrap = aiContentEl.closest('.message');
                    if (msgWrap && data.assistant_message_id) {
                        msgWrap.setAttribute('data-message-id', data.assistant_message_id);
                        msgWrap.setAttribute('data-role', 'assistant');
                        const actionsEl = msgWrap.querySelector('.message-actions');
                        if (actionsEl) {
                            actionsEl.innerHTML = `<button class="btn-regenerate btn btn-sm btn-link text-muted" data-message-id="${messageId}" title="Regenerate response"><i class="bi bi-arrow-clockwise"></i></button>`;
                            bindMessageActions(msgWrap);
                        }
                    }
                }
            }
        } catch (e) {
            alert('Error: ' + (e.message || 'Failed to regenerate response'));
            if (nextAiMsg) {
                const contentEl = nextAiMsg.querySelector('.message-text');
                if (contentEl) {
                    contentEl.innerHTML = renderMarkdown('Error: ' + (e.message || 'Failed to regenerate'));
                }
            }
        }
    }

    let currentStreamAbortController = null;
    let currentRequestId = null;
    let currentToolAbortController = null;
    let currentToolRequestId = null;

    function generateRequestId() {
        if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    function stopGeneration() {
        if (currentStreamAbortController && currentRequestId) {
            fetch('/ai/cancel/' + currentRequestId, { method: 'POST', credentials: 'include' }).catch(function() {});
            currentRequestId = null;
        }
        if (currentStreamAbortController) {
            currentStreamAbortController.abort();
            currentStreamAbortController = null;
        }
        if (currentToolAbortController && currentToolRequestId) {
            fetch('/ai/cancel/' + currentToolRequestId, { method: 'POST', credentials: 'include' }).catch(function() {});
            currentToolRequestId = null;
            currentToolAbortController.abort();
            currentToolAbortController = null;
        }
    }

    function setLoading(loading, showStop = false) {
        btnSend.disabled = loading && !showStop;
        if (showStop) {
            btnSend.innerHTML = '<i class="bi bi-stop-fill"></i>';
            btnSend.title = 'Stop generating';
        } else if (loading) {
            btnSend.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        } else {
            btnSend.innerHTML = '<i class="bi bi-send-fill"></i>';
            btnSend.title = 'Send';
        }
    }

    async function sendMessage(content, attachedFile) {
        let cid = getConversationId();
        const mode = getCurrentMode();

        if (!cid) {
            const docId = mode === 'document' && selectDocument ? selectDocument.value : null;
            const notes = mode === 'notes' && notesContext ? notesContext.value.trim() : null;
            const title = content.length > 50 ? content.substring(0, 50) + '...' : content;

            const formData = new FormData();
            formData.append('title', title);
            formData.append('mode', mode);
            if (docId) formData.append('document_id', docId);
            if (notes) formData.append('notes_context', notes);

            const resp = await fetch('/chat/new', {
                method: 'POST',
                body: formData,
                credentials: 'include',
                headers: { Accept: 'application/json' },
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to create conversation');
            }
            const data = await resp.json().catch(() => ({}));
            cid = data.conversation_id;
            if (cid) setConversationId(cid);
            else {
                const loc = resp.headers.get('Location');
                if (loc) {
                    const u = new URL(loc);
                    const q = u.searchParams.get('conv_id');
                    if (q) { cid = parseInt(q, 10); setConversationId(cid); }
                }
            }
            if (!cid) throw new Error('Failed to create conversation');
            addConversationToSidebar(cid, content.length > 40 ? content.substring(0, 40) + '...' : content);
        }

        appendMessage('user', content);

        const fd = new FormData();
        fd.append('conversation_id', cid);
        fd.append('content', content);
        if (attachedFile) fd.append('file', attachedFile, attachedFile.name || 'file');

        setLoading(true);
        const thinkingEl = appendMessage('assistant', 'AI is thinking…', null, true);
        const contentEl = thinkingEl;
        const msgWrap = contentEl.closest('.message');

        const useStream = true;
        currentStreamAbortController = new AbortController();
        currentRequestId = null;

        if (useStream) {
            setLoading(true, true);
            var streamBuffer = '';
            var thinkingShown = true;
            const thinkingDelay = 1200;
            const thinkingTimer = setTimeout(() => {
                if (thinkingShown && streamBuffer === '') {
                    contentEl.textContent = 'AI is thinking…';
                }
            }, thinkingDelay);

            try {
                const resp = await fetch('/chat/send/stream', {
                    method: 'POST',
                    body: fd,
                    credentials: 'include',
                    signal: currentStreamAbortController.signal,
                });
                if (!resp.ok) {
                    const errData = await resp.json().catch(() => ({}));
                    const msg = errData.detail || (typeof errData === 'string' ? errData : 'Failed to send message');
                    throw new Error(Array.isArray(msg) ? msg.join(' ') : msg);
                }
                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    const chunk = decoder.decode(value, { stream: true });
                    const lines = chunk.split('\n');
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                if (data.request_id) currentRequestId = data.request_id;
                                if (data.cancelled) {
                                    streamBuffer += (streamBuffer ? '\n\n' : '') + 'Response stopped by user';
                                    contentEl.setAttribute('data-raw-content', escapeHtml(streamBuffer));
                                    contentEl.innerHTML = renderMarkdown(streamBuffer);
                                    addCopyButtons(contentEl);
                                    highlightCode(contentEl);
                                }
                                if (data.error) throw new Error(data.error);
                                if (data.chunk) {
                                    streamBuffer += data.chunk;
                                    if (thinkingShown) {
                                        thinkingShown = false;
                                        contentEl.setAttribute('data-raw-content', escapeHtml(streamBuffer));
                                        contentEl.innerHTML = renderMarkdown(streamBuffer);
                                    } else {
                                        contentEl.setAttribute('data-raw-content', escapeHtml(streamBuffer));
                                        contentEl.innerHTML = renderMarkdown(streamBuffer);
                                    }
                                    addCopyButtons(contentEl);
                                    highlightCode(contentEl);
                                    msgWrap?.scrollIntoView({ behavior: 'smooth', block: 'end' });
                                }
                                if (data.done) {
                                    if (data.cancelled && !streamBuffer) {
                                        streamBuffer = 'Response stopped by user';
                                        contentEl.setAttribute('data-raw-content', escapeHtml(streamBuffer));
                                        contentEl.innerHTML = renderMarkdown(streamBuffer);
                                        addCopyButtons(contentEl);
                                        highlightCode(contentEl);
                                    }
                                    currentRequestId = null;
                                    if (data.assistant_message_id) msgWrap?.setAttribute('data-message-id', data.assistant_message_id);
                                    msgWrap?.setAttribute('data-role', 'assistant');
                                    const userMsgWrap = msgWrap?.previousElementSibling;
                                    if (userMsgWrap && data.user_message_id) {
                                        userMsgWrap.setAttribute('data-message-id', data.user_message_id);
                                        userMsgWrap.setAttribute('data-role', 'user');
                                    }
                                    const actionsEl = msgWrap?.querySelector('.message-actions');
                                    if (actionsEl && data.user_message_id) {
                                        actionsEl.innerHTML = `<button class="btn-regenerate btn btn-sm btn-link text-muted" data-message-id="${data.user_message_id}" title="Regenerate response"><i class="bi bi-arrow-clockwise"></i></button>`;
                                        bindMessageActions(msgWrap);
                                    }
                                }
                            } catch (parseErr) {
                                if (parseErr.name === 'AbortError') throw parseErr;
                            }
                        }
                    }
                }
                clearTimeout(thinkingTimer);
                if (msgWrap) msgWrap.classList.remove('streaming');
                const voiceOutputBtn = document.getElementById('btnVoiceOutput');
                if (voiceOutputBtn) voiceOutputBtn.classList.remove('d-none');
                if (cid && history.pushState) history.pushState({ convId: cid }, '', `/chat?conv_id=${cid}`);
            } catch (e) {
                clearTimeout(thinkingTimer);
                currentRequestId = null;
                if (e.name === 'AbortError') {
                    contentEl.setAttribute('data-raw-content', escapeHtml(streamBuffer));
                    contentEl.innerHTML = renderMarkdown(streamBuffer ? streamBuffer : 'Response stopped by user');
                } else {
                    const errMsg = e.message || 'Something went wrong';
                    contentEl.innerHTML = renderMarkdown('Error: ' + errMsg);
                    if (window.showAlert) window.showAlert(errMsg, 'danger');
                    else alert('Error: ' + errMsg);
                }
                addCopyButtons(contentEl);
                highlightCode(contentEl);
                if (msgWrap) msgWrap.classList.remove('streaming');
            }
            currentStreamAbortController = null;
            setLoading(false);
            messageInput.value = '';
            return;
        }

        try {
            const resp = await fetch('/chat/send', {
                method: 'POST',
                body: fd,
                credentials: 'include',
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                const msg = data.detail || 'Failed to send message';
                throw new Error(Array.isArray(msg) ? msg.join(' ') : msg);
            }
            const rawContent = data.content || '';
            contentEl.setAttribute('data-raw-content', escapeHtml(rawContent));
            contentEl.innerHTML = renderMarkdown(rawContent);
            addCopyButtons(contentEl);
            highlightCode(contentEl);
            const userMsgWrap = msgWrap?.previousElementSibling;
            if (userMsgWrap && data.user_message_id) {
                userMsgWrap.setAttribute('data-message-id', data.user_message_id);
                userMsgWrap.setAttribute('data-role', 'user');
            }
            if (msgWrap) {
                msgWrap.classList.remove('streaming');
                if (data.assistant_message_id) {
                    msgWrap.setAttribute('data-message-id', data.assistant_message_id);
                    msgWrap.setAttribute('data-role', 'assistant');
                }
                const actionsEl = msgWrap.querySelector('.message-actions');
                if (actionsEl) {
                    actionsEl.innerHTML = `<button class="btn-regenerate btn btn-sm btn-link text-muted" data-message-id="${data.user_message_id || ''}" title="Regenerate response"><i class="bi bi-arrow-clockwise"></i></button>`;
                    bindMessageActions(msgWrap);
                }
            }
            const voiceOutputBtn = document.getElementById('btnVoiceOutput');
            if (voiceOutputBtn) voiceOutputBtn.classList.remove('d-none');
            if (cid && history.pushState) history.pushState({ convId: cid }, '', `/chat?conv_id=${cid}`);
        } catch (e) {
            const errMsg = e.message || 'Something went wrong';
            contentEl.innerHTML = renderMarkdown('Error: ' + errMsg);
            if (window.showAlert) window.showAlert(errMsg, 'danger');
            else alert('Error: ' + errMsg);
        } finally {
            setLoading(false);
            messageInput.value = '';
        }
    }

    let deleteChatModalConvId = null;
    let deleteChatModalButton = null;

    function showDeleteChatModal(conversationId, buttonEl) {
        deleteChatModalConvId = conversationId;
        deleteChatModalButton = buttonEl;
        const modal = document.getElementById('deleteChatModal');
        if (modal) {
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();
        }
    }

    function hideDeleteChatModal() {
        const modal = document.getElementById('deleteChatModal');
        if (modal) {
            const bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) bsModal.hide();
        }
        deleteChatModalConvId = null;
        deleteChatModalButton = null;
    }

    async function confirmDeleteConversation() {
        if (!deleteChatModalConvId) return;
        const conversationId = deleteChatModalConvId;
        const buttonEl = deleteChatModalButton;
        hideDeleteChatModal();
        try {
            const resp = await fetch(`/chat/${conversationId}/delete`, {
                method: 'POST',
                credentials: 'include',
                headers: { Accept: 'application/json' },
            });
            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                alert(data.detail || 'Failed to delete chat');
                return;
            }
            const wrapper = buttonEl && buttonEl.closest('.conversation-item-wrapper');
            if (wrapper && wrapper.parentElement) {
                wrapper.parentElement.removeChild(wrapper);
            }
            const currentId = getConversationId();
            if (currentId && String(currentId) === String(conversationId)) {
                setConversationId('');
                messageInput.value = '';
                chatMessages.querySelectorAll('.message').forEach(m => m.remove());
                if (emptyState) emptyState.style.display = '';
                if (history && history.pushState) {
                    history.pushState({}, '', '/chat');
                }
                updateClearHistoryButtonVisibility();
            }
        } catch (e) {
            alert('Failed to delete chat: ' + (e.message || 'Unknown error'));
        }
    }

    document.getElementById('deleteChatModalCancel')?.addEventListener('click', hideDeleteChatModal);
    document.getElementById('deleteChatModalConfirm')?.addEventListener('click', confirmDeleteConversation);

    async function deleteConversation(conversationId, buttonEl) {
        if (!conversationId) return;
        showDeleteChatModal(conversationId, buttonEl);
    }

    function bindDeleteButtons(scope) {
        (scope || document).querySelectorAll('.btn-delete-conversation').forEach(btn => {
            if (btn.dataset.bound === '1') return;
            btn.dataset.bound = '1';
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const id = btn.getAttribute('data-conversation-id');
                deleteConversation(id, btn);
            });
        });
    }

    async function callTool(tool, extra) {
        let cid = getConversationId();
        const mode = getCurrentMode();
        const isExplain = tool === 'explain';

        if (!cid) {
            const formData = new FormData();
            formData.append('title', tool.charAt(0).toUpperCase() + tool.slice(1));
            if (isExplain) {
                formData.append('mode', 'free');
            } else {
                const docId = mode === 'document' && selectDocument ? selectDocument.value : null;
                const notes = mode === 'notes' && notesContext ? notesContext.value.trim() : null;
                formData.append('mode', mode);
                if (docId) formData.append('document_id', docId);
                if (notes) formData.append('notes_context', notes);
            }

            const resp = await fetch('/chat/new', {
                method: 'POST',
                body: formData,
                credentials: 'include',
                headers: { Accept: 'application/json' },
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                const d = err.detail;
                const msg = Array.isArray(d) ? (d[0] && d[0].msg) || String(d[0]) : (d || 'Failed to create conversation.');
                alert(typeof msg === 'string' ? msg : 'Failed to create conversation.');
                return;
            }
            const data = await resp.json().catch(() => ({}));
            cid = data.conversation_id;
            if (cid) {
                setConversationId(cid);
                addConversationToSidebar(cid, tool.charAt(0).toUpperCase() + tool.slice(1));
                if (history.pushState) history.pushState({ convId: cid }, '', `/chat?conv_id=${cid}`);
            } else {
                const u = new URL(resp.url);
                const q = u.searchParams.get('conv_id');
                if (q) {
                    cid = parseInt(q, 10);
                    setConversationId(cid);
                    addConversationToSidebar(cid, tool.charAt(0).toUpperCase() + tool.slice(1));
                    if (history.pushState) history.pushState({ convId: cid }, '', `/chat?conv_id=${cid}`);
                }
            }
        }

        const fd = new FormData();
        fd.append('conversation_id', cid);
        if (extra) {
            if (extra.topic !== undefined) {
                fd.append('topic', extra.topic);
                if (extra.document_id != null && extra.document_id !== '') {
                    fd.append('document_id', String(extra.document_id));
                }
            } else {
                fd.append(extra.key, extra.value);
            }
        }
        var toolRequestId = generateRequestId();
        fd.append('request_id', toolRequestId);

        const endpoint = {
            summarize: '/chat/tools/summarize',
            mcq: '/chat/tools/mcq',
            explain: '/chat/tools/explain',
        }[tool];
        if (!endpoint) return;

        currentToolAbortController = new AbortController();
        currentToolRequestId = toolRequestId;
        setLoading(true, true);
        const el = appendMessage('assistant', 'AI is thinking…', null, true);
        const contentEl = el;
        const msgWrap = contentEl.closest('.message');
        try {
            const resp = await fetch(endpoint, {
                method: 'POST',
                body: fd,
                credentials: 'include',
                signal: currentToolAbortController.signal,
            });
            const data = await resp.json().catch(() => ({}));
            const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg || d).join(' ') : (data.detail || 'Request failed');
            const content = resp.ok ? (data.content || '') : ('Error: ' + detail);
            currentToolAbortController = null;
            currentToolRequestId = null;
            msgWrap.classList.remove('streaming');
            typeOutEffect(contentEl, content, {
                wordDelay: 30,
                onDone: function() {
                    const actionsEl = msgWrap.querySelector('.message-actions');
                    if (actionsEl) {
                        actionsEl.innerHTML = `<button class="btn-regenerate btn btn-sm btn-link text-muted" title="Regenerate response">
                            <i class="bi bi-arrow-clockwise"></i>
                        </button>`;
                        bindMessageActions(msgWrap);
                    }
                }
            });
        } catch (e) {
            currentToolAbortController = null;
            currentToolRequestId = null;
            var errMsg = e.name === 'AbortError' ? 'Response stopped by user' : (e.message || 'Network error');
            contentEl.setAttribute('data-raw-content', escapeHtml(errMsg));
            contentEl.innerHTML = renderMarkdown(errMsg);
            if (msgWrap) msgWrap.classList.remove('streaming');
        } finally {
            setLoading(false);
        }
    }

    const explainOptionsEl = document.getElementById('explainOptions');
    const explainUseDocumentCheck = document.getElementById('explainUseDocument');
    const explainDocumentWrapEl = document.getElementById('explainDocumentWrap');
    const explainDocumentSelectEl = document.getElementById('explainDocumentSelect');

    function showToolModal(tool, label, placeholder) {
        toolModalTitle.textContent = label;
        toolInputLabel.textContent = tool === 'explain' ? 'Enter topic to explain' : 'Topic';
        toolInput.placeholder = placeholder || 'Enter...';
        toolInput.value = '';

        if (tool === 'explain') {
            if (explainOptionsEl) explainOptionsEl.style.display = 'block';
            if (explainUseDocumentCheck) {
                explainUseDocumentCheck.checked = false;
                if (explainDocumentWrapEl) explainDocumentWrapEl.style.display = 'none';
            }
            if (explainUseDocumentCheck && explainDocumentWrapEl) {
                explainUseDocumentCheck.onchange = () => {
                    explainDocumentWrapEl.style.display = explainUseDocumentCheck.checked ? 'block' : 'none';
                };
            }
        } else {
            if (explainOptionsEl) explainOptionsEl.style.display = 'none';
        }

        const modal = new bootstrap.Modal(toolInputModal);
        modal.show();
        btnToolSubmit.onclick = () => {
            const val = toolInput.value.trim();
            if (tool === 'explain') {
                if (!val) {
                    if (typeof showAlert === 'function') showAlert('Please enter a topic to explain.', 'danger');
                    else alert('Please enter a topic to explain.');
                    return;
                }
                const useDoc = explainUseDocumentCheck && explainUseDocumentCheck.checked;
                const docId = useDoc && explainDocumentSelectEl ? (explainDocumentSelectEl.value || null) : null;
                if (useDoc && !docId) {
                    if (typeof showAlert === 'function') showAlert('Please select a document or uncheck "Use uploaded document".', 'danger');
                    else alert('Please select a document or uncheck "Use uploaded document".');
                    return;
                }
                modal.hide();
                callTool('explain', { topic: val, document_id: docId || undefined });
            } else {
                modal.hide();
                if (val) callTool(tool, { key: 'topic', value: val });
            }
        };
    }

    // Event listeners
    chatForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (currentStreamAbortController || currentToolAbortController) {
            stopGeneration();
            return;
        }
        const content = messageInput.value.trim();
        if (!content && !(window.__attachedFiles && window.__attachedFiles.length)) return;
        const text = content || 'Summarize or explain the attached file.';
        const file = window.__attachedFiles && window.__attachedFiles.length ? window.__attachedFiles[0] : null;
        if (window.__clearAttachments) window.__clearAttachments();
        await sendMessage(text, file);
    });

    btnNewChat?.addEventListener('click', () => {
        setConversationId('');
        messageInput.value = '';
        if (emptyState) emptyState.style.display = '';
        chatMessages.querySelectorAll('.message').forEach(m => m.remove());
        window.location.href = '/chat';
    });

    modeRadios?.forEach(r => {
        r.addEventListener('change', () => {
            const mode = r.value;
            if (modeDocumentSelect) modeDocumentSelect.style.display = mode === 'document' ? 'inline-block' : 'none';
            if (notesPanel) notesPanel.style.display = mode === 'notes' ? 'block' : 'none';
        });
    });

    if (selectDocument) {
        selectDocument.addEventListener('change', () => {
            if (getConversationId()) setConversationId('');
        });
    }

    btnApplyNotes?.addEventListener('click', async () => {
        const notes = notesContext?.value?.trim();
        if (!notes) {
            alert('Please paste some notes first');
            return;
        }
        const formData = new FormData();
        formData.append('title', 'Notes Chat');
        formData.append('mode', 'notes');
        formData.append('notes_context', notes);
        try {
            const resp = await fetch('/chat/new', {
                method: 'POST',
                body: formData,
                credentials: 'include',
                headers: { Accept: 'application/json' },
            });
            const data = await resp.json().catch(() => ({}));
            const cid = data.conversation_id;
            if (cid) {
                window.location.href = `/chat?conv_id=${cid}`;
            } else {
                window.location.href = '/chat';
            }
        } catch (e) {
            alert('Failed to start chat: ' + (e.message || 'Unknown error'));
        }
    });

    document.querySelectorAll('.tool-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tool = btn.dataset.tool;
            if (tool === 'explain') showToolModal('explain', 'Explain Step-by-Step', 'Enter topic or question...');
            else callTool(tool);
        });
    });

    if (getCurrentMode() === 'document') modeDocumentSelect.style.display = 'inline-block';
    if (getCurrentMode() === 'notes') notesPanel.style.display = 'block';

    messageInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (currentStreamAbortController || currentToolAbortController) {
                e.preventDefault();
                stopGeneration();
            }
            return;
        }
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new SubmitEvent('submit'));
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && (currentStreamAbortController || currentToolAbortController)) {
            e.preventDefault();
            stopGeneration();
        }
    });

    // Auto-resize textarea
    messageInput?.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 200) + 'px';
    });

    // Predicted-questions prefix (must match backend PREDICTED_QUESTIONS_PREFIX)
    const PREDICTED_QUESTIONS_PREFIX = '<!-- PREDICTED_QUESTIONS -->';

    function bindPredictedQuestionsBlock(containerEl) {
        if (!containerEl) return;
        const block = containerEl.querySelector('.predicted-questions-block');
        if (!block) return;
        const convId = getConversationId();
        const messageWrap = containerEl.closest('.message');
        const messageId = (messageWrap && messageWrap.getAttribute('data-message-id')) || '';

        if (convId) {
            const bar = document.createElement('div');
            bar.className = 'pq-download-bar';
            bar.innerHTML = '<span class="text-muted small me-2">Download:</span>' +
                '<a href="/chat/' + convId + '/export?format=pdf" class="btn btn-sm btn-outline-danger" target="_blank" rel="noopener">PDF</a>' +
                '<a href="/chat/' + convId + '/export?format=html" class="btn btn-sm btn-outline-primary" target="_blank" rel="noopener">HTML</a>' +
                '<a href="/chat/' + convId + '/export?format=txt" class="btn btn-sm btn-outline-secondary" target="_blank" rel="noopener">TXT</a>';
            block.insertBefore(bar, block.firstChild);
        }

        const storageKey = 'pq_solved_' + convId + '_' + messageId;
        try {
            const saved = JSON.parse(localStorage.getItem(storageKey) || '[]');
            block.querySelectorAll('.pq-solved-checkbox').forEach(cb => {
                const idx = parseInt(cb.getAttribute('data-index'), 10);
                if (saved.indexOf(idx) !== -1) cb.checked = true;
                cb.addEventListener('change', function() {
                    const checkboxes = block.querySelectorAll('.pq-solved-checkbox');
                    const arr = [];
                    checkboxes.forEach(c => { if (c.checked) arr.push(parseInt(c.getAttribute('data-index'), 10)); });
                    localStorage.setItem(storageKey, JSON.stringify(arr));
                });
            });
        } catch (e) { /* ignore */ }

        block.querySelectorAll('.pq-hint-toggle').forEach(btn => {
            const hintText = btn.parentElement.querySelector('.pq-hint-text');
            if (!hintText) return;
            btn.addEventListener('click', function() {
                const show = hintText.style.display === 'none';
                hintText.style.display = show ? 'block' : 'none';
                btn.textContent = show ? 'Hide hint' : 'Show hint';
            });
        });
    }

    function renderMessageContent(el) {
        let rawContent = el.getAttribute('data-raw-content') || el.textContent || '';
        if (rawContent.indexOf('&lt;!-- PREDICTED_QUESTIONS --&gt;') === 0) {
            rawContent = rawContent.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"');
        }
        if (rawContent.indexOf(PREDICTED_QUESTIONS_PREFIX) === 0) {
            const html = rawContent.split(PREDICTED_QUESTIONS_PREFIX)[1];
            if (html && html.trim()) {
                el.innerHTML = html.trim();
                bindPredictedQuestionsBlock(el);
                return;
            }
        }
        el.innerHTML = renderMarkdown(rawContent);
        addCopyButtons(el);
        highlightCode(el);
    }

    // Initialize: Render existing messages with Markdown or predicted-questions HTML
    document.querySelectorAll('.markdown-content').forEach(el => {
        renderMessageContent(el);
    });
    bindMessageActions(document);
    bindDeleteButtons(document);
    updateClearHistoryButtonVisibility();

    // Clear History modal
    btnClearHistory?.addEventListener('click', function() {
        const cid = getConversationId();
        if (!cid) return;
        const modalEl = document.getElementById('clearHistoryModal');
        if (!modalEl) return;
        const modal = new bootstrap.Modal(modalEl);
        modal.show();
        const confirmBtn = document.getElementById('clearHistoryModalConfirm');
        const once = async function() {
            confirmBtn.removeEventListener('click', once);
            try {
                const r = await fetch('/chat/' + cid + '/clear', { method: 'POST', credentials: 'include' });
                if (!r.ok) {
                    const err = await r.json().catch(() => ({}));
                    alert(err.detail || 'Failed to clear history');
                    return;
                }
                chatMessages.querySelectorAll('.message').forEach(m => m.remove());
                if (emptyState) emptyState.style.display = '';
                modal.hide();
                showToast('Chat history cleared.', 'success');
            } catch (e) {
                alert('Failed to clear history: ' + (e.message || 'Unknown error'));
            }
        };
        confirmBtn.addEventListener('click', once);
        modalEl.addEventListener('hidden.bs.modal', function onHidden() {
            modalEl.removeEventListener('hidden.bs.modal', onHidden);
            confirmBtn.removeEventListener('click', once);
        }, { once: true });
    });
    document.getElementById('clearHistoryModalCancel')?.addEventListener('click', function() {
        bootstrap.Modal.getInstance(document.getElementById('clearHistoryModal'))?.hide();
    });

    // Scroll to bottom on load
    if (chatMessages) {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // Voice-to-AI: Press mic -> listen -> auto-send -> AI responds (no manual send)
    function setupVoiceToAI() {
        const btn = document.getElementById('btnVoiceInput');
        const listeningIndicator = document.getElementById('voiceListeningIndicator');
        if (!btn) return;

        if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            const recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;  // Wait for complete speech only
            recognition.lang = 'en-US';
            recognition.maxAlternatives = 1;

            let isListening = false;

            recognition.onresult = (event) => {
                // Get final transcript (complete speech only)
                const transcript = event.results[event.results.length - 1][0].transcript.trim();
                if (transcript) {
                    // Auto-send to AI after complete speech
                    sendMessage(transcript);
                }
            };

            recognition.onend = () => {
                isListening = false;
                btn.classList.remove('voice-listening');
                btn.innerHTML = '<i class="bi bi-mic"></i>';
                btn.title = 'Speak to AI';
                if (listeningIndicator) listeningIndicator.classList.add('d-none');
            };

            recognition.onerror = (event) => {
                if (event.error !== 'aborted') {
                    console.warn('Speech recognition error:', event.error);
                }
                isListening = false;
                btn.classList.remove('voice-listening');
                btn.innerHTML = '<i class="bi bi-mic"></i>';
                if (listeningIndicator) listeningIndicator.classList.add('d-none');
            };

            btn.onclick = () => {
                if (isListening) {
                    recognition.abort();
                    return;
                }
                try {
                    recognition.start();
                    isListening = true;
                    btn.classList.add('voice-listening');
                    btn.innerHTML = '<i class="bi bi-mic-fill"></i>';
                    btn.title = 'Listening... Click to stop';
                    if (listeningIndicator) listeningIndicator.classList.remove('d-none');
                } catch (e) {
                    console.warn('Speech recognition start failed:', e);
                }
            };
        } else {
            btn.style.display = 'none';
        }
    }

    setupVoiceToAI();

    window.sendMessageFromChat = sendMessage;

    var sidebarEl = document.getElementById('chatSidebar');
    var sidebarToggle = document.getElementById('sidebarToggle');
    var sidebarOverlay = document.getElementById('sidebarOverlay');
    if (sidebarToggle && sidebarEl) {
        sidebarToggle.addEventListener('click', function() {
            sidebarEl.classList.toggle('open');
            if (sidebarOverlay) {
                sidebarOverlay.classList.toggle('show');
                sidebarOverlay.setAttribute('aria-hidden', sidebarEl.classList.contains('open') ? 'false' : 'true');
            }
        });
    }
    if (sidebarOverlay && sidebarEl) {
        sidebarOverlay.addEventListener('click', function() {
            sidebarEl.classList.remove('open');
            sidebarOverlay.classList.remove('show');
            sidebarOverlay.setAttribute('aria-hidden', 'true');
        });
    }
})();
