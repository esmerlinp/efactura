// e-Factura Admin Portal — JS

// ── Theme Management ──────────────────────────────────────
const THEME_KEY = 'efactura-portal-theme';

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const darkIcon = document.querySelector('.theme-icon-dark');
    const lightIcon = document.querySelector('.theme-icon-light');
    if (darkIcon && lightIcon) {
        if (theme === 'light') {
            darkIcon.style.display = 'none';
            lightIcon.style.display = 'inline-flex';
        } else {
            darkIcon.style.display = 'inline-flex';
            lightIcon.style.display = 'none';
        }
    }
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
}

// Apply saved theme immediately on load (before DOMContentLoaded to avoid flash)
(function () {
    const saved = localStorage.getItem(THEME_KEY) || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
})();

// ── DOMContentLoaded ──────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Sync toggle icons with the currently active theme
    const saved = localStorage.getItem(THEME_KEY) || 'dark';
    applyTheme(saved);

    // Auto-dismiss flash messages after 5s
    document.querySelectorAll('.flash').forEach(el => {
        setTimeout(() => {
            el.style.opacity = '0';
            el.style.transition = 'opacity 0.4s';
            setTimeout(() => el.remove(), 400);
        }, 5000);
    });

    // Toggle navigation on mobile
    const mobileNavToggle = document.getElementById('mobile-nav-toggle');
    const sidebar = document.querySelector('.sidebar');
    
    if (mobileNavToggle && sidebar) {
        mobileNavToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            sidebar.classList.toggle('open');
        });

        // Close sidebar when clicking outside on mobile
        document.addEventListener('click', (e) => {
            if (sidebar.classList.contains('open') && !sidebar.contains(e.target) && !mobileNavToggle.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        });
    }
});
