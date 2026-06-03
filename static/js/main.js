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
    
    sidebarHeaders.forEach(header => {
        header.addEventListener('click', () => {
            // Si la barra lateral entera está colapsada (minimizada), no hacer nada
            if (mainAppContainer && mainAppContainer.classList.contains('sidebar-collapsed')) {
                return;
            }
            
            const section = header.closest('.sidebar-section');
            if (!section) return;
            
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
                // EXPANDIR
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
});

// Helper para formatear valores monetarios de DOP en la UI
function formatCurrencyDOP(amount) {
    return new Intl.NumberFormat('es-DO', {
        style: 'currency',
        currency: 'DOP'
    }).format(amount);
}
