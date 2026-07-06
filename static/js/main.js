/* =========================================================================
   ASINCRONISMO Y CONTROL DE INTERFAZ DE USUARIO - MAIN JS
   ========================================================================= */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Inicializar animaciones de entrada en cascada
    const cards = document.querySelectorAll('.card-kpi, .card-table-wrapper, .auth-card');
    cards.forEach((card, index) => {
        card.classList.add('animate-fade-in');
        card.style.animationDelay = `${index * 0.05}s`;
    });

    // 2. Control de Alternancia de Sandbox / Producción (Unificado)
    const sandboxToggle = document.getElementById('sandbox-toggle');
    const sandboxBannerToggle = document.getElementById('sandbox-banner-toggle');
    
    const triggerToggleSandbox = async () => {
        try {
            const response = await fetch('/toggle-sandbox', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            if (response.ok) {
                // Efecto de parpadeo de pantalla sutil antes de recargar
                document.body.style.opacity = '0';
                document.body.style.transition = 'opacity 0.25s ease';
                
                setTimeout(() => {
                    window.location.reload();
                }, 250);
            } else {
                console.error('Fallo al alternar el entorno del Sandbox.');
            }
        } catch (err) {
            console.error('Error de red al alternar Sandbox:', err);
        }
    };

    if (sandboxToggle) {
        sandboxToggle.addEventListener('click', triggerToggleSandbox);
    }
    if (sandboxBannerToggle) {
        sandboxBannerToggle.addEventListener('click', triggerToggleSandbox);
    }

    // 3. Auto-ocultar Alertas de Jinja (Flask flashes)
    const alertBanners = document.querySelectorAll('.alert-banner');
    alertBanners.forEach(alert => {
        setTimeout(() => {
            alert.style.opacity = '0';
            alert.style.transform = 'translateY(-10px)';
            alert.style.transition = 'all 0.4s ease';
            setTimeout(() => alert.remove(), 400);
        }, 5000);
    });

    // 4. Recordatorios CRM de Próximo Contacto (Notificación Local visual en Dashboard)
    const crmReminders = document.querySelectorAll('.crm-notification-item');
    if (crmReminders.length > 0) {
        console.log(`🔔 Se encontraron ${crmReminders.length} compromisos CRM agendados para hoy.`);
    }

    // 5. Control de Alternancia de Tema (Oscuro / Claro) con persistencia
    const themeToggleBtn = document.getElementById('theme-toggle-dropdown-btn');
    if (themeToggleBtn) {
        const themeIconLight = document.getElementById('theme-icon-dropdown-light');
        const themeIconDark = document.getElementById('theme-icon-dropdown-dark');
        
        // Función para actualizar iconos
        const updateThemeIcons = (theme) => {
            if (theme === 'dark') {
                themeIconLight.style.display = 'block';
                themeIconDark.style.display = 'none';
            } else {
                themeIconLight.style.display = 'none';
                themeIconDark.style.display = 'block';
            }
        };

        // Leer tema inicial y sincronizar iconos
        const currentTheme = localStorage.getItem('theme') || 'light';
        updateThemeIcons(currentTheme);

        // Click event listener
        themeToggleBtn.addEventListener('click', () => {
            const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
            const newTheme = currentTheme === 'light' ? 'dark' : 'light';
            
            // Efecto de transición sutil en el fondo
            document.documentElement.style.transition = 'background-color 0.3s ease, color 0.3s ease';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            
            // Actualizar theme-color para Safari (reemplazar elemento para compatibilidad)
            if (typeof window.setThemeColor === 'function') {
                const lightColor = document.documentElement.getAttribute('data-theme-color-light') || '#7c3aed';
                const darkColor = document.documentElement.getAttribute('data-theme-color-dark') || '#0f172a';
                window.setThemeColor(newTheme === 'dark' ? darkColor : lightColor);
            }
            
            updateThemeIcons(newTheme);
        });
    }

    // 6. Control de Barra Lateral Colapsable con Persistencia
    const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
    const mainAppContainer = document.getElementById('main-app-container');
    const toggleIcon = document.getElementById('toggle-icon');

    if (sidebarToggleBtn && mainAppContainer) {
        // Función para actualizar el icono del botón de alternancia
        const updateToggleIcon = (isCollapsed) => {
            if (toggleIcon) {
                if (isCollapsed) {
                    toggleIcon.classList.remove('fa-chevron-left');
                    toggleIcon.classList.add('fa-chevron-right');
                } else {
                    toggleIcon.classList.remove('fa-chevron-right');
                    toggleIcon.classList.add('fa-chevron-left');
                }
            }
        };

        // Sincronizar icono inicial según estado
        const isCurrentlyCollapsed = mainAppContainer.classList.contains('sidebar-collapsed');
        updateToggleIcon(isCurrentlyCollapsed);

        sidebarToggleBtn.addEventListener('click', () => {
            const willCollapse = !mainAppContainer.classList.contains('sidebar-collapsed');
            
            if (willCollapse) {
                mainAppContainer.classList.add('sidebar-collapsed');
                localStorage.setItem('sidebar-collapsed', 'true');
            } else {
                mainAppContainer.classList.remove('sidebar-collapsed');
                localStorage.setItem('sidebar-collapsed', 'false');
            }
            
            updateToggleIcon(willCollapse);
        });
    }

    // 6.1. Control de Secciones de Barra Lateral Colapsables (Dropdowns de Grupos)
    const sidebarHeaders = document.querySelectorAll('.sidebar-section-header');

    // Función helper para colapsar una sección programáticamente
    function collapseSidebarSection(section) {
        if (section.getAttribute('id') === 'sidebar-section-quick') return;
        const content = section.querySelector('.sidebar-section-content');
        if (!content) return;

        if (content.dataset.transitioning === 'true') return;
        if (section.classList.contains('collapsed')) return;

        const sectionId = section.getAttribute('id');
        content.dataset.transitioning = 'true';

        const height = content.scrollHeight;
        content.style.maxHeight = height + 'px';
        content.style.opacity = '1';

        content.offsetHeight;

        section.classList.add('collapsed');
        content.style.maxHeight = '0px';
        content.style.opacity = '0';

        if (sectionId) {
            localStorage.setItem('sidebar-collapsed-' + sectionId, 'true');
        }

        content.addEventListener('transitionend', function onEnd(e) {
            if (e.propertyName === 'max-height') {
                content.style.maxHeight = '';
                content.style.opacity = '';
                content.removeAttribute('data-transitioning');
                content.removeEventListener('transitionend', onEnd);
            }
        });
    }

    sidebarHeaders.forEach(header => {
        header.addEventListener('click', () => {
            // Si la barra lateral entera está colapsada (minimizada), no hacer nada
            if (mainAppContainer && mainAppContainer.classList.contains('sidebar-collapsed')) {
                return;
            }

            const section = header.closest('.sidebar-section');
            if (!section) return;
            if (section.getAttribute('id') === 'sidebar-section-quick') return;

            const content = section.querySelector('.sidebar-section-content');
            if (!content) return;

            // Evitar spam de clicks durante la animación
            if (content.dataset.transitioning === 'true') {
                return;
            }

            const isCurrentlyCollapsed = section.classList.contains('collapsed');
            const sectionId = section.getAttribute('id');

            content.dataset.transitioning = 'true';

            if (isCurrentlyCollapsed) {
                // EXPANDIR — antes de expandir, colapsar automáticamente otras secciones no-General
                if (sectionId !== 'sidebar-section-general') {
                    document.querySelectorAll('.sidebar-section').forEach(otherSection => {
                        const otherId = otherSection.getAttribute('id');
                        if (otherId && otherId !== sectionId && otherId !== 'sidebar-section-general') {
                            collapseSidebarSection(otherSection);
                        }
                    });
                }

                content.style.maxHeight = '0px';
                content.style.opacity = '0';
                section.classList.remove('collapsed');

                // Forzar reflow para que el navegador reconozca el estado inicial
                const height = content.scrollHeight;
                content.offsetHeight;

                content.style.maxHeight = height + 'px';
                content.style.opacity = '1';

                if (sectionId) {
                    localStorage.setItem('sidebar-collapsed-' + sectionId, 'false');
                }

                const onEnd = (e) => {
                    if (e.propertyName === 'max-height') {
                        content.style.maxHeight = '';
                        content.style.opacity = '';
                        content.removeAttribute('data-transitioning');
                        content.removeEventListener('transitionend', onEnd);
                    }
                };
                content.addEventListener('transitionend', onEnd);
            } else {
                // COLAPSAR
                const height = content.scrollHeight;
                content.style.maxHeight = height + 'px';
                content.style.opacity = '1';

                // Forzar reflow
                content.offsetHeight;

                section.classList.add('collapsed');
                content.style.maxHeight = '0px';
                content.style.opacity = '0';

                if (sectionId) {
                    localStorage.setItem('sidebar-collapsed-' + sectionId, 'true');
                }

                const onEnd = (e) => {
                    if (e.propertyName === 'max-height') {
                        content.style.maxHeight = '';
                        content.style.opacity = '';
                        content.removeAttribute('data-transitioning');
                        content.removeEventListener('transitionend', onEnd);
                    }
                };
                content.addEventListener('transitionend', onEnd);
            }
        });
    });

    // 7. Formateo Automático de Entradas de Teléfono y Montos
    function formatPhoneNumber(value) {
        if (!value) return value;
        const phoneNumber = value.replace(/[^\d]/g, '');
        const phoneNumberLength = phoneNumber.length;
        if (phoneNumberLength < 4) return phoneNumber;
        if (phoneNumberLength < 7) {
            return `${phoneNumber.slice(0, 3)}-${phoneNumber.slice(3)}`;
        }
        return `${phoneNumber.slice(0, 3)}-${phoneNumber.slice(3, 6)}-${phoneNumber.slice(6, 10)}`;
    }

    // Formatear teléfonos existentes al cargar la página
    document.querySelectorAll('input').forEach(input => {
        const isPhone = input.type === 'tel' || /phone|tel|telefono/i.test(input.id || input.name || '');
        if (isPhone && input.value) {
            input.value = formatPhoneNumber(input.value);
        }
    });

    // Delegación de eventos para formatear teléfonos dinámicamente mientras se escribe
    document.addEventListener('input', (e) => {
        const target = e.target;
        const isPhone = target.tagName === 'INPUT' && (
            target.type === 'tel' ||
            /phone|tel|telefono/i.test(target.id || target.name || '')
        );
        if (isPhone) {
            const selectionStart = target.selectionStart;
            const prevLen = target.value.length;
            
            const formatted = formatPhoneNumber(target.value);
            target.value = formatted;
            
            const currentLen = formatted.length;
            let newPos = selectionStart + (currentLen - prevLen);
            target.setSelectionRange(newPos, newPos);
        }
    });

    // Delegación de eventos para formatear montos a 2 decimales al perder el foco (blur)
    document.addEventListener('blur', (e) => {
        const target = e.target;
        if (target.tagName === 'INPUT' && target.type === 'number') {
            const isAmount = target.step === '0.01' || 
                             /amount|price|monto|precio/i.test(target.id || target.name || '');
            if (isAmount) {
                const val = parseFloat(target.value);
                if (!isNaN(val)) {
                    target.value = val.toFixed(2);
                }
            }
        }
    }, true); // Usar fase de captura ya que 'blur' no burbujea

    // ====== 8. Accesos Rápidos (Pines del menú lateral) ======
    const PINNED_KEY = 'sidebar-quick-access';
    const MAX_PINNED = 3;

    function getPinnedHrefs() {
        try {
            return JSON.parse(localStorage.getItem(PINNED_KEY)) || [];
        } catch {
            return [];
        }
    }

    function setPinnedHrefs(hrefs) {
        if (hrefs.length === 0) {
            localStorage.removeItem(PINNED_KEY);
        } else {
            localStorage.setItem(PINNED_KEY, JSON.stringify(hrefs));
        }
        renderQuickAccess();
        updatePinIcons();
    }

    function renderQuickAccess() {
        const section = document.getElementById('sidebar-section-quick');
        const list = document.getElementById('quick-access-list');
        if (!section || !list) return;

        const hrefs = getPinnedHrefs();
        const validHrefs = [];

        list.innerHTML = '';

        hrefs.slice(0, MAX_PINNED).forEach(href => {
            const originalLink = document.querySelector(`.nav-item a[href="${href}"]`);
            if (!originalLink) return;
            validHrefs.push(href);

            const originalItem = originalLink.closest('.nav-item');
            if (!originalItem) return;

            const iconClass = originalLink.querySelector('i')?.className || 'fa-solid fa-link';
            const label = originalLink.querySelector('span')?.textContent || 'Sin etiqueta';
            const tooltip = originalItem.dataset.tooltip || label;

            const item = document.createElement('li');
            item.className = 'nav-item';
            item.dataset.tooltip = tooltip;

            const a = document.createElement('a');
            a.href = href;
            a.innerHTML = `<i class="${iconClass}"></i><span>${label}</span>`;

            const unpinBtn = document.createElement('button');
            unpinBtn.className = 'unpin-btn';
            unpinBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
            unpinBtn.dataset.href = href;
            unpinBtn.title = 'Quitar de accesos rápidos';
            unpinBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                setPinnedHrefs(getPinnedHrefs().filter(h => h !== href));
            });

            item.style.position = 'relative';
            item.appendChild(a);
            item.appendChild(unpinBtn);
            list.appendChild(item);
        });

        if (validHrefs.length !== hrefs.length) {
            setPinnedHrefs(validHrefs);
        }

        section.style.display = validHrefs.length === 0 ? 'none' : '';
    }

    function updatePinIcons() {
        const pinned = getPinnedHrefs();
        document.querySelectorAll('.pin-btn').forEach(btn => {
            const isPinned = pinned.includes(btn.dataset.href);
            btn.classList.toggle('pinned', isPinned);
            btn.title = isPinned ? 'Quitar de accesos rápidos' : 'Agregar a accesos rápidos';
        });
    }

    function addPinButtons() {
        document.querySelectorAll('.nav-item').forEach(item => {
            if (item.closest('#sidebar-section-quick')) return;
            if (item.querySelector('.pin-btn')) return;

            const link = item.querySelector('a');
            if (!link) return;

            const btn = document.createElement('button');
            btn.className = 'pin-btn';
            btn.innerHTML = '<i class="fa-solid fa-thumbtack"></i>';
            btn.dataset.href = link.getAttribute('href');
            btn.title = 'Agregar a accesos rápidos';

            btn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();

                const href = btn.dataset.href;
                const pinned = getPinnedHrefs();

                if (pinned.includes(href)) {
                    setPinnedHrefs(pinned.filter(h => h !== href));
                } else if (pinned.length < MAX_PINNED) {
                    setPinnedHrefs([...pinned, href]);
                } else {
                    btn.style.color = 'var(--danger)';
                    setTimeout(() => btn.style.color = '', 800);
                }
            });

            item.style.position = 'relative';
            item.appendChild(btn);
        });

        updatePinIcons();
    }

    renderQuickAccess();
    addPinButtons();
});

