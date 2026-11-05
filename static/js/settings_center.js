(function () {
    'use strict';

    function normalizeSearch(value) {
        return String(value || '')
            .toLocaleLowerCase('es')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .trim();
    }

    function initializeSettingsCenter() {
        const input = document.getElementById('settings-search');
        if (!input) return;

        const clearButton = document.getElementById('settings-search-clear');
        const emptyState = document.getElementById('settings-no-results');
        const categories = Array.from(document.querySelectorAll('[data-settings-category]'));
        const cards = Array.from(document.querySelectorAll('[data-settings-item]'));

        function applyFilter() {
            const query = normalizeSearch(input.value);
            let visibleItems = 0;

            cards.forEach(card => {
                const visible = !query || normalizeSearch(card.dataset.search).includes(query);
                card.hidden = !visible;
                if (visible) visibleItems += 1;
            });

            categories.forEach(category => {
                category.hidden = !category.querySelector('[data-settings-item]:not([hidden])');
            });

            clearButton.hidden = !query;
            emptyState.hidden = visibleItems !== 0;
        }

        input.addEventListener('input', applyFilter);
        clearButton.addEventListener('click', function () {
            input.value = '';
            applyFilter();
            input.focus();
        });

        document.querySelectorAll('[data-settings-action="export-data"]').forEach(button => {
            button.addEventListener('click', function () {
                const modal = document.getElementById('global-export-modal');
                if (modal) modal.style.display = 'flex';
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeSettingsCenter);
    } else {
        initializeSettingsCenter();
    }
})();
