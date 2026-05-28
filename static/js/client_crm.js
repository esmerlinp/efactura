/* =========================================================================
   CRM CLIENTES E INTEGRACIÓN MEGAPLUS DGII - CLIENT_CRM JS
   ========================================================================= */

document.addEventListener('DOMContentLoaded', () => {
    const rncInput = document.getElementById('rnc-input');
    const nameInput = document.getElementById('razon-social-input');
    const lookupStatus = document.getElementById('lookup-status');
    const lookupIcon = document.getElementById('lookup-icon');

    if (rncInput) {
        // Escuchar el evento input con un sutil debounce o longitud exacta
        rncInput.addEventListener('input', async (e) => {
            const rawVal = e.target.value;
            const cleanedVal = rawVal.replace(/[^0-9]/g, '');
            
            // Actualizar el valor visual sin guiones para comodidad del usuario
            e.target.value = rawVal.replace(/[^0-9-]/g, '');

            if (cleanedVal.length === 9 || cleanedVal.length === 11) {
                // Ejecutar búsqueda asíncrona en el padrón a través de Megaplus
                showStatusLoading();

                try {
                    const response = await fetch(`/api/rnc-lookup?rnc=${cleanedVal}`);
                    const data = await response.json();

                    if (response.ok && !data.error) {
                        showStatusSuccess(data.razon_social);
                        if (nameInput) {
                            nameInput.value = data.razon_social;
                            
                            // Animación de entrada suave del valor autocompletado
                            nameInput.style.border = '1px solid var(--accent-emerald)';
                            nameInput.style.boxShadow = '0 0 10px rgba(16, 185, 129, 0.15)';
                            setTimeout(() => {
                                nameInput.style.border = '';
                                nameInput.style.boxShadow = '';
                            }, 1500);
                        }
                    } else {
                        showStatusError(data.message || 'RNC no encontrado en DGII.');
                    }
                } catch (err) {
                    showStatusError('Error de red al consultar padrón.');
                }
            } else {
                resetStatus();
            }
        });
    }

    function showStatusLoading() {
        if (lookupStatus && lookupIcon) {
            lookupStatus.textContent = 'Consultando padrón DGII en tiempo real...';
            lookupStatus.style.color = 'var(--text-secondary)';
            lookupIcon.className = 'fa-solid fa-circle-notch fa-spin';
            lookupIcon.style.color = 'var(--accent-purple)';
        }
    }

    function showStatusSuccess(razonSocial) {
        if (lookupStatus && lookupIcon) {
            lookupStatus.textContent = '✓ Verificado en Padrón Oficial DGII.';
            lookupStatus.style.color = 'var(--accent-emerald)';
            lookupIcon.className = 'fa-solid fa-circle-check';
            lookupIcon.style.color = 'var(--accent-emerald)';
        }
    }

    function showStatusError(msg) {
        if (lookupStatus && lookupIcon) {
            lookupStatus.textContent = `✗ ${msg}`;
            lookupStatus.style.color = 'var(--accent-red)';
            lookupIcon.className = 'fa-solid fa-circle-exclamation';
            lookupIcon.style.color = 'var(--accent-red)';
        }
    }

    function resetStatus() {
        if (lookupStatus && lookupIcon) {
            lookupStatus.textContent = 'Ingresa 9 dígitos para RNC o 11 dígitos para Cédula.';
            lookupStatus.style.color = 'var(--text-muted)';
            lookupIcon.className = 'fa-solid fa-fingerprint';
            lookupIcon.style.color = 'var(--text-muted)';
        }
    }
});
