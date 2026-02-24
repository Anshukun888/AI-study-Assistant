(function() {
    var groupId = window.GROUP_ID;
    var groupName = window.GROUP_NAME || '';
    var currentUserId = window.CURRENT_USER_ID;
    var currentUsername = window.CURRENT_USERNAME || 'You';
    var pinnedMessageId = window.PINNED_MESSAGE_ID || null;
    var maxUploadSizeMb = window.MAX_UPLOAD_SIZE_MB || 50;
    var ws = null;
    var messagesContainer = document.getElementById('groupChatMessages');
    var messageInput = document.getElementById('groupMessageInput');
    var groupChatForm = document.getElementById('groupChatForm');
    var onlineUsers = [];
    var typingTimeout = null;
    var currentGroupRequestId = null;
    var groupStreamingRequestId = null;
    var groupStreamingWrap = null;
    var groupStreamingEl = null;
    var btnGroupSend = document.getElementById('btnGroupSend');
    var scrollEl = null;
    var userScrolledUp = false;
    var scrollThreshold = 80;
    var selectedGroupFileId = null;

    if (typeof marked !== 'undefined') {
        marked.setOptions({ breaks: true, gfm: true, headerIds: false, mangle: false });
    }

    var groupChatSidebar = document.getElementById('groupChatSidebar');
    var groupChatSidebarToggle = document.getElementById('groupChatSidebarToggle');
    var groupChatSidebarOverlay = document.getElementById('groupChatSidebarOverlay');
    if (groupChatSidebarToggle && groupChatSidebar) {
        groupChatSidebarToggle.addEventListener('click', function() {
            groupChatSidebar.classList.toggle('open');
            if (groupChatSidebarOverlay) {
                groupChatSidebarOverlay.classList.toggle('show');
                groupChatSidebarOverlay.setAttribute('aria-hidden', groupChatSidebar.classList.contains('open') ? 'false' : 'true');
            }
        });
    }
    if (groupChatSidebarOverlay) {
        groupChatSidebarOverlay.addEventListener('click', function() {
            if (groupChatSidebar) groupChatSidebar.classList.remove('open');
            groupChatSidebarOverlay.classList.remove('show');
            groupChatSidebarOverlay.setAttribute('aria-hidden', 'true');
        });
    }

    function showToast(message, type) {
        type = type || 'info';
        var container = document.getElementById('alertToastContainer');
        if (!container) return;
        var toast = document.createElement('div');
        toast.className = 'toast align-items-center text-bg-' + type + ' border-0 show';
        toast.setAttribute('role', 'alert');
        toast.innerHTML = '<div class="d-flex"><div class="toast-body">' + escapeHtml(message) + '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
        container.appendChild(toast);
        var bsToast = new bootstrap.Toast(toast, { delay: 4000 });
        bsToast.show();
        toast.addEventListener('hidden.bs.toast', function() { toast.remove(); });
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    function renderMarkdown(content) {
        if (!content) return '';
        if (typeof marked === 'undefined') return escapeHtml(content).replace(/\n/g, '<br>');
        try {
            return marked.parse(content);
        } catch (e) {
            console.error('Markdown parse error:', e);
            return escapeHtml(content).replace(/\n/g, '<br>');
        }
    }

    function highlightCode(container) {
        if (!container || typeof Prism === 'undefined') return;
        container.querySelectorAll('pre code').forEach(function(block) {
            try { Prism.highlightElement(block); } catch (e) {}
        });
    }

    function addCopyButtonsToContainer(container) {
        if (!container) return;
        container.querySelectorAll('pre code').forEach(function(codeBlock) {
            var pre = codeBlock.parentElement;
            if (!pre || pre.querySelector('.copy-code-btn')) return;
            var copyBtn = document.createElement('button');
            copyBtn.className = 'copy-code-btn btn btn-sm';
            copyBtn.innerHTML = '<i class="bi bi-clipboard"></i>';
            copyBtn.title = 'Copy code';
            copyBtn.onclick = function() {
                var text = (codeBlock.textContent || codeBlock.innerText || '').trim();
                navigator.clipboard.writeText(text).then(function() {
                    copyBtn.innerHTML = '<i class="bi bi-check"></i>';
                    copyBtn.classList.add('copied');
                    setTimeout(function() {
                        copyBtn.innerHTML = '<i class="bi bi-clipboard"></i>';
                        copyBtn.classList.remove('copied');
                    }, 2000);
                }).catch(function(err) {
                    console.error('Copy failed:', err);
                    showToast('Copy failed', 'danger');
                });
            };
            pre.style.position = 'relative';
            pre.appendChild(copyBtn);
        });
    }

    function renderMessage(m, isPinned) {
        var isUser = m.user_id === currentUserId;
        var isAi = m.message_type === 'ai' || m.sender_type === 'ai';
        var isFileMsg = m.message_type === 'file' && m.file_name;
        var canEdit = isUser && !isAi && !isFileMsg;
        var bubbleClass = isAi ? 'message-assistant' : (isUser ? 'message-user' : 'message-other');
        var icon = isAi ? 'bi-robot' : 'bi-person-circle';
        var rawMessage = (m.message || '').trim();
        var bodyHtml;
        if (isFileMsg) {
            bodyHtml = '<a href="/uploads/' + escapeHtml(m.file_path || '') + '" target="_blank" class="btn btn-sm btn-outline-primary"><i class="bi bi-file-earmark"></i> ' + escapeHtml(m.file_name) + '</a>';
        } else if (isAi) {
            bodyHtml = renderMarkdown(rawMessage);
        } else {
            bodyHtml = escapeHtml(rawMessage);
        }
        var timeStr = (m.created_at && formatTime(m.created_at)) || '';
        var editedStr = (m.updated_at) ? ' <span class="message-edited text-muted small">(edited)</span>' : '';
        var metaHtml = '<div class="message-meta d-flex align-items-center flex-wrap gap-1 mt-1">' +
            (timeStr ? '<span class="message-time text-muted small">' + escapeHtml(timeStr) + '</span>' : '') + editedStr + '</div>';
        var voteCount = (typeof m.vote_count !== 'undefined' ? m.vote_count : 0);
        var voteHtml = (m.message_type !== 'file')
            ? '<div class="message-vote mt-1"><button type="button" class="btn btn-sm btn-link text-muted p-0 vote-btn" data-message-id="' + m.id + '" title="Upvote"><i class="bi bi-hand-thumbs-up"></i> <span class="vote-count">' + voteCount + '</span></button></div>'
            : '';
        var solvedStorageKey = 'group_solved_' + groupId + '_' + m.id;
        var isSolved = false;
        try { isSolved = localStorage.getItem(solvedStorageKey) === '1'; } catch (e) {}
        var solvedHtml = '<div class="message-solved-wrap mt-1"></div>';
        var editBtnHtml = canEdit ? '<button type="button" class="btn btn-sm btn-link text-muted group-edit-message-btn" data-message-id="' + m.id + '" title="Edit message"><i class="bi bi-pencil"></i></button>' : '';
        var div = document.createElement('div');
        div.className = 'message ' + bubbleClass + (isPinned ? ' border-start border-primary border-3' : '');
        div.dataset.messageId = m.id;
        div.innerHTML = '<div class="message-avatar"><i class="bi ' + icon + '"></i></div><div class="message-content">' +
            '<div class="message-actions d-flex gap-1 align-items-center flex-wrap">' + editBtnHtml + '</div>' +
            '<div class="message-text markdown-content" data-raw-content="' + escapeHtml(rawMessage) + '">' + bodyHtml + '</div>' +
            metaHtml + voteHtml + solvedHtml + '</div>';
        addCopyButtonsToContainer(div);
        highlightCode(div);
        var editBtn = div.querySelector('.group-edit-message-btn');
        if (editBtn) {
            editBtn.addEventListener('click', function() {
                openEditMessageModal(parseInt(this.dataset.messageId, 10));
            });
        }
        if (!isAi) {
            var actions = div.querySelector('.message-actions');
            var pinBtn = document.createElement('button');
            pinBtn.type = 'button';
            pinBtn.className = 'btn btn-sm btn-link text-muted pin-btn';
            pinBtn.dataset.messageId = m.id;
            pinBtn.title = 'Pin message';
            pinBtn.innerHTML = '<i class="bi bi-pin-angle"></i>';
            actions.appendChild(pinBtn);
        }
        var voteBtn = div.querySelector('.vote-btn');
        if (voteBtn) {
            voteBtn.addEventListener('click', function() { toggleVote(parseInt(this.dataset.messageId, 10)); });
        }
        var pinBtn = div.querySelector('.pin-btn');
        if (pinBtn) {
            pinBtn.addEventListener('click', function() { pinMessage(parseInt(this.dataset.messageId, 10)); });
        }
        var solvedWrap = div.querySelector('.message-solved-wrap');
        if (solvedWrap) {
            var solvedBtn = document.createElement('button');
            solvedBtn.type = 'button';
            solvedBtn.className = 'btn btn-sm btn-link text-muted p-0 solved-btn';
            solvedBtn.dataset.messageId = m.id;
            solvedBtn.title = 'Mark as solved';
            solvedBtn.innerHTML = isSolved ? '<i class="bi bi-check-circle-fill text-success me-1"></i><span class="solved-label">Solved</span>' : '<i class="bi bi-check-circle me-1"></i><span class="solved-label">Mark as solved</span>';
            solvedBtn.addEventListener('click', function() {
                var mid = parseInt(this.dataset.messageId, 10);
                var key = 'group_solved_' + groupId + '_' + mid;
                try {
                    var now = localStorage.getItem(key) === '1';
                    localStorage.setItem(key, now ? '0' : '1');
                    this.innerHTML = now ? '<i class="bi bi-check-circle me-1"></i><span class="solved-label">Mark as solved</span>' : '<i class="bi bi-check-circle-fill text-success me-1"></i><span class="solved-label">Solved</span>';
                    showToast(now ? 'Unmarked as solved' : 'Marked as solved', 'success');
                } catch (e) {}
            });
            solvedWrap.appendChild(solvedBtn);
        }
        return div;
    }

    function formatTime(iso) {
        try {
            var d = new Date(iso);
            var now = new Date();
            if (d.toDateString() === now.toDateString()) {
                return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            }
            return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch (e) { return iso; }
    }

    function showNewMessagesBadge() {
        var badge = document.getElementById('groupNewMessagesBadge');
        if (badge) badge.classList.remove('d-none');
    }
    function hideNewMessagesBadge() {
        var badge = document.getElementById('groupNewMessagesBadge');
        if (badge) badge.classList.add('d-none');
    }

    function appendMessage(m, skipNotification) {
        var isPinned = pinnedMessageId && m.id === pinnedMessageId;
        var el = renderMessage(m, isPinned);
        var loading = document.getElementById('messagesLoading');
        if (loading) loading.remove();
        messagesContainer.appendChild(el);
        if (!skipNotification) {
            var isFromMe = m.user_id === currentUserId;
            if (!isFromMe || m.message_type === 'ai' || m.sender_type === 'ai') showNewMessagesBadge();
        }
        if (!scrollEl) scrollEl = document.querySelector('.group-chat-container .chat-messages') || messagesContainer.closest('.chat-messages');
        if (scrollEl && messagesContainer.lastChild === el) {
            var atBottom = scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight <= scrollThreshold;
            if (!userScrolledUp || atBottom) el.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
    }

    function getMaxMessageId() {
        var max = 0;
        if (messagesContainer) {
            messagesContainer.querySelectorAll('[data-message-id]').forEach(function(el) {
                var id = parseInt(el.getAttribute('data-message-id'), 10);
                if (id && id > max) max = id;
            });
        }
        return max;
    }

    function markGroupAsRead() {
        try {
            var maxId = getMaxMessageId();
            if (maxId > 0) localStorage.setItem('group_read_' + groupId, String(maxId));
        } catch (e) {}
    }

    function loadMessages() {
        fetch('/groups/' + groupId + '/messages?limit=100&offset=0', { credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var loading = document.getElementById('messagesLoading');
                if (loading) loading.remove();
                (data.messages || []).forEach(function(m) { appendMessage(m, true); });
                if (data.pinned_message_id) {
                    pinnedMessageId = data.pinned_message_id;
                    var wrap = document.getElementById('pinnedMessageWrap');
                    var content = document.getElementById('pinnedMessageContent');
                    var pinnedEl = messagesContainer.querySelector('[data-message-id="' + data.pinned_message_id + '"]');
                    if (pinnedEl && wrap && content) {
                        content.textContent = pinnedEl.querySelector('.message-text') ? pinnedEl.querySelector('.message-text').textContent.slice(0, 200) : '';
                        wrap.classList.remove('d-none');
                    }
                }
                markGroupAsRead();
            })
            .catch(function() {
                var loading = document.getElementById('messagesLoading');
                if (loading) loading.textContent = 'Failed to load messages.';
            });
    }

    function updateOnlineList(users) {
        onlineUsers = users || [];
        var el = document.getElementById('groupOnlineList');
        if (!el) return;
        if (onlineUsers.length === 0) {
            el.innerHTML = '<span class="text-muted">No one online</span>';
            return;
        }
        el.innerHTML = '<span class="text-success small"><i class="bi bi-circle-fill me-1"></i>' + onlineUsers.length + ' online</span><ul class="list-unstyled mt-1 mb-0">' +
            onlineUsers.map(function(u) {
                return '<li class="d-flex align-items-center gap-1"><i class="bi bi-circle-fill text-success" style="font-size:0.5rem;"></i> ' + escapeHtml(u.username || '') + '</li>';
            }).join('') + '</ul>';
    }

    function showTyping(username) {
        var wrap = document.getElementById('typingIndicatorWrap');
        if (!wrap) return;
        var el = document.getElementById('typingIndicatorText');
        var displayName = (username && username !== 'Someone') ? username : 'User';
        if (el) el.textContent = displayName + ' is typing…';
        wrap.classList.remove('d-none');
        clearTimeout(window._typingHide);
        window._typingHide = setTimeout(function() { if (wrap) wrap.classList.add('d-none'); }, 3000);
    }

    function updateMessageStatus(messageId, status) {
        /* Status updates (e.g. delivered) no longer shown in minimal message UI */
    }

    function connectWs() {
        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var url = protocol + '//' + window.location.host + '/ws/groups/' + groupId;
        ws = new WebSocket(url);
        ws.onopen = function() { showToast('Connected', 'success'); };
        ws.onclose = function() { showToast('Disconnected. Reconnecting...', 'warning'); setTimeout(connectWs, 3000); };
        ws.onerror = function() {};
        ws.onmessage = function(ev) {
            try {
                var data = JSON.parse(ev.data);
                if (data.type === 'message') {
                    if (groupStreamingWrap && (data.sender_type === 'ai' || data.message_type === 'ai')) {
                        groupStreamingWrap.remove();
                        groupStreamingWrap = null;
                        groupStreamingEl = null;
                        groupStreamingRequestId = null;
                    }
                    appendMessage(data);
                    if (data.id && currentUserId && data.user_id === currentUserId) {
                        ws.send(JSON.stringify({ type: 'delivery_ack', message_id: data.id }));
                    }
                    if (data.sender_type === 'ai' || data.message_type === 'ai') {
                        clearGroupStopState();
                    }
                    var atBottom = scrollEl && (scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < scrollThreshold);
                    if (atBottom || (data.user_id === currentUserId)) markGroupAsRead();
                } else if (data.type === 'ai_chunk') {
                    if (data.request_id !== groupStreamingRequestId) return;
                    if (!groupStreamingWrap) {
                        groupStreamingWrap = document.createElement('div');
                        groupStreamingWrap.className = 'message message-assistant streaming';
                        groupStreamingWrap.dataset.requestId = data.request_id;
                        groupStreamingWrap.innerHTML = '<div class="message-avatar"><i class="bi bi-robot"></i></div><div class="message-content"><div class="message-text markdown-content"></div></div>';
                        messagesContainer.appendChild(groupStreamingWrap);
                        groupStreamingEl = groupStreamingWrap.querySelector('.message-text');
                    }
                    if (groupStreamingEl) {
                        var cur = groupStreamingEl.getAttribute('data-stream-raw') || '';
                        cur += data.chunk || '';
                        groupStreamingEl.setAttribute('data-stream-raw', cur);
                        groupStreamingEl.innerHTML = renderMarkdown(cur);
                        if (!scrollEl) scrollEl = document.querySelector('.group-chat-container .chat-messages') || messagesContainer.closest('.chat-messages');
                        if (scrollEl && groupStreamingWrap === messagesContainer.lastElementChild) {
                            groupStreamingWrap.scrollIntoView({ behavior: 'smooth', block: 'end' });
                        }
                    }
                } else if (data.type === 'ai_finished') {
                    if (data.request_id === currentGroupRequestId) clearGroupStopState();
                    if (data.request_id === groupStreamingRequestId) {
                        groupStreamingWrap = null;
                        groupStreamingEl = null;
                        groupStreamingRequestId = null;
                    }
                } else if (data.type === 'online') {
                    updateOnlineList(data.users);
                } else if (data.type === 'typing') {
                    if (data.user_id !== currentUserId) showTyping(data.username || 'Someone');
                } else if (data.type === 'message_status') {
                    updateMessageStatus(data.message_id, data.status);
                } else if (data.type === 'ai_started') {
                    groupStreamingRequestId = data.request_id || null;
                    groupStreamingWrap = null;
                    groupStreamingEl = null;
                    if (data.initiated_by === currentUserId) {
                        currentGroupRequestId = data.request_id || null;
                        setGroupSendButtonStop(true);
                    } else if (data.initiated_username) {
                        showToast(data.initiated_username + ' is generating...', 'info');
                    }
                } else if (data.type === 'history_cleared') {
                    clearAllMessagesUI();
                } else if (data.type === 'group_deleted') {
                    showToast('This group was deleted.', 'warning');
                    setTimeout(function() { window.location.href = '/groups/page/list'; }, 1500);
                } else if (data.type === 'member_left') {
                    if (data.username) showToast(data.username + ' left the group', 'info');
                } else if (data.type === 'ai_busy') {
                    showToast(data.message || 'Another member is using the AI. Please wait.', 'warning');
                } else if (data.type === 'message_updated') {
                    if (data.id && data.message !== undefined) {
                        applyMessageUpdate(data.id, data.message, data.updated_at || null);
                    }
                }
            } catch (e) {}
        };
    }

    function setGroupSendButtonStop(isStop) {
        if (!btnGroupSend) return;
        if (isStop) {
            btnGroupSend.innerHTML = '<i class="bi bi-stop-fill"></i>';
            btnGroupSend.title = 'Stop generating';
            btnGroupSend.dataset.stopMode = '1';
        } else {
            btnGroupSend.innerHTML = '<i class="bi bi-send-fill"></i>';
            btnGroupSend.title = 'Send';
            delete btnGroupSend.dataset.stopMode;
        }
    }

    function clearGroupStopState() {
        currentGroupRequestId = null;
        setGroupSendButtonStop(false);
    }

    function stopGroupGeneration() {
        if (currentGroupRequestId) {
            fetch('/ai/cancel/' + currentGroupRequestId, { method: 'POST', credentials: 'include' }).catch(function() {});
            clearGroupStopState();
            showToast('Generation stopped', 'info');
        }
    }

    function clearAllMessagesUI() {
        pinnedMessageId = null;
        var wrap = document.getElementById('pinnedMessageWrap');
        if (wrap) { wrap.classList.add('d-none'); }
        var content = document.getElementById('pinnedMessageContent');
        if (content) content.textContent = '';
        if (messagesContainer) {
            messagesContainer.innerHTML = '';
            var loading = document.createElement('div');
            loading.className = 'text-center py-4 text-muted';
            loading.id = 'messagesLoading';
            loading.textContent = 'No messages yet.';
            messagesContainer.appendChild(loading);
        }
    }

    function sendMessage(content) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'message',
                content: content,
                message_type: 'text',
                file_path: null,
                file_name: null,
                group_file_id: selectedGroupFileId || undefined
            }));
        }
        messageInput.value = '';
    }

    if (btnGroupSend) {
        btnGroupSend.addEventListener('click', function(ev) {
            if (this.dataset.stopMode === '1') {
                ev.preventDefault();
                ev.stopPropagation();
                stopGroupGeneration();
                return false;
            }
        });
    }

    groupChatForm.addEventListener('submit', function(e) {
        if (btnGroupSend && btnGroupSend.dataset.stopMode === '1') {
            e.preventDefault();
            stopGroupGeneration();
            return false;
        }
        e.preventDefault();
        var content = (messageInput.value || '').trim();
        if (!content) return;
        sendMessage(content);
    });

    messageInput.addEventListener('input', function() {
        clearTimeout(typingTimeout);
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'typing' }));
            typingTimeout = setTimeout(function() {}, 2000);
        }
    });

    function pinMessage(messageId) {
        var form = new FormData();
        form.append('message_id', messageId);
        fetch('/groups/' + groupId + '/pin', { method: 'POST', body: form, credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    showToast('Message pinned');
                    var prevPinnedId = pinnedMessageId;
                    pinnedMessageId = messageId;
                    var wrap = document.getElementById('pinnedMessageWrap');
                    var content = document.getElementById('pinnedMessageContent');
                    if (wrap && content) {
                        var newPinnedEl = messagesContainer.querySelector('[data-message-id="' + messageId + '"]');
                        if (newPinnedEl) {
                            var textEl = newPinnedEl.querySelector('.message-text');
                            content.textContent = textEl ? textEl.textContent.slice(0, 200) : '';
                            wrap.classList.remove('d-none');
                        }
                        if (prevPinnedId) {
                            var oldEl = messagesContainer.querySelector('[data-message-id="' + prevPinnedId + '"]');
                            if (oldEl) oldEl.classList.remove('border-start', 'border-primary', 'border-3');
                        }
                        if (newPinnedEl) newPinnedEl.classList.add('border-start', 'border-primary', 'border-3');
                    }
                }
            })
            .catch(function() { showToast('Failed to pin', 'danger'); });
    }

    function toggleVote(messageId) {
        fetch('/groups/' + groupId + '/messages/' + messageId + '/vote', { method: 'POST', credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    var el = messagesContainer.querySelector('[data-message-id="' + messageId + '"] .vote-count');
                    if (el) el.textContent = data.vote_count;
                }
            });
    }

    document.getElementById('btnGroupInsights').addEventListener('click', function() {
        var body = document.getElementById('groupInsightsBody');
        body.innerHTML = '<div class="text-center py-3 text-muted">Loading...</div>';
        var modal = new bootstrap.Modal(document.getElementById('groupInsightsModal'));
        modal.show();
        fetch('/groups/' + groupId + '/insights', { credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var html = '';
                html += '<h6>Most active users</h6><ul class="list-unstyled">';
                (data.most_active_users || []).forEach(function(u) {
                    html += '<li>' + escapeHtml(u.username) + ' — ' + u.message_count + ' messages</li>';
                });
                html += '</ul><h6 class="mt-3">Top discussed topics</h6><ul class="list-unstyled">';
                (data.top_discussed_topics || []).slice(0, 10).forEach(function(t) {
                    html += '<li>' + escapeHtml(t.topic) + ' (' + t.count + ')</li>';
                });
                html += '</ul>';
                if (data.ai_usage_stats && data.ai_usage_stats.ai_message_count != null) {
                    html += '<h6 class="mt-3">AI usage</h6><p class="mb-0">' + data.ai_usage_stats.ai_message_count + ' AI responses in this group.</p>';
                }
                body.innerHTML = html;
            })
            .catch(function() { body.innerHTML = '<p class="text-danger">Failed to load insights.</p>'; });
    });

    function loadFiles() {
        var el = document.getElementById('groupFilesList');
        if (!el) return;
        fetch('/groups/' + groupId + '/files', { credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var files = data.files || [];
                if (files.length === 0) {
                    el.innerHTML = '<span class="text-muted">No files</span>';
                    return;
                }
                el.innerHTML = '<ul class="list-unstyled mb-0">' + files.map(function(f) {
                    var canDelete = (f.uploaded_by != null && f.uploaded_by === currentUserId);
                    var deleteBtn = canDelete
                        ? ' <button type="button" class="btn btn-sm btn-link text-danger p-0 group-delete-file-btn" data-file-id="' + f.id + '" data-file-name="' + escapeHtml(f.file_name) + '" title="Delete file" aria-label="Delete file"><i class="bi bi-trash"></i></button>'
                        : '';
                    var useBtn = ' <button type="button" class="btn btn-sm btn-link text-primary p-0 group-use-file-btn" data-file-id="' + f.id + '" data-file-name="' + escapeHtml(f.file_name) + '" title="Use for AI context"><i class="bi bi-robot"></i></button>';
                    return '<li class="d-flex align-items-center gap-1 py-1">' +
                        '<a href="/uploads/' + escapeHtml(f.file_path || '') + '" target="_blank" class="small text-truncate flex-grow-1" title="' + escapeHtml(f.file_name) + '">' + escapeHtml(f.file_name) + '</a>' +
                        useBtn + deleteBtn + '</li>';
                }).join('') + '</ul>';
                el.querySelectorAll('.group-delete-file-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        showDeleteFileModal(parseInt(this.dataset.fileId, 10), this.dataset.fileName || '');
                    });
                });
                el.querySelectorAll('.group-use-file-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        setUsingFile(parseInt(this.dataset.fileId, 10), this.dataset.fileName || '');
                    });
                });
            })
            .catch(function() { el.innerHTML = '<span class="text-muted">Failed to load</span>'; });
    }

    function setUsingFile(fileId, fileName) {
        selectedGroupFileId = fileId;
        var wrap = document.getElementById('groupUsingFileWrap');
        var nameEl = document.getElementById('groupUsingFileName');
        if (wrap && nameEl) {
            nameEl.textContent = fileName;
            wrap.classList.remove('d-none');
        }
    }
    function clearUsingFile() {
        selectedGroupFileId = null;
        var wrap = document.getElementById('groupUsingFileWrap');
        var nameEl = document.getElementById('groupUsingFileName');
        if (wrap && nameEl) {
            nameEl.textContent = '';
            wrap.classList.add('d-none');
        }
    }
    if (document.getElementById('groupClearUsingFile')) {
        document.getElementById('groupClearUsingFile').addEventListener('click', clearUsingFile);
    }

    var groupDeleteFileModalFileId = null;
    function showDeleteFileModal(fileId, fileName) {
        groupDeleteFileModalFileId = fileId;
        var modal = document.getElementById('groupDeleteFileModal');
        if (modal) {
            var bsModal = new bootstrap.Modal(modal);
            bsModal.show();
        }
    }
    function hideDeleteFileModal() {
        groupDeleteFileModalFileId = null;
        var modal = document.getElementById('groupDeleteFileModal');
        if (modal) {
            var bs = bootstrap.Modal.getInstance(modal);
            if (bs) bs.hide();
        }
    }
    function confirmDeleteGroupFile() {
        if (groupDeleteFileModalFileId == null) return;
        var fileId = groupDeleteFileModalFileId;
        hideDeleteFileModal();
        fetch('/groups/' + groupId + '/files/' + fileId, { method: 'DELETE', credentials: 'include' })
            .then(function(r) {
                if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed to delete'); });
                return r.json();
            })
            .then(function() {
                loadFiles();
                showToast('File deleted.', 'success');
            })
            .catch(function(e) {
                showToast(e.message || 'Failed to delete file', 'danger');
            });
    }
    document.getElementById('groupDeleteFileModalCancel') && document.getElementById('groupDeleteFileModalCancel').addEventListener('click', hideDeleteFileModal);
    document.getElementById('groupDeleteFileModalConfirm') && document.getElementById('groupDeleteFileModalConfirm').addEventListener('click', confirmDeleteGroupFile);

    var ALLOWED_GROUP_EXT = /\.(pdf|png|jpg|jpeg|docx)$/i;
    function validateGroupFile(file) {
        if (!file.name) return 'Invalid file';
        if (!ALLOWED_GROUP_EXT.test(file.name)) return 'Only PDF, DOCX, and images (PNG, JPG) are allowed.';
        var maxBytes = (maxUploadSizeMb || 50) * 1024 * 1024;
        if (file.size > maxBytes) return 'File too large (max ' + (maxUploadSizeMb || 50) + ' MB).';
        return null;
    }
    function uploadGroupFile(file, onProgress, onSuccess, onError) {
        var fd = new FormData();
        fd.append('file', file, file.name || 'file');
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/groups/' + groupId + '/upload');
        xhr.withCredentials = true;
        xhr.upload.addEventListener('progress', function(e) {
            if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
        });
        xhr.onload = function() {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data.document_id && data.file_name) {
                        onSuccess(data.document_id, data.file_name);
                    } else {
                        onError('Invalid response');
                    }
                } catch (err) {
                    onError('Invalid response');
                }
            } else {
                try {
                    var err = JSON.parse(xhr.responseText);
                    onError(err.detail || 'Upload failed');
                } catch (e) {
                    onError('Upload failed (' + xhr.status + ')');
                }
            }
        };
        xhr.onerror = function() { onError('Network error'); };
        xhr.send(fd);
    }
    function handleGroupFiles(files) {
        if (!files || !files.length) return;
        var list = Array.from(files).filter(function(f) { return f && f.name; });
        if (!list.length) return;
        list.forEach(function(file) {
            var err = validateGroupFile(file);
            if (err) {
                showToast(err, 'danger');
                return;
            }
            var chip = document.createElement('span');
            chip.className = 'attachment-chip badge bg-secondary me-1 mb-1';
            chip.textContent = file.name + ' …';
            var preview = document.getElementById('groupAttachmentPreview');
            if (preview) {
                preview.style.display = 'block';
                preview.appendChild(chip);
            }
            uploadGroupFile(
                file,
                function(pct) { chip.textContent = file.name + ' ' + pct + '%'; },
                function(docId, fileName) {
                    chip.textContent = file.name;
                    chip.classList.remove('bg-secondary');
                    chip.classList.add('bg-success');
                    showToast('Uploaded: ' + fileName, 'success');
                    loadFiles();
                    setUsingFile(docId, fileName);
                    setTimeout(function() {
                        chip.remove();
                        if (preview && !preview.children.length) preview.style.display = 'none';
                    }, 2000);
                },
                function(msg) {
                    chip.classList.remove('bg-secondary');
                    chip.classList.add('bg-danger');
                    chip.textContent = file.name + ' failed';
                    showToast(msg, 'danger');
                    setTimeout(function() {
                        chip.remove();
                        if (preview && !preview.children.length) preview.style.display = 'none';
                    }, 3000);
                }
            );
        });
    }
    var groupFileInput = document.getElementById('groupFileInput');
    if (groupFileInput) {
        groupFileInput.addEventListener('change', function() {
            handleGroupFiles(this.files);
            this.value = '';
        });
    }
    var groupAttachFileInput = document.getElementById('groupAttachFileInput');
    if (groupAttachFileInput) {
        groupAttachFileInput.addEventListener('change', function() {
            handleGroupFiles(this.files);
            this.value = '';
        });
    }
    var groupInputWrapper = document.getElementById('groupInputWrapper');
    if (groupInputWrapper) {
        groupInputWrapper.addEventListener('dragover', function(e) {
            e.preventDefault();
            e.stopPropagation();
            this.classList.add('drag-over');
        });
        groupInputWrapper.addEventListener('dragleave', function(e) {
            e.preventDefault();
            e.stopPropagation();
            this.classList.remove('drag-over');
        });
        groupInputWrapper.addEventListener('drop', function(e) {
            e.preventDefault();
            e.stopPropagation();
            this.classList.remove('drag-over');
            handleGroupFiles(e.dataTransfer && e.dataTransfer.files);
        });
    }

    var groupEditMessageId = null;
    function openEditMessageModal(messageId) {
        var msgEl = messagesContainer.querySelector('[data-message-id="' + messageId + '"]');
        if (!msgEl) return;
        var textEl = msgEl.querySelector('.message-text');
        var raw = (textEl && (textEl.getAttribute('data-raw-content') || textEl.textContent)) || '';
        groupEditMessageId = messageId;
        var input = document.getElementById('groupEditMessageInput');
        if (input) input.value = raw.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"');
        var modal = document.getElementById('groupEditMessageModal');
        if (modal) {
            var bsModal = new bootstrap.Modal(modal);
            bsModal.show();
        }
    }
    function hideEditMessageModal() {
        groupEditMessageId = null;
        var modal = document.getElementById('groupEditMessageModal');
        if (modal) {
            var bs = bootstrap.Modal.getInstance(modal);
            if (bs) bs.hide();
        }
    }
    function saveEditGroupMessage() {
        if (groupEditMessageId == null) return;
        var messageId = groupEditMessageId;
        var input = document.getElementById('groupEditMessageInput');
        var newContent = (input && input.value || '').trim();
        if (!newContent) {
            showToast('Message cannot be empty', 'warning');
            return;
        }
        hideEditMessageModal();
        var form = new FormData();
        form.append('content', newContent);
        fetch('/groups/' + groupId + '/messages/' + messageId + '/edit', { method: 'POST', body: form, credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    applyMessageUpdate(messageId, data.message, data.updated_at);
                    showToast('Message updated', 'success');
                } else {
                    showToast('Failed to update message', 'danger');
                }
            })
            .catch(function() {
                showToast('Failed to update message', 'danger');
            });
    }
    function applyMessageUpdate(messageId, newMessage, updatedAt) {
        var msgEl = messagesContainer.querySelector('[data-message-id="' + messageId + '"]');
        if (!msgEl) return;
        var textEl = msgEl.querySelector('.message-text');
        if (textEl) {
            textEl.setAttribute('data-raw-content', escapeHtml(newMessage));
            textEl.innerHTML = escapeHtml(newMessage);
        }
        var meta = msgEl.querySelector('.message-meta');
        if (meta) {
            var timeSpan = meta.querySelector('.message-time');
            var editedSpan = meta.querySelector('.message-edited');
            if (!editedSpan) {
                var ed = document.createElement('span');
                ed.className = 'message-edited text-muted small';
                ed.textContent = ' (edited)';
                meta.appendChild(ed);
            }
        }
    }
    document.getElementById('groupEditMessageModalCancel') && document.getElementById('groupEditMessageModalCancel').addEventListener('click', hideEditMessageModal);
    document.getElementById('groupEditMessageModalSave') && document.getElementById('groupEditMessageModalSave').addEventListener('click', saveEditGroupMessage);

    document.querySelectorAll('.ai-quick-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var prefix = this.getAttribute('data-prefix') || '@ai ';
            messageInput.value = prefix;
            messageInput.focus();
        });
    });

    if (document.getElementById('btnGroupStudyPlan')) {
        document.getElementById('btnGroupStudyPlan').addEventListener('click', function() {
            var modal = document.getElementById('groupStudyPlanModal');
            if (modal) {
                document.getElementById('groupStudyPlanTopic').value = '';
                document.getElementById('groupStudyPlanType').value = 'weekly';
                new bootstrap.Modal(modal).show();
            }
        });
    }
    if (document.getElementById('btnGroupCreateStudyPlan')) {
        document.getElementById('btnGroupCreateStudyPlan').addEventListener('click', function() {
            var topic = (document.getElementById('groupStudyPlanTopic') && document.getElementById('groupStudyPlanTopic').value || '').trim();
            var planType = (document.getElementById('groupStudyPlanType') && document.getElementById('groupStudyPlanType').value) || 'weekly';
            if (!topic) {
                showToast('Please enter a topic', 'warning');
                return;
            }
            var modalEl = document.getElementById('groupStudyPlanModal');
            if (modalEl) bootstrap.Modal.getInstance(modalEl).hide();
            if (typeof window.createStudyPlan === 'function') {
                window.createStudyPlan(topic, planType, null);
            }
        });
    }

    var btnGroupClearHistory = document.getElementById('btnGroupClearHistory');
    var groupClearHistoryModal = document.getElementById('groupClearHistoryModal');
    if (btnGroupClearHistory && groupClearHistoryModal) {
        btnGroupClearHistory.addEventListener('click', function() {
            var modal = new bootstrap.Modal(groupClearHistoryModal);
            modal.show();
        });
        document.getElementById('groupClearHistoryModalConfirm').addEventListener('click', function() {
            fetch('/groups/' + groupId + '/clear', { method: 'POST', credentials: 'include' })
                .then(function(r) {
                    if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed to clear'); });
                    return r.json();
                })
                .then(function() {
                    clearAllMessagesUI();
                    bootstrap.Modal.getInstance(groupClearHistoryModal).hide();
                    showToast('Group chat history cleared.', 'success');
                })
                .catch(function(e) {
                    showToast(e.message || 'Failed to clear history', 'danger');
                });
        });
        document.getElementById('groupClearHistoryModalCancel').addEventListener('click', function() {
            bootstrap.Modal.getInstance(groupClearHistoryModal).hide();
        });
    }

    var btnGroupLeave = document.getElementById('btnGroupLeave');
    var groupLeaveModal = document.getElementById('groupLeaveModal');
    if (btnGroupLeave && groupLeaveModal) {
        btnGroupLeave.addEventListener('click', function() {
            var modal = new bootstrap.Modal(groupLeaveModal);
            modal.show();
        });
        document.getElementById('groupLeaveModalConfirm').addEventListener('click', function() {
            bootstrap.Modal.getInstance(groupLeaveModal).hide();
            fetch('/groups/' + groupId + '/leave', { method: 'POST', credentials: 'include', headers: { 'Accept': 'text/html' } })
                .then(function(r) {
                    if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed'); });
                    window.location.href = '/groups/page/list';
                })
                .catch(function(e) {
                    showToast(e.message || 'Failed to leave', 'danger');
                });
        });
        document.getElementById('groupLeaveModalCancel').addEventListener('click', function() { bootstrap.Modal.getInstance(groupLeaveModal).hide(); });
    }

    var btnGroupDelete = document.getElementById('btnGroupDelete');
    var groupDeleteModal = document.getElementById('groupDeleteModal');
    if (btnGroupDelete && groupDeleteModal) {
        btnGroupDelete.addEventListener('click', function() {
            var modal = new bootstrap.Modal(groupDeleteModal);
            modal.show();
        });
        document.getElementById('groupDeleteModalConfirm').addEventListener('click', function() {
            bootstrap.Modal.getInstance(groupDeleteModal).hide();
            fetch('/groups/' + groupId + '/delete', { method: 'POST', credentials: 'include', headers: { 'Accept': 'text/html' } })
                .then(function(r) {
                    if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed'); });
                    window.location.href = '/groups/page/list';
                })
                .catch(function(e) {
                    showToast(e.message || 'Failed to delete group', 'danger');
                });
        });
        document.getElementById('groupDeleteModalCancel').addEventListener('click', function() { bootstrap.Modal.getInstance(groupDeleteModal).hide(); });
    }

    if (document.getElementById('btnGroupInvite')) {
        document.getElementById('btnGroupInvite').addEventListener('click', function() {
            fetch('/groups/' + groupId + '/invite', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'expires_days=7',
                credentials: 'include'
            })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.invite_url) {
                        navigator.clipboard.writeText(data.invite_url).then(function() {
                            showToast('Invite link copied to clipboard', 'success');
                        }).catch(function() {
                            prompt('Copy this invite link:', data.invite_url);
                        });
                    }
                })
                .catch(function() { showToast('Failed to create invite', 'danger'); });
        });
    }

    scrollEl = document.querySelector('.group-chat-container .chat-messages');
    if (scrollEl) {
        scrollEl.addEventListener('scroll', function() {
            var atBottom = scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < scrollThreshold;
            userScrolledUp = !atBottom;
            if (atBottom) {
                hideNewMessagesBadge();
                markGroupAsRead();
            }
        });
    }
    if (messageInput) {
        messageInput.addEventListener('focus', function() {
            hideNewMessagesBadge();
            markGroupAsRead();
        });
    }

    function setupGroupVoiceInput() {
        var btn = document.getElementById('btnGroupVoiceInput');
        if (!btn) return;
        if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
            var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            var recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = 'en-US';
            var isListening = false;
            recognition.onresult = function(event) {
                var transcript = event.results[event.results.length - 1][0].transcript.trim();
                if (transcript && messageInput) {
                    messageInput.value = (messageInput.value ? messageInput.value + ' ' : '') + transcript;
                }
            };
            recognition.onend = function() {
                isListening = false;
                btn.classList.remove('voice-listening');
                btn.innerHTML = '<i class="bi bi-mic"></i>';
                btn.title = 'Tap to speak';
            };
            recognition.onerror = function() {
                isListening = false;
                btn.classList.remove('voice-listening');
                btn.innerHTML = '<i class="bi bi-mic"></i>';
            };
            btn.onclick = function() {
                if (isListening) {
                    recognition.abort();
                    return;
                }
                try {
                    recognition.start();
                    isListening = true;
                    btn.classList.add('voice-listening');
                    btn.innerHTML = '<i class="bi bi-mic-fill"></i>';
                    btn.title = 'Listening...';
                } catch (e) {}
            };
        } else {
            btn.style.display = 'none';
        }
    }
    setupGroupVoiceInput();

    loadMessages();
    loadFiles();
    connectWs();
})();