// =========================================================================
// ACTION MENU (3 DOTS DROPDOWN)
// =========================================================================
function toggleActionMenu(event) {
    event.stopPropagation();
    const btn = event.currentTarget;
    const menu = btn.nextElementSibling;
    if (!menu || !menu.classList.contains('action-menu-dropdown')) return;

    const isOpen = menu.classList.contains('show');
    closeAllActionMenus();
    if (!isOpen) {
        menu.classList.add('show');
        btn.classList.add('active');
    }
}

function closeAllActionMenus() {
    document.querySelectorAll('.action-menu-dropdown.show').forEach(m => m.classList.remove('show'));
    document.querySelectorAll('.action-menu-btn.active').forEach(b => b.classList.remove('active'));
}

document.addEventListener('click', function(e) {
    if (!e.target.closest('.action-menu')) {
        closeAllActionMenus();
    }
});

// Helper para formatear valores monetarios de DOP en la UI
function formatCurrencyDOP(amount) {
    return new Intl.NumberFormat('es-DO', {
        style: 'currency',
        currency: 'DOP'
    }).format(amount);
}

// =========================================================================
// DIALOG SYSTEM (replaces native alert/confirm)
// =========================================================================

/**
 * Show a custom alert dialog (replaces native alert())
 * @param {string} title - Modal title
 * @param {string} message - Message body
 * @param {string} type - 'info' | 'success' | 'warning' | 'danger' (default 'info')
 * @returns {Promise<boolean>} Always resolves to true (acknowledged)
 */
