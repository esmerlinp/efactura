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

    let priceListPrices = {};
    const priceListDataElement = document.getElementById('price-list-prices-json');
    if (priceListDataElement) {
        try {
            priceListPrices = JSON.parse(priceListDataElement.textContent);
        } catch(e) {
            priceListPrices = {};
        }
    }

    let activePriceListId = '';

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
                    <div style="font-weight: 500; font-size: 0.95rem; color: var(--text-primary); line-height: 1.3; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${c.razonSocial}">
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

                // Establecer la lista de precios activa según el cliente seleccionado
                const client = crmClients.find(c => c.id === id);
                activePriceListId = (client && client.priceListId) || '';

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

    if (btnOpenClientModal) btnOpenClientModal.addEventListener('click', openClientModal);
    if (btnCloseClientModal) btnCloseClientModal.addEventListener('click', closeClientModal);
    if (clientSearchModal) {
        clientSearchModal.addEventListener('click', (e) => {
            if (e.target === clientSearchModal) closeClientModal();
        });
    }
    if (modalClientFilter) modalClientFilter.addEventListener('input', (e) => renderClients(e.target.value));

    // =========================================================================
    // GESTIÓN DEL MODAL DE REGISTRO DE NUEVO CLIENTE (AJAX)
    // =========================================================================
    const clientCreateModal = document.getElementById('client-create-modal');
    const clientCreateModalBackdrop = document.getElementById('client-create-modal-backdrop');
    const btnOpenCreateClientModal = document.getElementById('btn-create-client-modal');
    const btnCloseCreateClientModal = document.getElementById('btn-close-create-client-modal');
    const btnCancelCreateClient = document.getElementById('btn-cancel-create-client');
    const btnSaveNewClient = document.getElementById('btn-save-new-client');
    const btnSaveNewClientLabel = document.getElementById('btn-save-new-client-label');
    const createClientAlert = document.getElementById('create-client-alert');

    const openCreateClientModal = () => {
        if (!clientCreateModal) return;
        // Reset campos del modal
        const fields = ['new-client-rnc', 'new-client-razon', 'new-client-email', 'new-client-telefono', 'new-client-direccion'];
        fields.forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
        if (createClientAlert) { createClientAlert.style.display = 'none'; createClientAlert.textContent = ''; }
        if (btnSaveNewClientLabel) btnSaveNewClientLabel.textContent = 'Guardar Cliente';
        if (btnSaveNewClient) btnSaveNewClient.disabled = false;
        clientCreateModal.style.display = 'flex';
        const rncField = document.getElementById('new-client-rnc');
        if (rncField) rncField.focus();
    };

    const closeCreateClientModal = () => {
        if (clientCreateModal) clientCreateModal.style.display = 'none';
    };

    const showCreateAlert = (msg, isError = false) => {
        if (!createClientAlert) return;
        createClientAlert.textContent = msg;
        createClientAlert.style.display = 'block';
        createClientAlert.style.background = isError ? 'rgba(239,68,68,0.12)' : 'rgba(16,185,129,0.12)';
        createClientAlert.style.color = isError ? '#dc2626' : '#059669';
        createClientAlert.style.border = isError ? '1px solid rgba(239,68,68,0.3)' : '1px solid rgba(16,185,129,0.3)';
    };

    if (btnOpenCreateClientModal) btnOpenCreateClientModal.addEventListener('click', openCreateClientModal);
    if (btnCloseCreateClientModal) btnCloseCreateClientModal.addEventListener('click', closeCreateClientModal);
    if (btnCancelCreateClient) btnCancelCreateClient.addEventListener('click', closeCreateClientModal);
    if (clientCreateModal) {
        clientCreateModal.addEventListener('click', (e) => {
            if (e.target === clientCreateModal) closeCreateClientModal();
        });
    }

    if (btnSaveNewClient) {
        btnSaveNewClient.addEventListener('click', async () => {
            const rnc = (document.getElementById('new-client-rnc')?.value || '').trim();
            const razonSocial = (document.getElementById('new-client-razon')?.value || '').trim();
            const email = (document.getElementById('new-client-email')?.value || '').trim();
            const telefono = (document.getElementById('new-client-telefono')?.value || '').trim();
            const direccion = (document.getElementById('new-client-direccion')?.value || '').trim();

            if (!razonSocial) {
                showCreateAlert('La Razón Social es obligatoria.', true);
                document.getElementById('new-client-razon')?.focus();
                return;
            }

            // Indicador de carga
            btnSaveNewClient.disabled = true;
            if (btnSaveNewClientLabel) btnSaveNewClientLabel.textContent = 'Guardando...';
            if (createClientAlert) createClientAlert.style.display = 'none';

            try {
                const response = await fetch('/clients/ajax_create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ rnc, razonSocial, email, telefono, direccion })
                });

                const result = await response.json();

                if (result.success) {
                    const newClient = result.client;

                    // Agregar cliente al array en memoria para buscarlo inmediatamente
                    crmClients.push({
                        id: newClient.id,
                        rnc: newClient.rnc,
                        razonSocial: newClient.razonSocial,
                        email: newClient.email,
                        telefono: newClient.telefono,
                        direccion: newClient.direccion,
                        phone: newClient.telefono
                    });

                    // Autoseleccionar en el formulario de factura
                    if (clientIdHidden) clientIdHidden.value = newClient.id;
                    if (clientSearchInput) {
                        clientSearchInput.value = `${newClient.razonSocial} (${newClient.rnc || 'Consumidor Final'})`;
                    }
                    if (clientRncInput) clientRncInput.value = newClient.rnc || '';

                    showCreateAlert(`✓ Cliente "${newClient.razonSocial}" registrado y seleccionado.`, false);
                    setTimeout(() => {
                        closeCreateClientModal();
                        validateTaxConstraints && validateTaxConstraints();
                    }, 1200);
                } else {
                    showCreateAlert(result.error || 'Error al registrar el cliente.', true);
                    if (btnSaveNewClientLabel) btnSaveNewClientLabel.textContent = 'Guardar Cliente';
                    btnSaveNewClient.disabled = false;
                }
            } catch (err) {
                showCreateAlert('Error de conexión. Verifique su red e intente de nuevo.', true);
                if (btnSaveNewClientLabel) btnSaveNewClientLabel.textContent = 'Guardar Cliente';
                btnSaveNewClient.disabled = false;
            }
        });
    }



    // =========================================================================
    // GESTIÓN DEL MODAL DE PRODUCTOS
    // =========================================================================
    let activeProductRow = null;
    const productSearchModal = document.getElementById('product-search-modal');
    const btnCloseProductModal = document.getElementById('btn-close-product-modal');
    const productModalBackdrop = document.getElementById('product-modal-backdrop');
    const modalProductFilter = document.getElementById('modal-product-filter');
    const modalProductListBody = document.getElementById('modal-product-list-body');

    const getPriceListPrice = (itemId) => {
        if (!activePriceListId) return null;
        const listPrices = priceListPrices[activePriceListId];
        if (!listPrices) return null;
        const itemPrice = listPrices[itemId];
        return itemPrice ? itemPrice.price : null;
    };

    const renderProducts = (filterText = '') => {
        const query = filterText.toLowerCase().trim();
        const filtered = catalogItems.filter(p =>
            p.name.toLowerCase().includes(query) ||
            (p.code || '').toLowerCase().includes(query)
        );

        modalProductListBody.innerHTML = filtered.map(p => {
            const listPrice = getPriceListPrice(p.id);
            const displayPrice = listPrice !== null ? listPrice : p.price;
            const priceLabel = listPrice !== null
                ? formatCurrencyDOP(listPrice) + ' <span style="font-size:0.7rem;color:var(--accent-emerald);font-weight:400;">(Lista)</span>'
                : formatCurrencyDOP(p.price);
            return `
            <tr class="product-select-row" data-id="${p.id}" data-name="${p.name}" data-price="${displayPrice}" data-itbis="${p.itbisRate}" data-code="${p.code || ''}" style="cursor:pointer;transition:background 0.15s;">
                <td style="font-family: monospace; font-weight: 500;">${p.code || 'N/A'}</td>
                <td>
                    <div style="font-weight: 500;">${p.name}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">${p.type === 'service' ? 'Servicio' : 'Producto'}</div>
                </td>
                <td style="text-align: right; font-weight: 500;">${priceLabel}</td>
                <td style="text-align:center;">${parseFloat(p.itbisRate * 100)}%</td>
            </tr>
        `}).join('');

        modalProductListBody.querySelectorAll('.product-select-row').forEach(row => {
            row.addEventListener('click', () => {
                if (!activeProductRow) return;
                const id = row.getAttribute('data-id');
                const name = row.getAttribute('data-name');
                const price = row.getAttribute('data-price');
                const itbis = row.getAttribute('data-itbis');
                const code = row.getAttribute('data-code');

                let duplicateRow = null;
                const rows = itemsTableBody.querySelectorAll('.item-row');
                rows.forEach(r => {
                    if (r !== activeProductRow) {
                        const existingIdInput = r.querySelector('.item-catalog-id-hidden');
                        if (existingIdInput && existingIdInput.value === id) {
                            duplicateRow = r;
                        }
                    }
                });

                if (duplicateRow) {
                    const qtyInput = duplicateRow.querySelector('.item-qty-input');
                    if (qtyInput) {
                        qtyInput.value = parseInt(qtyInput.value || 0) + 1;
                    }
                    if (rows.length > 1) {
                        activeProductRow.remove();
                        realignRowIndexes();
                    } else {
                        const searchInput = activeProductRow.querySelector('.item-catalog-search-input');
                        const catalogIdHidden = activeProductRow.querySelector('.item-catalog-id-hidden');
                        const nameInput = activeProductRow.querySelector('.item-name-input');
                        const priceInput = activeProductRow.querySelector('.item-price-input');
                        const itbisSelect = activeProductRow.querySelector('.item-itbis-select');
                        if (catalogIdHidden) catalogIdHidden.value = '';
                        if (searchInput) searchInput.value = '';
                        if (nameInput) nameInput.value = '';
                        if (priceInput) priceInput.value = '0.00';
                        if (itbisSelect) itbisSelect.value = '0.18';
                    }
                    closeProductModal();
                    recalculateTotals();
                    return;
                }

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

                const product = catalogItems.find(p => p.id === id || p.code === code);
                if (product) {
                    activeProductRow.dataset.codigoImpuesto = product.codigoImpuesto || "";
                    activeProductRow.dataset.tasaImpuestoAdicional = product.tasaImpuestoAdicional || 0.0;
                    activeProductRow.dataset.gradosAlcohol = product.gradosAlcohol || 0.0;
                    activeProductRow.dataset.cantidadReferencia = product.cantidadReferencia || 0.0;
                    activeProductRow.dataset.subcantidad = product.subcantidad || 0.0;
                    activeProductRow.dataset.precioReferencia = product.precioReferencia || 0.0;
                } else {
                    activeProductRow.dataset.codigoImpuesto = "";
                }

                closeProductModal();
                recalculateTotals();
            });
            row.addEventListener('mouseenter', () => {
                row.style.background = 'var(--hover-bg, rgba(0,0,0,0.04))';
            });
            row.addEventListener('mouseleave', () => {
                row.style.background = '';
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
    if (productSearchModal) {
        productSearchModal.addEventListener('click', (e) => {
            if (e.target === productSearchModal) closeProductModal();
        });
    }
    if (modalProductFilter) modalProductFilter.addEventListener('input', (e) => renderProducts(e.target.value));

    // =========================================================================
    // AUTOCOMPLETADO INLINE PARA CLIENTE (sin necesidad de abrir modal)
    // =========================================================================
    let clientAutocompleteDropdown = null;
    function getOrCreateClientDropdown() {
        if (!clientAutocompleteDropdown) {
            clientAutocompleteDropdown = document.createElement('div');
            clientAutocompleteDropdown.className = 'autocomplete-dropdown';
            clientAutocompleteDropdown.id = 'client-autocomplete-dropdown';
            clientAutocompleteDropdown.style.cssText = 'display:none; position:fixed; z-index:1050; max-height:280px; overflow-y:auto; background:var(--bg-card,#ffffff); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px); border:1px solid var(--border-color); border-radius:var(--radius-sm,8px); box-shadow:0 12px 40px rgba(0,0,0,0.18); font-size:0.9rem;';
            document.body.appendChild(clientAutocompleteDropdown);
        }
        return clientAutocompleteDropdown;
    }

    function positionClientDropdown() {
        const dropdown = getOrCreateClientDropdown();
        if (!clientSearchInput) return;
        const rect = clientSearchInput.getBoundingClientRect();
        const width = rect.width;
        dropdown.style.width = `${width}px`;
        dropdown.style.left = `${rect.left}px`;
        if (rect.bottom + 280 > window.innerHeight && rect.top > 280) {
            dropdown.style.top = `${rect.top - 284}px`;
        } else {
            dropdown.style.top = `${rect.bottom + 4}px`;
        }
    }

    const selectClient = (id, name, rnc, client) => {
        if (clientIdHidden) clientIdHidden.value = id;
        if (clientSearchInput) {
            clientSearchInput.value = rnc ? `${name} (${rnc})` : name;
        }
        if (clientRncInput) clientRncInput.value = rnc || '';
        activePriceListId = (client && client.priceListId) || '';
        const dropdown = getOrCreateClientDropdown();
        dropdown.style.display = 'none';
        if (typeof validateTaxConstraints === 'function') validateTaxConstraints();
    };

    if (clientSearchInput) {
        // Allow typing directly — no longer readonly
        clientSearchInput.removeAttribute('readonly');
        clientSearchInput.style.cursor = 'text';
        clientSearchInput.setAttribute('placeholder', 'Buscar cliente por nombre, RNC o email...');
        clientSearchInput.setAttribute('autocomplete', 'off');

        // Evitar que el blur cierre el dropdown cuando se hace clic en él
        const cd = getOrCreateClientDropdown();
        cd.addEventListener('mousedown', (ev) => {
            ev.preventDefault();
        });

        clientSearchInput.addEventListener('keyup', (e) => {
            const query = clientSearchInput.value.toLowerCase().trim();
            const dropdown = getOrCreateClientDropdown();
            if (query.length < 1) {
                dropdown.style.display = 'none';
                return;
            }
            const filtered = crmClients.filter(c =>
                (c.razonSocial || '').toLowerCase().includes(query) ||
                (c.rnc || '').toLowerCase().includes(query) ||
                (c.email || '').toLowerCase().includes(query) ||
                (c.phone || '').toLowerCase().includes(query)
            );
            if (filtered.length === 0) {
                dropdown.innerHTML = '<div style="padding:12px 16px; font-size:0.85rem; color:var(--text-muted,#999);">No se encontraron clientes. <button type="button" id="autocomplete-new-client-link" style="color:var(--accent-emerald); background:none; border:none; cursor:pointer; font-weight:600; padding:0;">Crear nuevo cliente</button></div>';
                const newClientLink = dropdown.querySelector('#autocomplete-new-client-link');
                if (newClientLink) {
                    newClientLink.addEventListener('click', () => {
                        dropdown.style.display = 'none';
                        if (typeof openCreateClientModal === 'function') openCreateClientModal();
                    });
                }
                positionClientDropdown();
                dropdown.style.display = 'block';
                return;
            }
            dropdown.innerHTML = filtered.map(c => `
                <div class="autocomplete-item" data-id="${c.id}" data-name="${c.razonSocial}" data-rnc="${c.rnc || ''}" style="padding:10px 16px; cursor:pointer; border-bottom:1px solid var(--border-color,#f0f0f0); display:flex; align-items:center; gap:10px; font-size:0.9rem;">
                    <div style="flex:1; min-width:0;">
                        <div style="font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${c.razonSocial}</div>
                        <div style="font-size:0.78rem; color:var(--text-muted,#888);">RNC: ${c.rnc || 'Consumidor Final'}</div>
                    </div>
                    <div style="font-size:0.78rem; color:var(--text-muted,#888); white-space:nowrap;">${c.email || ''}</div>
                </div>
            `).join('');
            dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
                item.addEventListener('click', (ev) => {
                    ev.preventDefault();
                    ev.stopPropagation();
                    const id = item.getAttribute('data-id');
                    const name = item.getAttribute('data-name');
                    const rnc = item.getAttribute('data-rnc');
                    const client = crmClients.find(c => c.id === id);
                    selectClient(id, name, rnc, client);
                });
            });
            positionClientDropdown();
            dropdown.style.display = 'block';
        });

        clientSearchInput.addEventListener('blur', () => {
            setTimeout(() => {
                const dropdown = getOrCreateClientDropdown();
                dropdown.style.display = 'none';
            }, 200);
        });

        clientSearchInput.addEventListener('focus', () => {
            if (clientSearchInput.value.trim().length >= 1) {
                clientSearchInput.dispatchEvent(new Event('keyup'));
            }
        });
    }

    // =========================================================================
    // AUTOCOMPLETADO INLINE PARA PRODUCTOS (sin necesidad de abrir modal)
    // =========================================================================
    function selectProductForRow(row, productId, displayName, price, itbis, product) {
        const searchInput = row.querySelector('.item-catalog-search-input');
        const catalogIdHidden = row.querySelector('.item-catalog-id-hidden');
        const nameInput = row.querySelector('.item-name-input');
        const priceInput = row.querySelector('.item-price-input');
        const itbisSelect = row.querySelector('.item-itbis-select');
        if (catalogIdHidden) catalogIdHidden.value = productId;
        if (searchInput) searchInput.value = displayName;
        if (nameInput) nameInput.value = product.name || displayName;
        if (priceInput) priceInput.value = parseFloat(price).toFixed(2);
        if (itbisSelect) itbisSelect.value = itbis;
        if (product) {
            row.dataset.codigoImpuesto = product.codigoImpuesto || '';
            row.dataset.tasaImpuestoAdicional = product.tasaImpuestoAdicional || 0.0;
            row.dataset.gradosAlcohol = product.gradosAlcohol || 0.0;
            row.dataset.cantidadReferencia = product.cantidadReferencia || 0.0;
            row.dataset.subcantidad = product.subcantidad || 0.0;
            row.dataset.precioReferencia = product.precioReferencia || 0.0;
        }
        const dropdown = row._autocompleteDropdown;
        if (dropdown) dropdown.style.display = 'none';
        recalculateTotals();
    }

    function createProductAutocomplete(row, searchInput) {
        if (row._autocompleteDropdown) return;
        const dropdown = document.createElement('div');
        dropdown.className = 'autocomplete-dropdown';
        dropdown.style.cssText = 'display:none; position:fixed; z-index:1050; max-height:260px; overflow-y:auto; width:380px; background:var(--bg-card,#ffffff); backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px); border:1px solid var(--border-color); border-radius:var(--radius-sm,8px); box-shadow:0 12px 40px rgba(0,0,0,0.18); font-size:0.85rem;';
        document.body.appendChild(dropdown);
        row._autocompleteDropdown = dropdown;

        const positionDropdown = () => {
            const rect = searchInput.getBoundingClientRect();
            dropdown.style.left = `${rect.left}px`;
            if (rect.bottom + 260 > window.innerHeight && rect.top > 260) {
                dropdown.style.top = `${rect.top - 264}px`;
            } else {
                dropdown.style.top = `${rect.bottom + 4}px`;
            }
        };
        row._positionDropdown = positionDropdown;

        searchInput.removeAttribute('readonly');
        searchInput.style.cursor = 'text';
        searchInput.setAttribute('placeholder', 'Escriba nombre o código...');
        searchInput.setAttribute('autocomplete', 'off');

        // Evitar que el blur cierre el dropdown cuando se hace clic en él
        dropdown.addEventListener('mousedown', (ev) => {
            ev.preventDefault();
        });

        searchInput.addEventListener('keyup', () => {
            const query = searchInput.value.toLowerCase().trim();
            if (query.length < 1) {
                dropdown.style.display = 'none';
                return;
            }
            const filtered = catalogItems.filter(p =>
                (p.name || '').toLowerCase().includes(query) ||
                (p.code || '').toLowerCase().includes(query)
            ).slice(0, 15);
            if (filtered.length === 0) {
                dropdown.innerHTML = '<div style="padding:12px 16px; color:var(--text-muted,#999);">No se encontraron productos. <button type="button" id="autocomplete-new-product-link" style="color:var(--accent-emerald); background:none; border:none; cursor:pointer; font-weight:600; padding:0; margin-left:4px;">Crear nuevo producto</button></div>';
                const newProductLink = dropdown.querySelector('#autocomplete-new-product-link');
                if (newProductLink) {
                    newProductLink.addEventListener('click', (ev) => {
                        ev.stopPropagation();
                        dropdown.style.display = 'none';
                        openProductCreateModal(row);
                    });
                }
                positionDropdown();
                dropdown.style.display = 'block';
                return;
            }
            dropdown.innerHTML = filtered.map(p => {
                const listPrice = getPriceListPrice(p.id);
                const displayPrice = listPrice !== null ? listPrice : p.price;
                const stock = parseFloat(p.totalStock || 0);
                const minStock = parseFloat(p.minStock || 0);
                const isService = p.type === 'Servicio';
                const stockLow = !isService && stock <= minStock && stock > 0;
                const stockOut = !isService && stock <= 0;
                const stockLabel = isService ? 'N/A (Servicio)' :
                    stockOut ? 'Sin existencias' :
                    stockLow ? `${stock} und (bajo mín.)` :
                    stock > 0 ? `${stock} und disponible` : 'Stock no definido';
                const stockColor = stockOut ? 'var(--accent-red,#ef4444)' :
                    stockLow ? '#f59e0b' :
                    isService ? 'var(--text-muted,#888)' : 'var(--accent-emerald,#10b981)';
                return `
                <div class="autocomplete-item" data-product-id="${p.id}" data-product-name="${p.name}" data-product-code="${p.code || ''}" data-product-price="${displayPrice}" data-product-itbis="${p.itbisRate}" style="padding:10px 14px; cursor:pointer; border-bottom:1px solid var(--border-color,#f0f0f0); display:flex; align-items:center; gap:10px; ${stockOut ? 'opacity:0.6;' : ''}">
                    <div style="flex:1; min-width:0;">
                        <div style="font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${p.name}</div>
                        <div style="font-size:0.75rem; color:var(--text-muted,#888); display:flex; align-items:center; gap:8px; margin-top:2px;">
                            <span>${p.code || 'S/C'}</span>
                            <span style="color:${stockColor}; font-weight:600;">${stockLabel}</span>
                        </div>
                    </div>
                    <div style="font-weight:600; white-space:nowrap;">${formatCurrencyDOP(displayPrice)}</div>
                    <button type="button" class="autocomplete-product-pick" style="background:var(--accent-emerald); color:white; border:none; border-radius:4px; padding:4px 10px; cursor:pointer; font-size:0.8rem; white-space:nowrap;">+ Agregar</button>
                </div>
            `}).join('');
            dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
                item.addEventListener('click', (ev) => {
                    ev.preventDefault();
                    ev.stopPropagation();
                    const productId = item.getAttribute('data-product-id');
                    const productName = item.getAttribute('data-product-name');
                    const productCode = item.getAttribute('data-product-code');
                    const displayPrice = parseFloat(item.getAttribute('data-product-price'));
                    const itbis = parseFloat(item.getAttribute('data-product-itbis'));
                    const product = catalogItems.find(p => p.id === productId);
                    if (productId && productName) {
                        selectProductForRow(row, productId, `${productName} (${productCode || 'N/A'})`, displayPrice, itbis, product);
                    }
                });
            });
            positionDropdown();
            dropdown.style.display = 'block';
        });

        searchInput.addEventListener('blur', () => {
            setTimeout(() => { dropdown.style.display = 'none'; }, 200);
        });

        searchInput.addEventListener('focus', () => {
            if (searchInput.value.trim().length >= 1) {
                searchInput.dispatchEvent(new Event('keyup'));
            }
        });
    }

    // Apply inline autocomplete to existing rows on page load
    document.querySelectorAll('#invoice-items-body .item-row').forEach(row => {
        const searchInput = row.querySelector('.item-catalog-search-input');
        if (searchInput) createProductAutocomplete(row, searchInput);
    });

    // Ocultar todos los dropdowns al hacer scroll (position:fixed necesita reposicionarse)
    window.addEventListener('scroll', () => {
        const cd = getOrCreateClientDropdown();
        if (cd) cd.style.display = 'none';
        document.querySelectorAll('#invoice-items-body .item-row').forEach(row => {
            if (row._autocompleteDropdown) row._autocompleteDropdown.style.display = 'none';
        });
    }, { passive: true });

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
                  <div style="position:relative;">
                    <input type="text" class="form-input item-catalog-search-input" placeholder="Escriba nombre o código…" autocomplete="off" style="padding-right:30px;">
                    <input type="hidden" class="item-catalog-id-hidden" name="items[${rowIndex}][catalog_id]">
                    <input type="hidden" class="item-name-input" name="items[${rowIndex}][name]">
                    <button type="button" class="btn-search-product" style="position:absolute;right:4px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--text-muted);cursor:pointer;padding:4px;"><i class="fa-solid fa-magnifying-glass" style="font-size:0.65rem;"></i></button>
                  </div>
                </td>
                <td style="text-align:center;"><input type="number" class="form-input item-qty-input" name="items[${rowIndex}][quantity]" min="1" value="1" style="width:60px;text-align:center;" required></td>
                <td style="text-align:right;"><input type="number" class="form-input item-price-input" name="items[${rowIndex}][price]" step="0.01" value="0.00" style="width:110px;" required></td>
                <td style="text-align:right;"><input type="number" class="form-input item-discount-input" name="items[${rowIndex}][discountRate]" step="0.01" min="0" max="1" value="0.00" style="width:75px;"></td>
                <td style="text-align:center;"><select class="form-select item-itbis-select" name="items[${rowIndex}][itbisRate]" style="width:75px;"><option value="0.18" selected>18%</option><option value="0.16">16%</option><option value="0.0">0%</option></select></td>
                <td style="text-align:right;font-weight:600;"><span class="item-total-label">RD$ 0.00</span></td>
                <td>
                  <div style="position:relative;">
                    <button type="button" class="row-menu-btn" onclick="toggleRowMenu(this)"><i class="fa-solid fa-ellipsis" style="font-size:0.9rem;"></i></button>
                    <div class="row-menu-dropdown">
                      <button type="button" class="row-menu-item danger" onclick="removeRowFromMenu(this)"><i class="fa-solid fa-trash-can" style="font-size:0.7rem;"></i> Eliminar de la lista</button>
                    </div>
                  </div>
                </td>
            `;

            itemsTableBody.appendChild(newRow);
            bindRowEvents(newRow);
            const searchInput = newRow.querySelector('.item-catalog-search-input');
            if (searchInput) createProductAutocomplete(newRow, searchInput);
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

        // El botón de lupa aún puede abrir el modal como fallback
        const openProductModalForRow = () => {
            activeProductRow = row;
            openProductModal();
        };

        if (searchBtn) searchBtn.addEventListener('click', openProductModalForRow);

        // Inputs cambiantes
        [priceInput, qtyInput, itbisSelect, discountInput].forEach(input => {
            if (input) {
                input.addEventListener('input', recalculateTotals);
                input.addEventListener('change', recalculateTotals);
            }
        });
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
        let totalIsc = 0.0;
        let totalPropina = 0.0;
        let totalCdt = 0.0;
        let totalIscEspecifico = 0.0;
        let totalIscAdvalorem = 0.0;
        let totalItemsQty = 0;

        const rows = itemsTableBody.querySelectorAll('.item-row');

        rows.forEach(row => {
            const price = parseFloat(row.querySelector('.item-price-input').value) || 0.0;
            const qty = parseInt(row.querySelector('.item-qty-input').value) || 1;
            const itbisRate = parseFloat(row.querySelector('.item-itbis-select').value) || 0.0;
            const itemDiscRate = parseFloat(row.querySelector('.item-discount-input').value) || 0.0;

            const rowSubtotalRaw = price * qty;
            const rowDiscount = rowSubtotalRaw * itemDiscRate;
            const rowSubtotal = rowSubtotalRaw - rowDiscount;

            // Cálculos dinámicos de Impuesto Selectivo al Consumo (ISC) en el frontend
            let iscEspecifico = 0.0;
            let iscAdvalorem = 0.0;
            const codImp = (row.dataset.codigoImpuesto || "").trim().padStart(3, '0');
            const tasaImp = parseFloat(row.dataset.tasaImpuestoAdicional) || 0.0;
            const gradosAlc = parseFloat(row.dataset.gradosAlcohol) || 0.0;
            const cantRef = parseFloat(row.dataset.cantidadReferencia) || 0.0;
            const subcant = parseFloat(row.dataset.subcantidad) || 0.0;
            const precioRef = parseFloat(row.dataset.precioReferencia) || 0.0;

            // Calcular ISC Específico e ISC AdValorem simultáneamente para Alcoholes y Tabacos
            const isAlcohol = (codImp >= '006' && codImp <= '018') || (codImp >= '023' && codImp <= '035');
            const isTabaco = (codImp >= '019' && codImp <= '022') || (codImp >= '036' && codImp <= '039');

            if (isAlcohol) {
                const tasaEsp = (codImp >= '006' && codImp <= '018') ? tasaImp : 632.58;
                iscEspecifico = tasaEsp * (gradosAlc / 100.0) * cantRef * subcant * qty;

                if (precioRef > 0.0) {
                    const tasaAdv = (codImp >= '023' && codImp <= '035') ? tasaImp : 0.10;
                    if (row.querySelector('.item-unit-select')?.value === 'Granel') {
                        iscAdvalorem = price * 1.30 * tasaAdv * qty;
                    } else {
                        if (qty > 0 && cantRef > 0) {
                            const precioSinItbis = precioRef / (1.0 + itbisRate);
                            const iscEspUnitario = iscEspecifico / (qty * cantRef);
                            const precioSinIscEsp = precioSinItbis - iscEspUnitario;
                            const precioSinIscAd = precioSinIscEsp / (1.0 + tasaAdv);
                            iscAdvalorem = precioSinIscAd * tasaAdv * cantRef * qty;
                        }
                    }
                }
            } else if (isTabaco) {
                const tasaEsp = (codImp >= '019' && codImp <= '022') ? tasaImp : 2.50;
                iscEspecifico = qty * cantRef * tasaEsp;

                if (precioRef > 0.0) {
                    const tasaAdv = (codImp >= '036' && codImp <= '039') ? tasaImp : 0.20;
                    const precioSinItbis = precioRef / (1.0 + itbisRate);
                    const precioSinIscEsp = precioSinItbis - tasaEsp;
                    const precioSinIscAd = precioSinIscEsp / (1.0 + tasaAdv);
                    iscAdvalorem = precioSinIscAd * tasaAdv * cantRef * qty;
                }
            } else if (codImp === '001') { // Propina Legal
                iscAdvalorem = rowSubtotal * 0.10;
                totalPropina += iscAdvalorem;
            } else if (codImp === '002') { // CDT
                iscAdvalorem = rowSubtotal * 0.02;
                totalCdt += iscAdvalorem;
            } else if (codImp === '003' || codImp === '004') { // Seguros / Telecomunicaciones
                iscAdvalorem = rowSubtotal * tasaImp;
            }

            const rowIsc = iscEspecifico + iscAdvalorem;
            const rowITBIS = (rowSubtotal + rowIsc) * itbisRate; // El ISC forma parte de la base imponible del ITBIS
            const rowTotal = rowSubtotal + rowIsc + rowITBIS;

            subtotalRaw += rowSubtotalRaw;
            totalDiscount += rowDiscount;
            totalITBIS += rowITBIS;
            totalIsc += rowIsc;
            totalIscEspecifico += iscEspecifico;
            totalIscAdvalorem += iscAdvalorem;
            totalItemsQty += qty;

            row.querySelector('.item-total-label').textContent = formatCurrencyDOP(rowTotal);
        });

        const globalDiscRate = parseFloat(discountGlobalInput.value) || 0.0;
        const globalDiscount = (subtotalRaw - totalDiscount) * globalDiscRate;
        totalDiscount += globalDiscount;

        const subtotal = subtotalRaw - totalDiscount;

        if (globalDiscRate > 0.0) {
            totalITBIS = totalITBIS * (1.0 - globalDiscRate);
            totalIsc = totalIsc * (1.0 - globalDiscRate);
            totalPropina = totalPropina * (1.0 - globalDiscRate);
            totalCdt = totalCdt * (1.0 - globalDiscRate);
            totalIscEspecifico = totalIscEspecifico * (1.0 - globalDiscRate);
            totalIscAdvalorem = totalIscAdvalorem * (1.0 - globalDiscRate);
        }

        const total = subtotal + totalIsc + totalITBIS;

        const isrRate = parseFloat(isrRateSelect.value) || 0.0;
        const itbisRetRate = parseFloat(itbisRateSelect.value) || 0.0;

        const retainedISR = subtotal * isrRate;
        const retainedITBIS = totalITBIS * itbisRetRate;
        const netPayable = Math.max(0.0, total - retainedISR - retainedITBIS);

        if (lblSubtotalRaw) lblSubtotalRaw.textContent = formatCurrencyDOP(subtotalRaw);
        if (lblDiscount) lblDiscount.textContent = formatCurrencyDOP(totalDiscount);
        if (lblSubtotal) lblSubtotal.textContent = formatCurrencyDOP(subtotal);
        if (lblITBIS) lblITBIS.textContent = formatCurrencyDOP(totalITBIS);

        // Elementos dinámicos desagregados (desglosados)
        const lblTotalPropina = document.getElementById('lbl-total-propina');
        const lblTotalCdt = document.getElementById('lbl-total-cdt');
        const lblTotalIsc = document.getElementById('lbl-total-isc');
        const lblTotalIscEspecifico = document.getElementById('lbl-total-isc-especifico');
        const lblTotalIscAdvalorem = document.getElementById('lbl-total-isc-advalorem');
        const lblTotalImpuestos = document.getElementById('lbl-total-impuestos');
        const lblTotalItemsQty = document.getElementById('lbl-total-items-qty');

        if (lblTotalPropina) lblTotalPropina.textContent = formatCurrencyDOP(totalPropina);
        if (lblTotalCdt) lblTotalCdt.textContent = formatCurrencyDOP(totalCdt);
        if (lblTotalIsc) lblTotalIsc.textContent = formatCurrencyDOP(totalIsc);
        if (lblTotalIscEspecifico) lblTotalIscEspecifico.textContent = formatCurrencyDOP(totalIscEspecifico);
        if (lblTotalIscAdvalorem) lblTotalIscAdvalorem.textContent = formatCurrencyDOP(totalIscAdvalorem);

        const totalImpuestosSum = totalITBIS + totalIsc + totalPropina + totalCdt;
        if (lblTotalImpuestos) lblTotalImpuestos.textContent = formatCurrencyDOP(totalImpuestosSum);
        if (lblTotalItemsQty) lblTotalItemsQty.textContent = formatCurrencyDOP(subtotalRaw);

        // Mostrar / Ocultar la sección de Impuestos Adicionales (ISC) en los totales (mantenido por compatibilidad)
        const lblIsc = document.getElementById('lbl-isc');
        const lblIscContainer = document.getElementById('lbl-isc-container');
        if (lblIsc && lblIscContainer) {
            lblIsc.textContent = formatCurrencyDOP(totalIsc);
            if (totalIsc > 0.01) {
                lblIscContainer.style.display = 'flex';
            } else {
                lblIscContainer.style.display = 'none';
            }
        }

        if (lblTotal) lblTotal.textContent = formatCurrencyDOP(total);
        if (lblRetainedISR) lblRetainedISR.textContent = formatCurrencyDOP(retainedISR);
        if (lblRetainedITBIS) lblRetainedITBIS.textContent = formatCurrencyDOP(retainedITBIS);
        if (lblNetPayable) lblNetPayable.textContent = formatCurrencyDOP(netPayable);
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

        const disableSubmitButtons = (disabled) => {
            submitBtn.disabled = disabled;
            submitBtn.style.opacity = disabled ? '0.5' : '1';
            if (submitBtnCobrar) {
                submitBtnCobrar.disabled = disabled;
                submitBtnCobrar.style.opacity = disabled ? '0.5' : '1';
            }
        };

        if (type.includes('E31')) {
            if (cleanRnc.length !== 9 && cleanRnc.length !== 11) {
                clientWarning.textContent = '⚠️ Para Crédito Fiscal (E31) se requiere un RNC de 9 dígitos o Cédula de 11 dígitos.';
                clientWarning.style.display = 'block';
                clientWarning.style.color = '#ef4444'; // Red alert
                disableSubmitButtons(true);
            } else {
                // RNC de formato correcto -> Validar contra el padrón RNC de la DGII en tiempo real
                clientWarning.textContent = '🔍 Validando RNC/Cédula con el padrón oficial de la DGII...';
                clientWarning.style.display = 'block';
                clientWarning.style.color = '#94a3b8'; // Neutral text
                disableSubmitButtons(true);

                fetch(`/api/rnc-lookup?rnc=${cleanRnc}`)
                    .then(response => response.json())
                    .then(data => {
                        if (data.error) {
                            clientWarning.textContent = `❌ RNC/Cédula no válido: El contribuyente no está registrado en la DGII. No se puede emitir Crédito Fiscal (E31).`;
                            clientWarning.style.display = 'block';
                            clientWarning.style.color = '#ef4444'; // Red error alert
                            disableSubmitButtons(true);
                        } else {
                            clientWarning.textContent = `✅ RNC Registrado: ${data.razon_social} (${data.regimen || 'Régimen Normal'})`;
                            clientWarning.style.display = 'block';
                            clientWarning.style.color = '#10b981'; // Success emerald
                            disableSubmitButtons(false);

                            // Autocompletar la razón social en el input de búsqueda del cliente si está vacío o es por defecto
                            const clientSearchInput = document.getElementById('client-search-input');
                            if (clientSearchInput && (!clientSearchInput.value || clientSearchInput.value.includes('Consumidor Final'))) {
                                clientSearchInput.value = `${data.razon_social} (${cleanRnc})`;
                            }
                        }
                    })
                    .catch(err => {
                        // Fallback ante caídas de conexión externa
                        clientWarning.textContent = '⚠️ No se pudo verificar el RNC con la DGII (Fallo de red). Procediendo con precaución.';
                        clientWarning.style.display = 'block';
                        clientWarning.style.color = '#f59e0b'; // Amber yellow
                        disableSubmitButtons(false);
                    });
            }
        } else {
            clientWarning.style.display = 'none';
            disableSubmitButtons(false);
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

    // =========================================================================
    // MODAL DE CREACIÓN RÁPIDA DE PRODUCTO (AJAX)
    // =========================================================================
    const productCreateModal = document.getElementById('product-create-modal');
    const btnCloseProductCreateModal = document.getElementById('btn-close-product-create-modal');
    const btnCancelProductCreate = document.getElementById('btn-cancel-product-create');
    const btnSaveNewProduct = document.getElementById('btn-save-new-product');
    const productCreateAlertEl = document.getElementById('product-create-alert');
    let targetProductRow = null;

    const openProductCreateModal = (row) => {
        if (!productCreateModal) return;
        targetProductRow = row || null;
        const n = document.getElementById('new-product-name'); if (n) n.value = '';
        const p = document.getElementById('new-product-price'); if (p) p.value = '0.00';
        const t = document.getElementById('new-product-type'); if (t) t.value = 'Bien';
        const i = document.getElementById('new-product-itbis'); if (i) i.value = '0.18';
        const c = document.getElementById('new-product-cost'); if (c) c.value = '0.00';
        if (productCreateAlertEl) { productCreateAlertEl.style.display = 'none'; }
        if (btnSaveNewProduct) btnSaveNewProduct.disabled = false;
        const lbl = document.getElementById('btn-save-new-product-label');
        if (lbl) lbl.textContent = 'Guardar y Seleccionar';
        productCreateModal.style.display = 'flex';
        setTimeout(() => document.getElementById('new-product-name')?.focus(), 100);
    };

    const closeProductCreateModal = () => {
        if (productCreateModal) productCreateModal.style.display = 'none';
        targetProductRow = null;
    };

    if (btnCloseProductCreateModal) btnCloseProductCreateModal.addEventListener('click', closeProductCreateModal);
    if (btnCancelProductCreate) btnCancelProductCreate.addEventListener('click', closeProductCreateModal);
    if (productCreateModal) {
        productCreateModal.addEventListener('click', (e) => {
            if (e.target === productCreateModal) closeProductCreateModal();
        });
    }

    if (btnSaveNewProduct) {
        btnSaveNewProduct.addEventListener('click', async () => {
            const name = (document.getElementById('new-product-name')?.value || '').trim();
            const price = parseFloat(document.getElementById('new-product-price')?.value || '0');
            const type = document.getElementById('new-product-type')?.value || 'Bien';
            const itbisRate = parseFloat(document.getElementById('new-product-itbis')?.value || '0.18');
            const costPrice = parseFloat(document.getElementById('new-product-cost')?.value || '0');

            if (!name) {
                if (productCreateAlertEl) { productCreateAlertEl.textContent = 'El nombre del producto es obligatorio.'; productCreateAlertEl.style.display = 'block'; productCreateAlertEl.style.background = 'rgba(239,68,68,0.12)'; productCreateAlertEl.style.color = '#dc2626'; }
                document.getElementById('new-product-name')?.focus();
                return;
            }
            if (isNaN(price) || price < 0) {
                if (productCreateAlertEl) { productCreateAlertEl.textContent = 'El precio debe ser un valor válido.'; productCreateAlertEl.style.display = 'block'; productCreateAlertEl.style.background = 'rgba(239,68,68,0.12)'; productCreateAlertEl.style.color = '#dc2626'; }
                return;
            }

            btnSaveNewProduct.disabled = true;
            const lbl = document.getElementById('btn-save-new-product-label');
            if (lbl) lbl.textContent = 'Guardando...';

            try {
                const csrfMeta = document.querySelector('meta[name="csrf-token"]');
                const resp = await fetch('/api/quick-create-product', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfMeta ? csrfMeta.getAttribute('content') : '' },
                    body: JSON.stringify({ name, price, type, itbisRate: itbisRate, costPrice })
                });
                const result = await resp.json();
                if (result.success) {
                    const np = result.item;
                    catalogItems.push({
                        id: np.id, code: np.code || '', name: np.name, price: np.price,
                        type: np.type, itbisRate: np.itbisRate, costPrice: np.costPrice || 0,
                        totalStock: 0, codigoImpuesto: '', tasaImpuestoAdicional: 0,
                        gradosAlcohol: 0, cantidadReferencia: 0, subcantidad: 0, precioReferencia: 0
                    });
                    if (productCreateAlertEl) { productCreateAlertEl.textContent = '✓ "' + np.name + '" creado.'; productCreateAlertEl.style.display = 'block'; productCreateAlertEl.style.background = 'rgba(16,185,129,0.12)'; productCreateAlertEl.style.color = '#059669'; }
                    setTimeout(() => {
                        if (targetProductRow) {
                            const si = targetProductRow.querySelector('.item-catalog-search-input');
                            const ch = targetProductRow.querySelector('.item-catalog-id-hidden');
                            const ni = targetProductRow.querySelector('.item-name-input');
                            const pi = targetProductRow.querySelector('.item-price-input');
                            const is = targetProductRow.querySelector('.item-itbis-select');
                            if (ch) ch.value = np.id;
                            if (si) si.value = np.name + ' (' + (np.code || 'Nuevo') + ')';
                            if (ni) ni.value = np.name;
                            if (pi) pi.value = parseFloat(np.price).toFixed(2);
                            if (is) is.value = np.itbisRate;
                            targetProductRow.dataset.codigoImpuesto = '';
                            targetProductRow.dataset.tasaImpuestoAdicional = 0;
                            targetProductRow.dataset.gradosAlcohol = 0;
                            targetProductRow.dataset.cantidadReferencia = 0;
                            targetProductRow.dataset.subcantidad = 1;
                            targetProductRow.dataset.precioReferencia = 0;
                            recalculateTotals();
                        }
                        closeProductCreateModal();
                        btnSaveNewProduct.disabled = false;
                        if (lbl) lbl.textContent = 'Guardar y Seleccionar';
                    }, 600);
                } else {
                    if (productCreateAlertEl) { productCreateAlertEl.textContent = result.error || 'Error al crear el producto.'; productCreateAlertEl.style.display = 'block'; productCreateAlertEl.style.background = 'rgba(239,68,68,0.12)'; productCreateAlertEl.style.color = '#dc2626'; }
                    btnSaveNewProduct.disabled = false;
                    if (lbl) lbl.textContent = 'Guardar y Seleccionar';
                }
            } catch (err) {
                if (productCreateAlertEl) { productCreateAlertEl.textContent = 'Error de conexión.'; productCreateAlertEl.style.display = 'block'; productCreateAlertEl.style.background = 'rgba(239,68,68,0.12)'; productCreateAlertEl.style.color = '#dc2626'; }
                btnSaveNewProduct.disabled = false;
                if (lbl) lbl.textContent = 'Guardar y Seleccionar';
            }
        });
    }
    window.openProductCreateModal = openProductCreateModal;
});

// Helper para formatear valores monetarios de DOP en la UI
function formatCurrencyDOP(amount) {
    return new Intl.NumberFormat('es-DO', {
        style: 'currency',
        currency: 'DOP'
    }).format(amount);
}
