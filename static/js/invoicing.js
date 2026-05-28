/* =========================================================================
   CÁLCULOS ROBUSTOS Y MESA DE FACTURACIÓN CON BUSQUEDA AVANZADA - INVOICING JS
   ========================================================================= */

document.addEventListener('DOMContentLoaded', () => {
    const itemsTableBody = document.getElementById('invoice-items-body');
    const btnAddItem = document.getElementById('btn-add-item');
    const ecfTypeSelect = document.getElementById('ecf-type-select');
    
    // Elementos de resumen global
    const lblSubtotalRaw = document.getElementById('lbl-subtotal-raw');
    const lblDiscount = document.getElementById('lbl-discount');
    const lblSubtotal = document.getElementById('lbl-subtotal');
    const lblITBIS = document.getElementById('lbl-itbis');
    const lblTotal = document.getElementById('lbl-total');
    const lblRetainedISR = document.getElementById('lbl-retained-isr');
    const lblRetainedITBIS = document.getElementById('lbl-retained-itbis');
    const lblNetPayable = document.getElementById('lbl-net-payable');

    // Inputs de tasas de retención y descuento global
    const discountGlobalInput = document.getElementById('discount-global');
    const isrRateSelect = document.getElementById('isr-rate-select');
    const itbisRateSelect = document.getElementById('itbis-rate-select');
    
    const clientRncInput = document.getElementById('client-rnc-input');
    const clientWarning = document.getElementById('client-warning');
    const submitBtn = document.getElementById('submit-invoice-btn');

    // =========================================================================
    // CARGAR Y PARSAR CATÁLOGOS LOCALES (PARA EVITAR HITS DE BASE DE DATOS)
    // =========================================================================
    let catalogItems = [];
    const catalogDataElement = document.getElementById('catalog-data-json');
    if (catalogDataElement) {
        catalogItems = JSON.parse(catalogDataElement.textContent);
    }

    let crmClients = [];
    const clientsDataElement = document.getElementById('clients-data-json');
    if (clientsDataElement) {
        crmClients = JSON.parse(clientsDataElement.textContent);
    }

    // =========================================================================
    // GESTIÓN DEL MODAL DE CLIENTES
    // =========================================================================
    const clientSearchModal = document.getElementById('client-search-modal');
    const clientSearchInput = document.getElementById('client-search-input');
    const btnOpenClientModal = document.getElementById('btn-open-client-modal');
    const btnCloseClientModal = document.getElementById('btn-close-client-modal');
    const clientModalBackdrop = document.getElementById('client-modal-backdrop');
    const modalClientFilter = document.getElementById('modal-client-filter');
    const modalClientListBody = document.getElementById('modal-client-list-body');
    const clientIdHidden = document.getElementById('client-id-hidden');

    const renderClients = (filterText = '') => {
        const query = filterText.toLowerCase().trim();
        const filtered = crmClients.filter(c => 
            c.razonSocial.toLowerCase().includes(query) ||
            (c.rnc || '').toLowerCase().includes(query) ||
            (c.email || '').toLowerCase().includes(query) ||
            (c.phone || '').toLowerCase().includes(query)
        );

        modalClientListBody.innerHTML = filtered.map(c => `
            <tr style="border-bottom: 1px solid var(--border-color);">
                <td style="padding: 14px 16px; vertical-align: middle;">
                    <div style="font-weight: 600; font-size: 0.95rem; color: var(--text-primary); line-height: 1.3; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${c.razonSocial}">
                        ${c.razonSocial}
                    </div>
                    <div style="font-family: monospace; font-size: 0.78rem; color: var(--text-muted); margin-top: 4px; display: flex; align-items: center; gap: 6px;">
                        <i class="fa-solid fa-id-card" style="font-size: 0.72rem; opacity: 0.7;"></i>
                        <span>RNC: ${c.rnc || 'Consumidor Final'}</span>
                    </div>
                </td>
                <td style="padding: 14px 16px; vertical-align: middle;">
                    <div style="font-size: 0.85rem; color: var(--text-secondary); display: flex; align-items: center; gap: 6px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${c.email || ''}">
                        <i class="fa-solid fa-envelope" style="font-size: 0.75rem; color: var(--text-muted); width: 14px;"></i>
                        <span>${c.email || 'No especificado'}</span>
                    </div>
                    <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 4px; display: flex; align-items: center; gap: 6px;">
                        <i class="fa-solid fa-phone" style="font-size: 0.75rem; color: var(--text-muted); width: 14px;"></i>
                        <span>${c.phone || 'No especificado'}</span>
                    </div>
                </td>
                <td style="padding: 14px 16px; text-align: center; vertical-align: middle;">
                    <button type="button" class="btn btn-primary btn-select-client" data-id="${c.id}" data-name="${c.razonSocial}" data-rnc="${c.rnc || ''}" style="height: 36px; padding: 0 16px; font-size: 0.82rem; display: inline-flex; align-items: center; gap: 6px; border-radius: var(--radius-sm); border: none; cursor: pointer; transition: all var(--transition-fast);">
                        <i class="fa-solid fa-check" style="font-size: 0.8rem;"></i> Seleccionar
                    </button>
                </td>
            </tr>
        `).join('');

        // Vincular clics de selección
        modalClientListBody.querySelectorAll('.btn-select-client').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = btn.getAttribute('data-id');
                const name = btn.getAttribute('data-name');
                const rnc = btn.getAttribute('data-rnc');

                clientIdHidden.value = id;
                clientSearchInput.value = `${name} (${rnc || 'Consumidor Final'})`;
                if (clientRncInput) clientRncInput.value = rnc;
                
                closeClientModal();
                validateTaxConstraints();
            });
        });
    };

    const openClientModal = () => {
        clientSearchModal.style.display = 'flex';
        modalClientFilter.value = '';
        renderClients();
        modalClientFilter.focus();
    };

    const closeClientModal = () => {
        clientSearchModal.style.display = 'none';
    };

    if (clientSearchInput) clientSearchInput.addEventListener('click', openClientModal);
    if (btnOpenClientModal) btnOpenClientModal.addEventListener('click', openClientModal);
    if (btnCloseClientModal) btnCloseClientModal.addEventListener('click', closeClientModal);
    if (clientModalBackdrop) clientModalBackdrop.addEventListener('click', closeClientModal);
    if (modalClientFilter) modalClientFilter.addEventListener('input', (e) => renderClients(e.target.value));

    // =========================================================================
    // GESTIÓN DEL MODAL DE PRODUCTOS
    // =========================================================================
    let activeProductRow = null;
    const productSearchModal = document.getElementById('product-search-modal');
    const btnCloseProductModal = document.getElementById('btn-close-product-modal');
    const productModalBackdrop = document.getElementById('product-modal-backdrop');
    const modalProductFilter = document.getElementById('modal-product-filter');
    const modalProductListBody = document.getElementById('modal-product-list-body');

    const renderProducts = (filterText = '') => {
        const query = filterText.toLowerCase().trim();
        const filtered = catalogItems.filter(p => 
            p.name.toLowerCase().includes(query) ||
            (p.code || '').toLowerCase().includes(query)
        );

        modalProductListBody.innerHTML = filtered.map(p => `
            <tr>
                <td style="font-family: monospace; font-weight: 600;">${p.code || 'N/A'}</td>
                <td>
                    <div style="font-weight: 600;">${p.name}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">${p.type === 'service' ? 'Servicio' : 'Producto'}</div>
                </td>
                <td style="text-align: right; font-weight: 600;">${formatCurrencyDOP(p.price)}</td>
                <td>${parseFloat(p.itbisRate * 100)}%</td>
                <td style="text-align: center;">
                    <button type="button" class="btn btn-primary modal-row-btn btn-select-product" data-id="${p.id}" data-name="${p.name}" data-price="${p.price}" data-itbis="${p.itbisRate}" data-code="${p.code}">
                        <i class="fa-solid fa-check"></i> Seleccionar
                    </button>
                </td>
            </tr>
        `).join('');

        // Vincular clics de selección de producto
        modalProductListBody.querySelectorAll('.btn-select-product').forEach(btn => {
            btn.addEventListener('click', () => {
                if (activeProductRow) {
                     const id = btn.getAttribute('data-id');
                     const name = btn.getAttribute('data-name');
                     const price = btn.getAttribute('data-price');
                     const itbis = btn.getAttribute('data-itbis');
                     const code = btn.getAttribute('data-code');

                     const searchInput = activeProductRow.querySelector('.item-catalog-search-input');
                     const catalogIdHidden = activeProductRow.querySelector('.item-catalog-id-hidden');
                     const nameInput = activeProductRow.querySelector('.item-name-input');
                     const priceInput = activeProductRow.querySelector('.item-price-input');
                     const itbisSelect = activeProductRow.querySelector('.item-itbis-select');

                     catalogIdHidden.value = id;
                     searchInput.value = `${name} (${code || 'N/A'})`;
                     nameInput.value = name;
                     priceInput.value = parseFloat(price).toFixed(2);
                     itbisSelect.value = itbis;

                     closeProductModal();
                     recalculateTotals();
                }
            });
        });
    };

    const openProductModal = () => {
        productSearchModal.style.display = 'flex';
        modalProductFilter.value = '';
        renderProducts();
        modalProductFilter.focus();
    };

    const closeProductModal = () => {
        productSearchModal.style.display = 'none';
        activeProductRow = null;
    };

    if (btnCloseProductModal) btnCloseProductModal.addEventListener('click', closeProductModal);
    if (productModalBackdrop) productModalBackdrop.addEventListener('click', closeProductModal);
    if (modalProductFilter) modalProductFilter.addEventListener('input', (e) => renderProducts(e.target.value));

    // =========================================================================
    // AGREGAR PARTIDA DINÁMICA A LA TABLA
    // =========================================================================
    if (btnAddItem) {
        btnAddItem.addEventListener('click', () => {
            const rowIndex = itemsTableBody.children.length;
            const newRow = document.createElement('tr');
            newRow.className = 'item-row animate-fade-in';
            
            newRow.innerHTML = `
                <td>
                    <div style="position: relative; display: flex; gap: 6px; width: 100%;">
                        <input type="text" class="form-input item-catalog-search-input" placeholder="-- Buscar en Catálogo --" readonly style="cursor: pointer; width: 100%; text-overflow: ellipsis; white-space: nowrap; overflow: hidden;">
                        <input type="hidden" class="item-catalog-id-hidden" name="items[${rowIndex}][catalog_id]">
                        <button type="button" class="btn btn-secondary btn-search-product" style="padding: 8px 10px;" title="Buscar Producto">
                            <i class="fa-solid fa-magnifying-glass" style="font-size: 0.8rem;"></i>
                        </button>
                    </div>
                </td>
                <td>
                    <input type="text" class="form-input item-name-input" name="items[${rowIndex}][name]" required style="width: 100%;">
                </td>
                <td>
                    <input type="number" class="form-input item-price-input" name="items[${rowIndex}][price]" step="0.01" value="0.00" required style="width: 100%; text-align: right;">
                </td>
                <td>
                    <input type="number" class="form-input item-qty-input" name="items[${rowIndex}][quantity]" min="1" value="1" required style="width: 100%; text-align: center;">
                </td>
                <td>
                    <select class="form-select item-itbis-select" name="items[${rowIndex}][itbisRate]" style="width: 100%;">
                        <option value="0.18" selected>18%</option>
                        <option value="0.16">16%</option>
                        <option value="0.0">Exento (0%)</option>
                    </select>
                </td>
                <td>
                    <input type="number" class="form-input item-discount-input" name="items[${rowIndex}][discountRate]" step="0.01" min="0" max="1" value="0.00" style="width: 100%; text-align: right;">
                </td>
                <td style="text-align: right; vertical-align: middle;">
                    <strong class="item-total-label">RD$ 0.00</strong>
                </td>
                <td style="text-align: center; vertical-align: middle;">
                    <button type="button" class="btn btn-danger btn-remove-row" style="padding: 8px 12px;"><i class="fa-solid fa-trash-can"></i></button>
                </td>
            `;
            
            itemsTableBody.appendChild(newRow);
            bindRowEvents(newRow);
            recalculateTotals();
        });
    }

    // =========================================================================
    // VINCULAR EVENTOS A FILA
    // =========================================================================
    function bindRowEvents(row) {
        const searchInput = row.querySelector('.item-catalog-search-input');
        const searchBtn = row.querySelector('.btn-search-product');
        const nameInput = row.querySelector('.item-name-input');
        const priceInput = row.querySelector('.item-price-input');
        const qtyInput = row.querySelector('.item-qty-input');
        const itbisSelect = row.querySelector('.item-itbis-select');
        const discountInput = row.querySelector('.item-discount-input');
        const removeBtn = row.querySelector('.btn-remove-row');

        // Al hacer clic para buscar producto
        const openProductModalForRow = () => {
            activeProductRow = row;
            openProductModal();
        };

        if (searchInput) searchInput.addEventListener('click', openProductModalForRow);
        if (searchBtn) searchBtn.addEventListener('click', openProductModalForRow);

        // Inputs cambiantes
        [priceInput, qtyInput, itbisSelect, discountInput].forEach(input => {
            if (input) {
                input.addEventListener('input', recalculateTotals);
            }
        });

        // Borrar fila
        if (removeBtn) {
            removeBtn.addEventListener('click', () => {
                row.remove();
                realignRowIndexes();
                recalculateTotals();
            });
        }
    }

    // =========================================================================
    // RE-ALINEAR ÍNDICES TRAS BORRAR FILA
    // =========================================================================
    function realignRowIndexes() {
        const rows = itemsTableBody.querySelectorAll('.item-row');
        rows.forEach((row, i) => {
            row.querySelector('.item-catalog-id-hidden').name = `items[${i}][catalog_id]`;
            row.querySelector('.item-name-input').name = `items[${i}][name]`;
            row.querySelector('.item-price-input').name = `items[${i}][price]`;
            row.querySelector('.item-qty-input').name = `items[${i}][quantity]`;
            row.querySelector('.item-itbis-select').name = `items[${i}][itbisRate]`;
            row.querySelector('.item-discount-input').name = `items[${i}][discountRate]`;
        });
    }

    // =========================================================================
    // RECALCULAR TOTALES DE FACTURACIÓN (LEY 32-23)
    // =========================================================================
    function recalculateTotals() {
        let subtotalRaw = 0.0;
        let totalDiscount = 0.0;
        let totalITBIS = 0.0;
        
        const rows = itemsTableBody.querySelectorAll('.item-row');
        
        rows.forEach(row => {
            const price = parseFloat(row.querySelector('.item-price-input').value) || 0.0;
            const qty = parseInt(row.querySelector('.item-qty-input').value) || 1;
            const itbisRate = parseFloat(row.querySelector('.item-itbis-select').value) || 0.0;
            const itemDiscRate = parseFloat(row.querySelector('.item-discount-input').value) || 0.0;
            
            const rowSubtotalRaw = price * qty;
            const rowDiscount = rowSubtotalRaw * itemDiscRate;
            const rowSubtotal = rowSubtotalRaw - rowDiscount;
            const rowITBIS = rowSubtotal * itbisRate;
            const rowTotal = rowSubtotal + rowITBIS;
            
            subtotalRaw += rowSubtotalRaw;
            totalDiscount += rowDiscount;
            totalITBIS += rowITBIS;
            
            row.querySelector('.item-total-label').textContent = formatCurrencyDOP(rowTotal);
        });

        const globalDiscRate = parseFloat(discountGlobalInput.value) || 0.0;
        const globalDiscount = (subtotalRaw - totalDiscount) * globalDiscRate;
        totalDiscount += globalDiscount;

        const subtotal = subtotalRaw - totalDiscount;

        if (globalDiscRate > 0.0) {
            totalITBIS = totalITBIS * (1.0 - globalDiscRate);
        }

        const total = subtotal + totalITBIS;

        const isrRate = parseFloat(isrRateSelect.value) || 0.0;
        const itbisRetRate = parseFloat(itbisRateSelect.value) || 0.0;

        const retainedISR = subtotal * isrRate;
        const retainedITBIS = totalITBIS * itbisRetRate;
        const netPayable = Math.max(0.0, total - retainedISR - retainedITBIS);

        lblSubtotalRaw.textContent = formatCurrencyDOP(subtotalRaw);
        lblDiscount.textContent = formatCurrencyDOP(totalDiscount);
        lblSubtotal.textContent = formatCurrencyDOP(subtotal);
        lblITBIS.textContent = formatCurrencyDOP(totalITBIS);
        lblTotal.textContent = formatCurrencyDOP(total);
        lblRetainedISR.textContent = formatCurrencyDOP(retainedISR);
        lblRetainedITBIS.textContent = formatCurrencyDOP(retainedITBIS);
        lblNetPayable.textContent = formatCurrencyDOP(netPayable);
    }

    [discountGlobalInput, isrRateSelect, itbisRateSelect].forEach(control => {
        if (control) {
            control.addEventListener('input', recalculateTotals);
        }
    });

    if (ecfTypeSelect) {
        ecfTypeSelect.addEventListener('change', validateTaxConstraints);
    }

    if (clientRncInput) {
        clientRncInput.addEventListener('input', validateTaxConstraints);
    }

    function validateTaxConstraints() {
        if (!ecfTypeSelect) return;
        const type = ecfTypeSelect.value;
        const cleanRnc = (clientRncInput ? clientRncInput.value : '').replace(/[^0-9]/g, '');
        const submitBtnCobrar = document.getElementById('submit-invoice-cobrar-btn');

        if (type.includes('E31')) {
            if (cleanRnc.length !== 9) {
                clientWarning.textContent = '⚠️ Para Crédito Fiscal (E31) se requiere un RNC corporativo de 9 dígitos.';
                clientWarning.style.display = 'block';
                submitBtn.disabled = true;
                submitBtn.style.opacity = '0.5';
                if (submitBtnCobrar) {
                    submitBtnCobrar.disabled = true;
                    submitBtnCobrar.style.opacity = '0.5';
                }
            } else {
                clientWarning.style.display = 'none';
                submitBtn.disabled = false;
                submitBtn.style.opacity = '1';
                if (submitBtnCobrar) {
                    submitBtnCobrar.disabled = false;
                    submitBtnCobrar.style.opacity = '1';
                }
            }
        } else {
            clientWarning.style.display = 'none';
            submitBtn.disabled = false;
            submitBtn.style.opacity = '1';
            if (submitBtnCobrar) {
                submitBtnCobrar.disabled = false;
                submitBtnCobrar.style.opacity = '1';
            }
        }
    }

    // Inicializar primera fila si la tabla está vacía al cargar
    if (itemsTableBody) {
        if (itemsTableBody.children.length === 0 && btnAddItem) {
            btnAddItem.click();
        } else {
            const existingRows = itemsTableBody.querySelectorAll('.item-row');
            existingRows.forEach(row => bindRowEvents(row));
            if (existingRows.length > 0) {
                recalculateTotals();
            }
        }
    }
});

// Helper para formatear valores monetarios de DOP en la UI
function formatCurrencyDOP(amount) {
    return new Intl.NumberFormat('es-DO', {
        style: 'currency',
        currency: 'DOP'
    }).format(amount);
}
