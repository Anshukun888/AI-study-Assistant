(function() {
    var groupId = window.GROUP_ID;
    var groupName = window.GROUP_NAME || '';
    var currentUserId = window.CURRENT_USER_ID;
    var currentUsername = window.CURRENT_USERNAME || 'You';
    var pinnedMessageId = window.PINNED_MESSAGE_ID || null;
    var ws = null;
    var messagesContainer = document.getElementById('groupChatMessages');
    var messageInput = document.getElementById('groupMessageInput');
    var groupChatForm = document.getElementById('groupChatForm');
    var groupFileInput = document.getElementById('groupFileInput');
    var attachmentPreview = document.getElementById('groupAttachmentPreview');
    var pendingFile = null;
    var onlineUsers = [];
    var selectedGroupFileId = null;
    var typingTimeout = null;
    var currentGroupRequestId = null;
    var btnGroupSend = document.getElementById('btnGroupSend');

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

    function renderMessage(m, isPinned) {
        var isUser = m.user_id === currentUserId;
        var isAi = m.message_type === 'ai' || m.sender_type === 'ai';
        var username = m.username || (isAi ? 'AI' : 'User');
        var bubbleClass = isAi ? 'message-assistant' : (isUser ? 'message-user' : 'message-other');
        var icon = isAi ? 'bi-robot' : 'bi-person-circle';
        var statusText = (m.message_status === 'delivered' ? ' ✓✓' : '');
        var div = document.createElement('div');
        div.className = 'message ' + bubbleClass + (isPinned ? ' border-start border-primary border-3' : '');
        div.dataset.messageId = m.id;
        div.innerHTML = '<div class="message-avatar"><i class="bi ' + icon + '"></i></div><div class="message-content">' +
            '<div class="message-meta small text-muted mb-1">' + escapeHtml(username) + (m.created_at ? ' · ' + formatTime(m.created_at) : '') + (statusText) + '</div>' +
            '<div class="message-actions d-flex gap-1 align-items-center flex-wrap"></div>' +
            '<div class="message-text markdown-content">' + (m.message_type === 'file' && m.file_name
                ? '<a href="/uploads/' + escapeHtml(m.file_path || '') + '" target="_blank" class="btn btn-sm btn-outline-primary"><i class="bi bi-file-earmark"></i> ' + escapeHtml(m.file_name) + '</a>'
                : (m.message_type === 'ai' && typeof marked !== 'undefined' ? marked.parse(m.message || '') : escapeHtml(m.message || ''))) + '</div>' +
            (m.message_type !== 'file' && m.message_type !== 'ai' && (typeof m.vote_count !== 'undefined')
                ? '<div class="message-vote mt-1"><button type="button" class="btn btn-sm btn-link text-muted p-0 vote-btn" data-message-id="' + m.id + '" title="Upvote"><i class="bi bi-hand-thumbs-up"></i> <span class="vote-count">' + (m.vote_count || 0) + '</span></button></div>'
                : '') +
            '</div>';
        if (!isAi && username !== 'AI') {
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

    function appendMessage(m) {
        var isPinned = pinnedMessageId && m.id === pinnedMessageId;
        var el = renderMessage(m, isPinned);
        var loading = document.getElementById('messagesLoading');
        if (loading) loading.remove();
        messagesContainer.appendChild(el);
    }

    function loadMessages() {
        fetch('/groups/' + groupId + '/messages?limit=100&offset=0', { credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var loading = document.getElementById('messagesLoading');
                if (loading) loading.remove();
                (data.messages || []).forEach(function(m) { appendMessage(m); });
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
        if (el) el.textContent = username + ' is typing...';
        wrap.classList.remove('d-none');
        clearTimeout(window._typingHide);
        window._typingHide = setTimeout(function() { if (wrap) wrap.classList.add('d-none'); }, 3000);
    }

    function updateMessageStatus(messageId, status) {
        var el = messagesContainer.querySelector('[data-message-id="' + messageId + '"] .message-meta');
        if (el && status === 'delivered') {
            var t = el.textContent;
            if (t.indexOf('✓✓') === -1) el.textContent = t.trim() + ' ✓✓';
        }
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
                    appendMessage(data);
                    if (data.id && currentUserId && data.user_id === currentUserId) {
                        ws.send(JSON.stringify({ type: 'delivery_ack', message_id: data.id }));
                    }
                    if (data.sender_type === 'ai' || data.message_type === 'ai') {
                        clearGroupStopState();
                    }
                } else if (data.type === 'online') {
                    updateOnlineList(data.users);
                } else if (data.type === 'typing') {
                    if (data.user_id !== currentUserId) showTyping(data.username || 'Someone');
                } else if (data.type === 'message_status') {
                    updateMessageStatus(data.message_id, data.status);
                } else if (data.type === 'ai_started') {
                    // Only show loading/stop for the user who started this AI request
                    if (data.initiated_by === currentUserId) {
                        currentGroupRequestId = data.request_id || null;
                        setGroupSendButtonStop(true);
                    } else if (data.initiated_username) {
                        showToast(data.initiated_username + ' is generating...', 'info');
                    }
                } else if (data.type === 'ai_finished') {
                    if (data.request_id === currentGroupRequestId) clearGroupStopState();
                } else if (data.type === 'history_cleared') {
                    clearAllMessagesUI();
                } else if (data.type === 'group_deleted') {
                    showToast('This group was deleted.', 'warning');
                    setTimeout(function() { window.location.href = '/groups/page/list'; }, 1500);
                } else if (data.type === 'member_left') {
                    if (data.username) showToast(data.username + ' left the group', 'info');
                } else if (data.type === 'ai_busy') {
                    showToast(data.message || 'Another member is using the AI. Please wait.', 'warning');
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

    function sendMessage(content, messageType, filePath, fileName) {
        messageType = messageType || 'text';
        if (ws && ws.readyState === WebSocket.OPEN) {
            var payload = {
                type: 'message',
                content: content,
                message_type: messageType,
                file_path: filePath || null,
                file_name: fileName || null
            };
            if (selectedGroupFileId != null) payload.group_file_id = selectedGroupFileId;
            ws.send(JSON.stringify(payload));
        }
        messageInput.value = '';
        pendingFile = null;
        if (attachmentPreview) {
            attachmentPreview.innerHTML = '';
            attachmentPreview.style.display = 'none';
        }
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
        if (!content && !pendingFile) return;
        if (pendingFile) {
            var formData = new FormData();
            formData.append('file', pendingFile);
            fetch('/groups/' + groupId + '/upload', { method: 'POST', body: formData, credentials: 'include' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.file_path) {
                        sendMessage(content || 'Shared a file', 'file', data.file_path, data.file_name);
                    }
                })
                .catch(function() { showToast('Upload failed', 'danger'); });
        } else {
            sendMessage(content);
        }
    });

    messageInput.addEventListener('input', function() {
        clearTimeout(typingTimeout);
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'typing' }));
            typingTimeout = setTimeout(function() {}, 2000);
        }
    });

    if (groupFileInput) {
        groupFileInput.addEventListener('change', function() {
            var file = this.files && this.files[0];
            if (!file) return;
            if (!/\.(pdf|png|jpg|jpeg)$/i.test(file.name)) {
                showToast('Only PDF and images allowed', 'warning');
                return;
            }
            pendingFile = file;
            attachmentPreview.style.display = 'flex';
            attachmentPreview.innerHTML = '<span class="me-2"><i class="bi bi-file-earmark"></i> ' + escapeHtml(file.name) + '</span><button type="button" class="btn btn-sm btn-outline-secondary" id="clearGroupFile">Clear</button>';
            document.getElementById('clearGroupFile').addEventListener('click', function() {
                pendingFile = null;
                groupFileInput.value = '';
                attachmentPreview.innerHTML = '';
                attachmentPreview.style.display = 'none';
            });
        });
    }

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
                    el.innerHTML = '<span class="text-muted">No files yet</span>';
                    return;
                }
                el.innerHTML = '<ul class="list-unstyled mb-0">' + files.map(function(f) {
                    var useClass = selectedGroupFileId === f.id ? 'btn-warning' : 'btn-outline-secondary';
                    return '<li class="d-flex align-items-center gap-1 py-1">' +
                        '<a href="/uploads/' + escapeHtml(f.file_path || '') + '" target="_blank" class="small text-truncate flex-grow-1" title="' + escapeHtml(f.file_name) + '">' + escapeHtml(f.file_name) + '</a>' +
                        '<button type="button" class="btn btn-sm ' + useClass + ' use-in-ai-btn" data-file-id="' + f.id + '" data-file-name="' + escapeHtml(f.file_name) + '" title="Use in AI">Use</button>' +
                        '</li>';
                }).join('') + '</ul>';
                el.querySelectorAll('.use-in-ai-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var id = parseInt(this.dataset.fileId, 10);
                        var name = this.dataset.fileName || '';
                        if (selectedGroupFileId === id) {
                            selectedGroupFileId = null;
                            document.getElementById('selectedFileForAi').classList.add('d-none');
                        } else {
                            selectedGroupFileId = id;
                            document.getElementById('selectedFileForAiName').textContent = name;
                            document.getElementById('selectedFileForAi').classList.remove('d-none');
                        }
                        loadFiles();
                    });
                });
            })
            .catch(function() { el.innerHTML = '<span class="text-muted">Failed to load</span>'; });
    }

    if (document.getElementById('clearSelectedFileForAi')) {
        document.getElementById('clearSelectedFileForAi').addEventListener('click', function() {
            selectedGroupFileId = null;
            document.getElementById('selectedFileForAi').classList.add('d-none');
            loadFiles();
        });
    }

    document.querySelectorAll('.ai-quick-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var prefix = this.getAttribute('data-prefix') || '@ai ';
            messageInput.value = prefix;
            messageInput.focus();
        });
    });

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

    var sidebarFileInput = document.getElementById('groupFileInputSidebar');
    if (sidebarFileInput) {
        sidebarFileInput.addEventListener('change', function() {
            var file = this.files && this.files[0];
            if (!file) return;
            if (!/\.(pdf|png|jpg|jpeg)$/i.test(file.name)) {
                showToast('Only PDF and images allowed', 'warning');
                return;
            }
            var formData = new FormData();
            formData.append('file', file);
            fetch('/groups/' + groupId + '/upload', { method: 'POST', body: formData, credentials: 'include' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.file_path) {
                        showToast('File uploaded', 'success');
                        loadFiles();
                        if (ws && ws.readyState === WebSocket.OPEN) {
                            var payload = { type: 'message', content: 'Shared a file', message_type: 'file', file_path: data.file_path, file_name: data.file_name };
                            if (data.document_id != null) payload.group_file_id = data.document_id;
                            ws.send(JSON.stringify(payload));
                        }
                    }
                })
                .catch(function() { showToast('Upload failed', 'danger'); });
            this.value = '';
        });
    }

    loadMessages();
    loadFiles();
    connectWs();
})();
