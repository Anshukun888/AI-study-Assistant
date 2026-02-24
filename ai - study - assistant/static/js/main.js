// AI Study Assistant - Main JavaScript
// Utility functions and shared behavior

// Export for use in templates if needed
window.AIStudyAssistant = {
    escapeHtml: function(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }
};

// Global handler: toggle password visibility when clicking
// a `.toggle-password` button next to a `.password-input`.
document.addEventListener('click', function (e) {
    const btn = e.target.closest('.toggle-password');
    if (!btn) return;
    const input = btn.parentElement ? btn.parentElement.querySelector('.password-input') : null;
    if (!input) return;
    const icon = btn.querySelector('i');
    if (input.type === 'password') {
        input.type = 'text';
        if (icon) {
            icon.classList.remove('bi-eye');
            icon.classList.add('bi-eye-slash');
        }
    } else {
        input.type = 'password';
        if (icon) {
            icon.classList.remove('bi-eye-slash');
            icon.classList.add('bi-eye');
        }
    }
});
