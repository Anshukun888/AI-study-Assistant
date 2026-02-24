/**
 * Voice call with AI - production quality.
 * - AI speaks fully unless user says "STOP"; normal speech does NOT interrupt.
 * - "STOP" = stop TTS + abort in-flight message; call stays active; new question accepted.
 * - "END CALL" = full session end.
 * - After AI finishes or STOP: accept new question; optional follow-up: "Deeper explanation or example?"
 */
(function() {
    'use strict';

    var recognition = null;
    var voiceCallConvId = null;
    var isCallActive = false;
    var aiSpeaking = false;
    var callMuted = false;
    var callVolume = 1;
    var ttsQueue = [];
    var isProcessingUserSpeech = false;

    /** "Stop" = stop speaking + abort request only; keep call active. */
    var STOP_ONLY_PHRASES = ['stop'];
    /** "End call" = close session and exit. */
    var END_CALL_PHRASES = ['end call', 'cut call', 'hang up', 'end the call'];
    var MIN_FINAL_WORDS = 2;
    var pendingAIResponse = false;
    var voiceCallAbortController = null; /* abort in-flight sendToAI when user says STOP */

    function getConvIdInput() {
        return document.getElementById('conversationId');
    }

    function getConversationId() {
        var el = getConvIdInput();
        if (!el) return null;
        var v = (el.value || '').trim();
        return v ? parseInt(v, 10) : null;
    }

    function setConversationId(id) {
        var el = getConvIdInput();
        if (el) el.value = id ? String(id) : '';
    }

    function ensureConversation() {
        return new Promise(function(resolve) {
            var cid = getConversationId();
            if (cid) {
                voiceCallConvId = cid;
                resolve(cid);
                return;
            }
            var formData = new FormData();
            formData.append('title', 'Voice call');
            formData.append('mode', 'free');
            fetch('/chat/new', {
                method: 'POST',
                body: formData,
                credentials: 'include',
                headers: { Accept: 'application/json' }
            }).then(function(resp) {
                return resp.json();
            }).then(function(data) {
                var id = data.conversation_id || null;
                if (id) {
                    setConversationId(id);
                    voiceCallConvId = id;
                }
                resolve(id);
            }).catch(function() {
                resolve(null);
            });
        });
    }

    function appendTranscript(role, text) {
        var container = document.getElementById('voiceCallTranscript');
        if (!container) return;
        var p = document.createElement('p');
        p.className = role === 'you' ? 'voice-you' : 'voice-ai';
        p.textContent = (role === 'you' ? 'You: ' : 'AI: ') + text;
        container.appendChild(p);
        container.scrollTop = container.scrollHeight;
    }

    function setStatus(text) {
        var el = document.getElementById('voiceCallStatus');
        if (el) el.textContent = text;
    }

    function setStatusListening() {
        setStatus('Listening…');
        setMicVisible(true);
        setAISpeakingVisible(false);
    }

    function setStatusAISpeaking() {
        setStatus('AI Speaking…');
        setMicVisible(false);
        setAISpeakingVisible(true);
    }

    function setStatusThinking() {
        setStatus('AI is thinking…');
        setMicVisible(false);
        setAISpeakingVisible(false);
    }

    function setMicVisible(show) {
        var el = document.getElementById('voiceCallMicAnimation');
        if (el) el.classList.toggle('d-none', !show);
    }

    function setAISpeakingVisible(show) {
        var el = document.getElementById('voiceCallAISpeaking');
        if (el) el.classList.toggle('d-none', !show);
    }

    function isStopOnlyCommand(transcript) {
        var t = (transcript || '').trim().toLowerCase();
        return STOP_ONLY_PHRASES.some(function(phrase) {
            return t === phrase || t.indexOf(phrase) === 0 || t.endsWith(phrase);
        });
    }

    function isEndCallCommand(transcript) {
        var t = (transcript || '').trim().toLowerCase();
        return END_CALL_PHRASES.some(function(phrase) {
            return t === phrase || t.indexOf(phrase) === 0 || t.endsWith(phrase);
        });
    }

    function isNewQuestion(transcript) {
        var t = (transcript || '').trim();
        if (!t) return false;
        var words = t.split(/\s+/).filter(Boolean);
        return words.length >= MIN_FINAL_WORDS;
    }

    function getTTSVolume() {
        if (callMuted) return 0;
        var slider = document.getElementById('voiceCallVolume');
        if (slider) {
            var v = parseFloat(slider.value, 10);
            if (!isNaN(v)) return Math.max(0, Math.min(1, v));
        }
        return callVolume;
    }

    function speakText(text, onEnd) {
        if (!('speechSynthesis' in window)) {
            if (onEnd) onEnd();
            return;
        }
        var clean = (typeof window.cleanTextForVoice === 'function') ? window.cleanTextForVoice(text) : text;
        if (!clean.trim()) {
            if (onEnd) onEnd();
            return;
        }
        window.speechSynthesis.cancel();
        aiSpeaking = true;
        setStatusAISpeaking();
        var u = new SpeechSynthesisUtterance(clean);
        u.rate = 0.95;
        u.pitch = 1;
        u.volume = getTTSVolume();
        u.onend = function() {
            aiSpeaking = false;
            setAISpeakingVisible(false);
            if (isCallActive) setStatusListening();
            if (onEnd) onEnd();
        };
        u.onerror = function() {
            aiSpeaking = false;
            setAISpeakingVisible(false);
            if (isCallActive) setStatusListening();
            if (onEnd) onEnd();
        };
        window.speechSynthesis.speak(u);
    }

    /** Optional short follow-up after main answer: "Would you like a deeper explanation or a practice question?" */
    function speakFollowUpThenListen(callback) {
        var followUp = 'Would you like a deeper explanation or a practice question?';
        if (!('speechSynthesis' in window)) {
            if (callback) callback();
            return;
        }
        var clean = (typeof window.cleanTextForVoice === 'function') ? window.cleanTextForVoice(followUp) : followUp;
        if (!clean.trim() || !isCallActive) {
            if (callback) callback();
            return;
        }
        var u = new SpeechSynthesisUtterance(clean);
        u.rate = 0.9;
        u.pitch = 1;
        u.volume = getTTSVolume();
        u.onend = u.onerror = function() {
            if (isCallActive) setStatusListening();
            if (callback) callback();
        };
        window.speechSynthesis.speak(u);
    }

    function stopSpeaking() {
        if (window.speechSynthesis) window.speechSynthesis.cancel();
        aiSpeaking = false;
        setAISpeakingVisible(false);
        ttsQueue = [];
        pendingAIResponse = false;
        if (voiceCallAbortController) {
            try { voiceCallAbortController.abort(); } catch (e) {}
            voiceCallAbortController = null;
        }
        if (isCallActive) setStatusListening();
    }

    function sendToAI(transcript, onResponse) {
        if (voiceCallAbortController) {
            try { voiceCallAbortController.abort(); } catch (e) {}
        }
        voiceCallAbortController = new AbortController();
        var fd = new FormData();
        fd.append('conversation_id', voiceCallConvId);
        fd.append('content', transcript);
        fetch('/chat/send', {
            method: 'POST',
            body: fd,
            credentials: 'include',
            signal: voiceCallAbortController.signal
        }).then(function(resp) {
            return resp.json();
        }).then(function(data) {
            var content = (data && data.content) ? data.content : '';
            if (content && onResponse) onResponse(content);
            else if (onResponse) onResponse('');
        }).catch(function(err) {
            if (err.name === 'AbortError') return;
            if (onResponse) onResponse('Sorry, I could not respond. ' + (err.message || 'Network error'));
        }).finally(function() {
            voiceCallAbortController = null;
        });
    }

    function startRecognition() {
        var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            setStatus('Voice not supported in this browser');
            return;
        }
        recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = 'en-US';
        recognition.maxAlternatives = 1;

        recognition.onresult = function(event) {
            var finalTranscript = '';
            var hasFinal = false;
            for (var i = event.resultIndex; i < event.results.length; i++) {
                if (event.results[i].isFinal) {
                    hasFinal = true;
                    finalTranscript += event.results[i][0].transcript;
                }
            }
            finalTranscript = finalTranscript.trim();
            if (!hasFinal || !finalTranscript) return;

            if (isEndCallCommand(finalTranscript)) {
                endCall();
                return;
            }
            if (isStopOnlyCommand(finalTranscript)) {
                stopSpeaking();
                return;
            }

            /* Only accept new question when AI is not speaking and no request in flight (no interrupt on user speech) */
            if (aiSpeaking || pendingAIResponse || isProcessingUserSpeech) return;
            if (!isNewQuestion(finalTranscript)) return;

            isProcessingUserSpeech = true;
            pendingAIResponse = true;
            setStatusThinking();
            setMicVisible(false);
            appendTranscript('you', finalTranscript);
            sendToAI(finalTranscript, function(aiText) {
                isProcessingUserSpeech = false;
                if (!isCallActive) return;
                if (!pendingAIResponse) return;
                pendingAIResponse = false;
                if (aiText && aiText.trim()) {
                    appendTranscript('ai', aiText);
                    speakText(aiText, function() {
                        if (isCallActive) speakFollowUpThenListen(function() {});
                    });
                } else {
                    setStatusListening();
                }
            });
        };

        recognition.onend = function() {
            if (isCallActive && recognition) {
                try { recognition.start(); } catch (e) {}
            }
        };

        recognition.onerror = function(event) {
            if (event.error !== 'aborted' && event.error !== 'no-speech') {
                if (isCallActive) setStatusListening();
            }
            if (!aiSpeaking && isCallActive) setMicVisible(true);
        };

        try {
            recognition.start();
            setStatusListening();
        } catch (e) {
            setStatus('Could not start microphone');
        }
    }

    function endCall() {
        isCallActive = false;
        isProcessingUserSpeech = false;
        pendingAIResponse = false;
        if (recognition) {
            try { recognition.abort(); } catch (e) {}
            recognition = null;
        }
        stopSpeaking();
        setMicVisible(false);
        setAISpeakingVisible(false);
        setStatus('Tap Start to begin');
        var startBtn = document.getElementById('voiceCallStartBtn');
        var activeBtns = document.querySelector('.voice-call-active-buttons');
        if (startBtn) startBtn.classList.remove('d-none');
        if (activeBtns) activeBtns.classList.add('d-none');
        var transcript = document.getElementById('voiceCallTranscript');
        if (transcript) transcript.innerHTML = '';
        var modal = document.getElementById('voiceCallModal');
        if (modal) {
            var bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) bsModal.hide();
        }
    }

    function startCall() {
        setStatus('Starting…');
        ensureConversation().then(function(cid) {
            if (!cid) {
                setStatus('Could not create conversation');
                return;
            }
            isCallActive = true;
            var startBtn = document.getElementById('voiceCallStartBtn');
            var activeBtns = document.querySelector('.voice-call-active-buttons');
            if (startBtn) startBtn.classList.add('d-none');
            if (activeBtns) activeBtns.classList.remove('d-none');
            startRecognition();
        });
    }

    function toggleMute() {
        callMuted = !callMuted;
        var btn = document.getElementById('voiceCallMuteBtn');
        var icon = document.getElementById('voiceCallMuteIcon');
        if (btn && icon) {
            btn.classList.toggle('active', callMuted);
            btn.title = callMuted ? 'Unmute' : 'Mute';
            icon.className = callMuted ? 'bi bi-mic-mute-fill' : 'bi bi-mic-fill';
        }
        if (window.speechSynthesis && window.speechSynthesis.speaking) {
            var u = window.speechSynthesis.getVoices();
        }
    }

    function initVoiceCall() {
        var btnOpen = document.getElementById('btnVoiceCall');
        var modalEl = document.getElementById('voiceCallModal');
        if (!btnOpen || !modalEl) return;

        btnOpen.addEventListener('click', function openModal() {
            voiceCallConvId = getConversationId();
            callMuted = false;
            var modal = new bootstrap.Modal(modalEl);
            modal.show();
        });

        var startBtn = document.getElementById('voiceCallStartBtn');
        var endBtn = document.getElementById('voiceCallEndBtn');
        var closeBtn = document.getElementById('voiceCallCloseBtn');
        if (startBtn) startBtn.addEventListener('click', startCall);
        if (endBtn) endBtn.addEventListener('click', endCall);
        if (closeBtn) closeBtn.addEventListener('click', endCall);

        var muteBtn = document.getElementById('voiceCallMuteBtn');
        if (muteBtn) muteBtn.addEventListener('click', toggleMute);

        var volumeSlider = document.getElementById('voiceCallVolume');
        if (volumeSlider) {
            volumeSlider.addEventListener('input', function() {
                callVolume = parseFloat(this.value, 10);
                if (isNaN(callVolume)) callVolume = 1;
                callVolume = Math.max(0, Math.min(1, callVolume));
            });
        }

        modalEl.addEventListener('hidden.bs.modal', function() {
            endCall();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initVoiceCall);
    } else {
        setTimeout(initVoiceCall, 0);
    }
})();