function showAlert(title, message, type) {
    type = type || 'info';
    var icons = {
        info: { icon: 'fa-circle-info', cls: 'info' },
        success: { icon: 'fa-circle-check', cls: 'success' },
        warning: { icon: 'fa-triangle-exclamation', cls: 'warning' },
        danger: { icon: 'fa-circle-exclamation', cls: 'danger' }
    };
    var iconDef = icons[type] || icons.info;
    return new Promise(function(resolve) {
        var overlay = document.createElement('div');
        overlay.className = 'dialog-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', title);
        overlay.innerHTML =
            '<div class="dialog-box">' +
            '  <div class="dialog-icon-row">' +
            '    <div class="dialog-icon-circle ' + iconDef.cls + '"><i class="fa-solid ' + iconDef.icon + '"></i></div>' +
            '  </div>' +
            '  <div class="dialog-body">' +
            '    <div class="dialog-title">' + title + '</div>' +
            '    <div class="dialog-message">' + message + '</div>' +
            '  </div>' +
            '  <div class="dialog-footer">' +
            '    <button class="btn btn-primary dialog-ok-btn">Aceptar</button>' +
            '  </div>' +
            '</div>';
        document.body.appendChild(overlay);
        document.body.style.overflow = 'hidden';

        var closeDialog = function() {
            overlay.classList.add('closing');
            setTimeout(function() {
                if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                document.body.style.overflow = '';
                resolve(true);
            }, 150);
        };

        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeDialog();
        });
        overlay.querySelector('.dialog-ok-btn').addEventListener('click', closeDialog);

        document.addEventListener('keydown', function escHandler(e) {
            if (e.key === 'Escape') {
                closeDialog();
                document.removeEventListener('keydown', escHandler);
            }
        });

        setTimeout(function() {
            var btn = overlay.querySelector('.dialog-ok-btn');
            if (btn) btn.focus();
        }, 100);
    });
}

