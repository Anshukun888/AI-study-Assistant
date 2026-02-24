/**
 * Study Features - Study Plans, Voice Output
 */

(function() {
    'use strict';

    /**
     * Clean text for natural TTS: remove ALL markdown/symbols, convert bullets to speech.
     * Example: "- Machine Learning" -> "Machine learning". No asterisks, bullets, or symbols read aloud.
     */
    window.cleanTextForVoice = function(text) {
        if (!text || typeof text !== 'string') return '';
        var s = text.trim();
        if (!s) return '';

        // Strip code blocks (multiline)
        s = s.replace(/```[\s\S]*?```/g, ' ');
        // Strip inline code - keep content only
        s = s.replace(/`([^`]+)`/g, '$1');
        // Bold/italic: **text** and *text* and _text_ - keep text only
        s = s.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/\*([^*]+)\*/g, '$1');
        s = s.replace(/__([^_]+)__/g, '$1').replace(/_([^_]+)_/g, '$1');
        // Heading markers - remove # ## ### etc
        s = s.replace(/^#{1,6}\s*/gm, '');

        var lines = s.split(/\n/).map(function(ln) { return ln.trim(); }).filter(Boolean);
        var bulletPattern = /^(\s*[-*•]\s+|\s*\d+[.)]\s+)(.*)$/i;
        var resultParts = [];
        var bulletGroup = [];

        function flushBullets() {
            if (bulletGroup.length === 0) return;
            var cleaned = bulletGroup.map(function(x) {
                return x.replace(/^[\s*\-•\d.)]+\s*/, '').trim()
                    .replace(/\*\*|\*|__|_/g, '');
            }).filter(Boolean);
            if (cleaned.length === 1) {
                resultParts.push(cleaned[0] + '.');
            } else if (cleaned.length === 2) {
                resultParts.push(cleaned[0] + ' and ' + cleaned[1] + '.');
            } else if (cleaned.length > 2) {
                resultParts.push(cleaned.slice(0, -1).join(', ') + ', and ' + cleaned[cleaned.length - 1] + '.');
            }
            bulletGroup = [];
        }

        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].replace(/\*\*|\*/g, '').trim();
            if (!line) {
                flushBullets();
                continue;
            }
            var match = line.match(bulletPattern);
            if (match) {
                bulletGroup.push(match[2].trim());
            } else {
                flushBullets();
                line = line.replace(/^[\s\-*#_`]+\s*|\s*[\s\-*#_`]+$/g, '');
                if (line) resultParts.push(line);
            }
        }
        flushBullets();

        var out = resultParts.join(' ');
        // Remove ALL markdown/symbols so TTS never says "asterisk" or "dash"
        ['*', '_', '`', '#', '~', '^', '|', '‑', '–', '—'].forEach(function(ch) { out = out.split(ch).join(''); });
        out = out.replace(/\s*[-*•]\s+/g, ' ').replace(/-{2,}/g, ' ').replace(/\s+/g, ' ').replace(/\s*([,.])\s*/g, '$1 ').trim();
        out = out.replace(/^[\s\-*#_`~|•]+\s*|\s*[\s\-*#_`~|•]+$/g, '');
        out = out.replace(/\s+/g, ' ').trim();
        if (out && !/[.!?]$/.test(out)) out = out + '.';
        return out;
    };

    window.createStudyPlan = async function(topic, planType, documentId) {
        const loadingModalHtml = `
            <div class="modal fade" id="studyPlanLoadingModal" tabindex="-1" data-bs-backdrop="static">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-body text-center py-4">
                            <div class="spinner-border text-primary mb-3" role="status"></div>
                            <p class="mb-0">Generating your study plan...</p>
                        </div>
                    </div>
                </div>
            </div>
        `;
        const existingLoading = document.getElementById('studyPlanLoadingModal');
        if (existingLoading) existingLoading.remove();
        document.body.insertAdjacentHTML('beforeend', loadingModalHtml);
        const loadingModal = new bootstrap.Modal(document.getElementById('studyPlanLoadingModal'));
        loadingModal.show();

        try {
            const formData = new FormData();
            formData.append('topic', topic);
            formData.append('plan_type', planType);
            if (documentId) formData.append('document_id', documentId);

            const resp = await fetch('/api/study-plans/create', {
                method: 'POST',
                body: formData,
                credentials: 'include',
            });

            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || 'Failed to create study plan');

            loadingModal.hide();
            document.getElementById('studyPlanLoadingModal')?.remove();

            if (data.conversation_id && typeof window.openStudyPlanChat === 'function') {
                window.openStudyPlanChat(data.conversation_id, data.title || 'Study Plan', data.content);
            } else {
                showStudyPlan(data.study_plan_id, data.content);
            }
            return data;
        } catch (e) {
            loadingModal.hide();
            document.getElementById('studyPlanLoadingModal')?.remove();
            alert('Error: ' + (e.message || 'Failed to create study plan'));
            throw e;
        }
    };

    window.showStudyPlan = function(planId, content) {
        const modalHtml = `
            <div class="modal fade" id="studyPlanViewModal" tabindex="-1">
                <div class="modal-dialog modal-xl">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Study Plan</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <div class="markdown-content">${renderMarkdown(content)}</div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        const existing = document.getElementById('studyPlanViewModal');
        if (existing) existing.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const modal = new bootstrap.Modal(document.getElementById('studyPlanViewModal'));
        modal.show();
        const contentEl = document.querySelector('#studyPlanViewModal .markdown-content');
        if (contentEl) {
            addCopyButtons(contentEl);
            highlightCode(contentEl);
        }
    };

    window.setupVoiceOutput = function() {
        const btn = document.getElementById('btnVoiceOutput');
        if (!btn) return;

        if ('speechSynthesis' in window) {
            let isSpeaking = false;

            btn.onclick = () => {
                const lastMessage = document.querySelector('.message-assistant:last-child .message-text');
                if (!lastMessage) return;
                let text = lastMessage.textContent || lastMessage.innerText;
                if (!text) return;
                text = window.cleanTextForVoice ? window.cleanTextForVoice(text) : text;

                if (isSpeaking) {
                    window.speechSynthesis.cancel();
                    btn.classList.remove('speaking');
                    btn.innerHTML = '<i class="bi bi-volume-up"></i>';
                    isSpeaking = false;
                } else {
                    const utterance = new SpeechSynthesisUtterance(text);
                    utterance.rate = 0.9;
                    utterance.pitch = 1;
                    utterance.volume = 1;
                    utterance.onstart = () => {
                        btn.classList.add('speaking');
                        btn.innerHTML = '<i class="bi bi-volume-mute"></i>';
                        isSpeaking = true;
                    };
                    utterance.onend = () => {
                        btn.classList.remove('speaking');
                        btn.innerHTML = '<i class="bi bi-volume-up"></i>';
                        isSpeaking = false;
                    };
                    window.speechSynthesis.speak(utterance);
                }
            };
        } else {
            btn.style.display = 'none';
        }
    };

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    function renderMarkdown(content) {
        if (!content) return '';
        if (typeof marked === 'undefined') {
            return escapeHtml(content).replace(/\n/g, '<br>');
        }
        try {
            return marked.parse(content);
        } catch (e) {
            return escapeHtml(content).replace(/\n/g, '<br>');
        }
    }

    function addCopyButtons(container) {
        if (!container) return;
        container.querySelectorAll('pre code').forEach((codeBlock) => {
            const pre = codeBlock.parentElement;
            if (pre.querySelector('.copy-code-btn')) return;
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
                } catch (err) {}
            };
            pre.style.position = 'relative';
            pre.appendChild(copyBtn);
        });
    }

    function highlightCode(container) {
        if (!container || typeof Prism === 'undefined') return;
        container.querySelectorAll('pre code').forEach((block) => Prism.highlightElement(block));
    }
})();
