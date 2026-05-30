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

         modalProductListBody.querySelectorAll('.btn-select-product').forEach(btn => {
            btn.addEventListener('click', () => {
                if (activeProductRow) {
                     const id = btn.getAttribute('data-id');
                     const name = btn.getAttribute('data-name');
                     const price = btn.getAttribute('data-price');
                     const itbis = btn.getAttribute('data-itbis');
                     const code = btn.getAttribute('data-code');

                     // Check if product is already in another row
                     let duplicateRow = null;
                     const rows = itemsTableBody.querySelectorAll('.item-row');
                     rows.forEach(row => {
                         if (row !== activeProductRow) {
                             const existingIdInput = row.querySelector('.item-catalog-id-hidden');
                             if (existingIdInput && existingIdInput.value === id) {
                                 duplicateRow = row;
                             }
                         }
                     });

                     if (duplicateRow) {
                          // Increment quantity of existing row
                          const qtyInput = duplicateRow.querySelector('.item-qty-input');
                          if (qtyInput) {
                              qtyInput.value = parseInt(qtyInput.value || 0) + 1;
                          }
                          
                          // Remove the empty active row since the product was merged into an existing row
                          if (rows.length > 1) {
                              activeProductRow.remove();
                              realignRowIndexes();
                          } else {
                              // If it is the only row, just reset inputs so it is clean
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

                     // Buscar el producto en catalogItems para asociar campos del Impuesto Selectivo (ISC)
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
                    <input type="text" class="form-input item-name-input" name="items[${rowIndex}][name]" required readonly style="width: 100%; background-color: var(--bg-input-readonly, rgba(0,0,0,0.02));">
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
                input.addEventListener('change', recalculateTotals);
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
});

// Helper para formatear valores monetarios de DOP en la UI
function formatCurrencyDOP(amount) {
    return new Intl.NumberFormat('es-DO', {
        style: 'currency',
        currency: 'DOP'
    }).format(amount);
}