/**
 * Show a custom confirm dialog (replaces native confirm())
 * @param {string} title - Modal title
 * @param {string} message - Confirmation message
 * @param {string} type - 'warning' | 'danger' (default 'warning')
 * @param {string} confirmText - Text for confirm button (default 'Confirmar')
 * @param {string} cancelText - Text for cancel button (default 'Cancelar')
 * @returns {Promise<boolean>} true if confirmed, false if cancelled
 */
function showConfirm(title, message, type, confirmText, cancelText) {
    type = type || 'warning';
    confirmText = confirmText || 'Confirmar';
    cancelText = cancelText || 'Cancelar';
    var icons = {
        warning: { icon: 'fa-triangle-exclamation', cls: 'warning' },
        danger: { icon: 'fa-circle-exclamation', cls: 'danger' },
        info: { icon: 'fa-circle-question', cls: 'info' }
    };
    var iconDef = icons[type] || icons.warning;
    var btnClass = type === 'danger' ? 'btn-danger' : 'btn-primary';

    return new Promise(function(resolve) {
        var overlay = document.createElement('div');
        overlay.className = 'dialog-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', title);
        overlay.innerHTML =
            '<div class="dialog-box">' +
            '  <div class="dialog-icon-row">' +
            '    <div class="dialog-icon-circle ' + iconDef.cls + '"><i class="fa-solid ' + iconDef.icon + '"></i></div>' +
            '  </div>' +
            '  <div class="dialog-body">' +
            '    <div class="dialog-title">' + title + '</div>' +
            '    <div class="dialog-message">' + message + '</div>' +
            '  </div>' +
            '  <div class="dialog-footer">' +
            '    <button class="btn btn-secondary dialog-cancel-btn">' + cancelText + '</button>' +
            '    <button class="btn ' + btnClass + ' dialog-confirm-btn">' + confirmText + '</button>' +
            '  </div>' +
            '</div>';
        document.body.appendChild(overlay);
        document.body.style.overflow = 'hidden';

        var closeDialog = function(result) {
            overlay.classList.add('closing');
            setTimeout(function() {
                if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                document.body.style.overflow = '';
                resolve(result);
            }, 150);
        };

        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeDialog(false);
        });
        overlay.querySelector('.dialog-cancel-btn').addEventListener('click', function() { closeDialog(false); });
        overlay.querySelector('.dialog-confirm-btn').addEventListener('click', function() { closeDialog(true); });

        document.addEventListener('keydown', function escHandler(e) {
            if (e.key === 'Escape') {
                closeDialog(false);
                document.removeEventListener('keydown', escHandler);
            }
        });

        setTimeout(function() {
            var btn = overlay.querySelector('.dialog-confirm-btn');
            if (btn) btn.focus();
        }, 100);
    });
}

