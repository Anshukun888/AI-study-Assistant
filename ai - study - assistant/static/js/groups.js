(function() {
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

    function extractInviteToken(input) {
        var s = (input || '').trim();
        if (!s) return null;
        var match = s.match(/\/groups\/invite\/([^/?#]+)/i);
        if (match) return match[1];
        if (/^[A-Za-z0-9_-]{20,}$/.test(s)) return s;
        return s;
    }

    document.getElementById('btnCreateGroup').addEventListener('click', function() {
        var modal = new bootstrap.Modal(document.getElementById('createGroupModal'));
        document.getElementById('groupName').value = '';
        modal.show();
    });

    var btnJoinWithInvite = document.getElementById('btnJoinWithInvite');
    if (btnJoinWithInvite) {
        btnJoinWithInvite.addEventListener('click', function() {
            var modalEl = document.getElementById('joinInviteModal');
            if (!modalEl) return;
            document.getElementById('inviteLinkInput').value = '';
            document.getElementById('inviteLinkError').classList.add('d-none');
            var modal = new bootstrap.Modal(modalEl);
            modal.show();
        });
    }

    var btnJoinInviteSubmit = document.getElementById('btnJoinInviteSubmit');
    if (btnJoinInviteSubmit) {
        btnJoinInviteSubmit.addEventListener('click', function() {
            var input = document.getElementById('inviteLinkInput');
            var errEl = document.getElementById('inviteLinkError');
            var token = extractInviteToken(input && input.value);
            if (!token) {
                if (errEl) {
                    errEl.textContent = 'Please paste a valid invite link or token.';
                    errEl.classList.remove('d-none');
                }
                return;
            }
            errEl.classList.add('d-none');
            window.location.href = '/groups/invite/' + encodeURIComponent(token);
        });
    }

    document.getElementById('btnCreateGroupSubmit').addEventListener('click', async function() {
        var name = document.getElementById('groupName').value.trim();
        if (!name) {
            showToast('Enter a group name', 'warning');
            return;
        }
        var btn = document.getElementById('btnCreateGroupSubmit');
        btn.disabled = true;
        try {
            var form = new FormData();
            form.append('name', name);
            var r = await fetch('/groups/create', {
                method: 'POST',
                body: form,
                credentials: 'include'
            });
            var data = await r.json().catch(function() { return {}; });
            if (!r.ok) {
                showToast(data.detail || 'Failed to create group', 'danger');
                return;
            }
            bootstrap.Modal.getInstance(document.getElementById('createGroupModal')).hide();
            showToast('Group created', 'success');
            window.location.href = '/groups/' + data.group_id;
        } catch (e) {
            showToast('Error: ' + (e.message || 'Network error'), 'danger');
        } finally {
            btn.disabled = false;
        }
    });

    // Leave group
    var leaveGroupModal = document.getElementById('leaveGroupModal');
    var leaveGroupName = document.getElementById('leaveGroupName');
    var leaveGroupModalConfirm = document.getElementById('leaveGroupModalConfirm');
    var leaveGroupModalCancel = document.getElementById('leaveGroupModalCancel');
    if (leaveGroupModal && leaveGroupModalConfirm) {
        var leaveGroupId = null;
        document.querySelectorAll('.btn-leave-group').forEach(function(btn) {
            btn.addEventListener('click', function() {
                leaveGroupId = parseInt(this.getAttribute('data-group-id'), 10);
                var name = this.getAttribute('data-group-name') || 'this group';
                if (leaveGroupName) leaveGroupName.textContent = name;
                var modal = new bootstrap.Modal(leaveGroupModal);
                modal.show();
            });
        });
        leaveGroupModalConfirm.addEventListener('click', function() {
            if (leaveGroupId == null) return;
            var groupId = leaveGroupId;
            leaveGroupId = null;
            bootstrap.Modal.getInstance(leaveGroupModal).hide();
            fetch('/groups/' + groupId + '/leave', { method: 'POST', credentials: 'include', headers: { 'Accept': 'application/json' } })
                .then(function(r) {
                    if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed to leave'); });
                    return r.json();
                })
                .then(function() {
                    showToast('You left the group', 'success');
                    window.location.reload();
                })
                .catch(function(e) {
                    showToast(e.message || 'Failed to leave group', 'danger');
                });
        });
        if (leaveGroupModalCancel) leaveGroupModalCancel.addEventListener('click', function() { bootstrap.Modal.getInstance(leaveGroupModal).hide(); });
    }

    // Delete group (admin only)
    var deleteGroupModal = document.getElementById('deleteGroupModal');
    var deleteGroupName = document.getElementById('deleteGroupName');
    var deleteGroupModalConfirm = document.getElementById('deleteGroupModalConfirm');
    var deleteGroupModalCancel = document.getElementById('deleteGroupModalCancel');
    if (deleteGroupModal && deleteGroupModalConfirm) {
        var deleteGroupId = null;
        document.querySelectorAll('.btn-delete-group').forEach(function(btn) {
            btn.addEventListener('click', function() {
                deleteGroupId = parseInt(this.getAttribute('data-group-id'), 10);
                var name = this.getAttribute('data-group-name') || 'this group';
                if (deleteGroupName) deleteGroupName.textContent = name;
                var modal = new bootstrap.Modal(deleteGroupModal);
                modal.show();
            });
        });
        deleteGroupModalConfirm.addEventListener('click', function() {
            if (deleteGroupId == null) return;
            var groupId = deleteGroupId;
            deleteGroupId = null;
            bootstrap.Modal.getInstance(deleteGroupModal).hide();
            fetch('/groups/' + groupId + '/delete', { method: 'POST', credentials: 'include', headers: { 'Accept': 'application/json' } })
                .then(function(r) {
                    if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Failed to delete'); });
                    return r.json();
                })
                .then(function() {
                    showToast('Group deleted', 'success');
                    window.location.reload();
                })
                .catch(function(e) {
                    showToast(e.message || 'Failed to delete group', 'danger');
                });
        });
        if (deleteGroupModalCancel) deleteGroupModalCancel.addEventListener('click', function() { bootstrap.Modal.getInstance(deleteGroupModal).hide(); });
    }
})();