document.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
        if (e.ctrlKey && e.key === 'k') {
            e.preventDefault();
            showCommandPalette();
        }
        if (e.ctrlKey && e.key === 's') {
            var form = e.target.closest('form');
            if (form) { e.preventDefault(); form.dispatchEvent(new Event('submit', {cancelable: true})); }
        }
        return;
    }
    if (e.ctrlKey && e.key === 'k') { e.preventDefault(); showCommandPalette(); }
    if (e.ctrlKey && e.key === 'n') {
        e.preventDefault();
        if (window.location.pathname.includes('/invoices')) window.location.href = '/invoices/new';
    }
    if (e.ctrlKey && e.key === 'e') { e.preventDefault(); window.location.href = '/expenses/new'; }
    if (e.key === 'Escape') {
        closeAllActionMenus();
    }
});

// =========================================================================
// ACCORDION TOGGLE (shared component)
// =========================================================================
function toggleAccordionSection(header) {
    var item = header.parentElement;
    var content = item.querySelector('.accordion-content');
    if (!content) return;
    var isActive = item.classList.contains('active');

    var allItems = document.querySelectorAll('.accordion-item');
    for (var i = 0; i < allItems.length; i++) {
        allItems[i].classList.remove('active');
        var c = allItems[i].querySelector('.accordion-content');
        if (c) c.style.maxHeight = null;
    }

    if (!isActive) {
        item.classList.add('active');
        content.style.maxHeight = content.scrollHeight + 'px';
    }
}

// =========================================================================
// UNIFIED TOAST NOTIFICATION SERVICE
// =========================================================================
function ensureToastContainer() {
    var container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    return container;
}

/**
 * Show a toast notification
 * @param {string} message - Message text
 * @param {string} type - 'success' | 'error' | 'warning' | 'info' (default 'info')
 * @param {string} title - Optional title
 * @param {number} duration - Duration in ms (default 5000)
 */
function showToast(message, type, title, duration) {
    type = type || 'info';
    title = title || '';
    duration = duration || 5000;
    var typeMap = {
        success: { icon: 'fa-circle-check', color: 'var(--accent-success)', cls: 'toast-success' },
        error:   { icon: 'fa-circle-exclamation', color: 'var(--accent-red)', cls: 'toast-error' },
        warning: { icon: 'fa-triangle-exclamation', color: 'var(--accent-yellow)', cls: 'toast-warning' },
        info:    { icon: 'fa-circle-info', color: 'var(--accent-emerald)', cls: '' }
    };
    var def = typeMap[type] || typeMap.info;

    var container = ensureToastContainer();
    var toast = document.createElement('div');
    toast.className = 'toast-item ' + def.cls;
    toast.style.borderLeftColor = def.color;
    toast.innerHTML =
        '<div class="toast-icon"><i class="fa-solid ' + def.icon + '" style="color:' + def.color + ';"></i></div>' +
        '<div class="toast-content">' +
        (title ? '<div class="toast-title-text">' + title + '</div>' : '') +
        '<div class="toast-message-text">' + message + '</div>' +
        '</div>' +
        '<button class="toast-close-btn" onclick="this.closest(\'.toast-item\').remove()"><i class="fa-solid fa-xmark"></i></button>';

    container.appendChild(toast);

    setTimeout(function() {
        if (toast.parentNode) {
            toast.classList.add('removing');
            setTimeout(function() {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 250);
        }
    }, duration);
}

function showCommandPalette() {
    var existing = document.getElementById('command-palette');
    if (existing) { existing.remove(); return; }
    var backdrop = document.createElement('div');
    backdrop.id = 'command-palette';
    backdrop.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:flex-start;justify-content:center;padding-top:15vh;backdrop-filter:blur(4px);';
    backdrop.onclick = function(e) { if (e.target === backdrop) backdrop.remove(); };

    var modal = document.createElement('div');
    modal.style.cssText = 'background:var(--bg-card);border:1px solid var(--border-color);border-radius:12px;width:500px;max-width:90vw;box-shadow:var(--shadow-lg);overflow:hidden;';
    modal.innerHTML = '<input id="palette-input" type="text" placeholder="Buscar página o acción..." style="width:100%;padding:14px 16px;border:none;border-bottom:1px solid var(--border-color);background:transparent;color:var(--text-primary);font-size:0.95rem;outline:none;box-sizing:border-box;" autofocus><div id="palette-results" style="max-height:300px;overflow-y:auto;padding:4px;"></div>';

    var commands = [
        { label: 'Nueva Factura', icon: 'fa-file-invoice', url: '/invoices/new', keys: 'Ctrl+N' },
        { label: 'Lista de Facturas', icon: 'fa-list', url: '/invoices' },
        { label: 'Nueva Cotización', icon: 'fa-file-signature', url: '/quotations/new' },
        { label: 'Nuevo Gasto', icon: 'fa-receipt', url: '/expenses/new', keys: 'Ctrl+E' },
        { label: 'Dashboard', icon: 'fa-house', url: '/dashboard' },
        { label: 'Lista de Clientes', icon: 'fa-users', url: '/clients' },
        { label: 'Catálogo de Cuentas', icon: 'fa-book', url: '/accounting/chart-of-accounts' },
        { label: 'Entradas de Diario', icon: 'fa-pen', url: '/accounting/journal-entries' },
        { label: 'Períodos Fiscales', icon: 'fa-calendar', url: '/accounting/fiscal-periods' },
        { label: 'Ratios Financieros', icon: 'fa-chart-pie', url: '/reports/financial-ratios' },
        { label: 'POS', icon: 'fa-cash-register', url: '/pos' },
    ];

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    var input = document.getElementById('palette-input');
    var results = document.getElementById('palette-results');

    function renderResults(filter) {
        var filtered = commands.filter(function(c) {
            return !filter || c.label.toLowerCase().includes(filter.toLowerCase());
        });
        results.innerHTML = filtered.map(function(c) {
            return '<div class="palette-item" style="display:flex;align-items:center;gap:10px;padding:8px 14px;cursor:pointer;font-size:0.85rem;color:var(--text-primary);border-radius:6px;" data-url="'+c.url+'" onmouseover="this.style.background=\'var(--bg-nav-hover)\'" onmouseout="this.style.background=\'transparent\'">' +
                '<i class="fa-solid '+c.icon+'" style="width:18px;text-align:center;opacity:0.6;"></i>' +
                '<span style="flex:1;">'+c.label+'</span>' +
                (c.keys ? '<span style="font-size:0.65rem;color:var(--text-muted);">'+c.keys+'</span>' : '') +
                '</div>';
        }).join('');
        results.querySelectorAll('.palette-item').forEach(function(item) {
            item.onclick = function() { window.location.href = this.dataset.url; };
        });
    }
    renderResults('');
    input.addEventListener('input', function() { renderResults(this.value); });
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') backdrop.remove();
    });
}
