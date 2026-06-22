class QuotationWizard {
    constructor() {
        this.currentStep = 1;
        this.totalSteps = 6;
        this.formData = this._initFormData();
        this._previewTimer = null;
        this._previewUpdating = false;
        this._clients = [];
        this._catalogItems = [];
        this._catalogTargetIdx = null;
        this._loadClients();
        this._loadCatalog();
        this._applyInitialData(this._loadInitialData());

        this._bindEvents();
        this._goToStep(1);
    }

    _initFormData() {
        return {
            clientId: '',
            clientName: '',
            clientRNC: '',
            clientContact: '',
            clientEmail: '',
            clientPhone: '',
            clientAddress: '',
            subject: '',
            items: [],
            scopeIncluded: [],
            scopeExcluded: [],
            deliverables: [],
            timeline: [],
            paymentSchedule: [],
            validityDays: 15,
            termsAndConditions: '',
            intellectualProperty: '',
            confidentiality: '',
            supportTerms: '',
            warrantyTerms: '',
            observations: '',
            currency: 'RD$',
            paymentType: 'Transferencia Bancaria',
            paymentMethod: 'Transferencia',
            discountRate: 0,
            notes: ''
        };
    }

    _getEmptyItem() {
        return { code: '', name: '', quantity: 1, price: 0, itbisRate: 0.18, discountRate: 0, catalogId: '' };
    }

    async _loadClients() {
        try {
            const resp = await fetch('/api/clients/list');
            const data = await resp.json();
            if (data.success) {
                this._clients = data.clients || [];
                this._renderClientOptions();
            }
        } catch (e) {
            console.error('Error loading clients:', e);
        }
    }

    _loadCatalog() {
        try {
            const el = document.getElementById('catalog-data-json');
            if (el) {
                this._catalogItems = JSON.parse(el.textContent || '[]');
            }
        } catch (e) {
            console.error('Error loading catalog:', e);
            this._catalogItems = [];
        }
    }

    _loadInitialData() {
        try {
            const el = document.getElementById('wz-initial-data-json');
            if (el) {
                const data = JSON.parse(el.textContent || 'null');
                return data && typeof data === 'object' ? data : null;
            }
        } catch (e) {
            console.error('Error loading initial data:', e);
        }
        return null;
    }

    _applyInitialData(data) {
        if (!data) return;

        this.formData.clientId = data.clientId || '';
        this.formData.clientName = data.clientName || '';
        this.formData.clientRNC = data.clientRNC || '';
        this.formData.clientContact = data.clientContact || '';
        this.formData.clientEmail = data.clientEmail || '';
        this.formData.clientPhone = this._formatPhone(data.clientPhone || '');
        this.formData.clientAddress = data.clientAddress || '';
        this.formData.subject = data.subject || '';
        this.formData.items = data.items || [];
        this.formData.scopeIncluded = data.scopeIncluded || [];
        this.formData.scopeExcluded = data.scopeExcluded || [];
        this.formData.deliverables = data.deliverables || [];
        this.formData.timeline = data.timeline || [];
        this.formData.paymentSchedule = data.paymentSchedule || [];
        this.formData.validityDays = data.validityDays || 15;
        this.formData.termsAndConditions = data.termsAndConditions || '';
        this.formData.intellectualProperty = data.intellectualProperty || '';
        this.formData.confidentiality = data.confidentiality || '';
        this.formData.supportTerms = data.supportTerms || '';
        this.formData.warrantyTerms = data.warrantyTerms || '';
        this.formData.observations = data.observations || '';
        this.formData.deliveryTimeTotal = data.deliveryTimeTotal || '';
        this.formData.currency = data.currency || 'RD$';
        this.formData.paymentType = data.paymentType || 'Transferencia Bancaria';
        this.formData.paymentMethod = data.paymentMethod || 'Transferencia';
        this.formData.notes = data.notes || '';
        this.formData.discountRate = data.discountRate || 0;

        this._syncFields();
        this._renderClientOptions();
        const sel = document.getElementById('wz-client');
        if (sel) sel.value = this.formData.clientId;
        this._renderItemsPreview();
        this._updatePreview();
        this._goToStep(1);
    }

    _renderClientOptions(filterText) {
        const sel = document.getElementById('wz-client');
        if (!sel) return;
        const query = (filterText || '').toLowerCase().trim();
        sel.innerHTML = '<option value="">-- Seleccionar Cliente Existente --</option>';
        this._clients.forEach(c => {
            const displayName = c.name || 'Sin nombre';
            const rnc = c.rnc || '';
            const match = !query ||
                displayName.toLowerCase().includes(query) ||
                rnc.includes(query) ||
                (c.email || '').toLowerCase().includes(query);
            if (!match) return;
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = `${displayName} (${rnc || 'S/RNC'})`;
            sel.appendChild(opt);
        });
    }

    _bindEvents() {
        document.addEventListener('click', (e) => {
            if (e.target.matches('#wz-catalog-modal-close') || e.target.closest('#wz-catalog-modal') === e.target) {
                this._closeCatalogModal();
                return;
            }
            if (e.target.matches('#wz-item-edit-close') || e.target.closest('#wz-item-edit-modal') === e.target) {
                this._closeEditModal();
                return;
            }
            const btn = e.target.closest('.wz-nav-next, .wz-nav-prev, .wz-btn-ai-full, .wz-btn-ai-section, .wz-add-item, .wz-remove-item, .wz-add-scope-include, .wz-add-scope-exclude, .wz-remove-scope, .wz-add-deliverable, .wz-remove-deliverable, .wz-add-timeline, .wz-remove-timeline, .wz-add-payment, .wz-remove-payment, #wz-catalog-open-btn, .wz-item-catalog-btn, .wz-catalog-item .btn-select-item');
            if (!btn) return;
            if (btn.matches('.wz-nav-next')) this._nextStep();
            else if (btn.matches('.wz-nav-prev')) this._prevStep();
            else if (btn.matches('.wz-btn-ai-full')) this._generateFullWithAI();
            else if (btn.matches('.wz-btn-ai-section')) this._suggestSection(btn.dataset.section);
            else if (btn.matches('.wz-add-item')) this._addItem();
            else if (btn.matches('.wz-remove-item')) this._removeItem(btn);
            else if (btn.matches('.wz-add-scope-include')) this._addScopeItem('scopeIncluded');
            else if (btn.matches('.wz-add-scope-exclude')) this._addScopeItem('scopeExcluded');
            else if (btn.matches('.wz-remove-scope')) this._removeScopeItem(btn);
            else if (btn.matches('.wz-add-deliverable')) this._addDeliverable();
            else if (btn.matches('.wz-remove-deliverable')) this._removeDeliverable(btn);
            else if (btn.matches('.wz-add-timeline')) this._addTimeline();
            else if (btn.matches('.wz-remove-timeline')) this._removeTimeline(btn);
            else if (btn.matches('.wz-add-payment')) this._addPayment();
            else if (btn.matches('.wz-remove-payment')) this._removePayment(btn);
            else if (btn.matches('#wz-catalog-open-btn')) this._openCatalogModal(null);
            else if (btn.matches('.wz-item-catalog-btn')) this._openCatalogModal(btn);
            else if (btn.matches('.wz-catalog-item .btn-select-item')) this._selectCatalogItem(btn);
        });

        document.getElementById('edit-save-btn')?.addEventListener('click', () => this._saveEditItem());
        document.getElementById('edit-cancel-btn')?.addEventListener('click', () => this._closeEditModal());
        document.getElementById('edit-add-catalog-btn')?.addEventListener('click', () => this._addItemToCatalog());

        document.addEventListener('change', (e) => {
            if (e.target.matches('#wz-client')) this._onClientChange(e.target);
            this._schedulePreview();
        });

        document.addEventListener('input', (e) => {
            if (e.target.matches('[data-wz-field]')) {
                this._onFieldChange(e.target);
                this._schedulePreview();
            }
            if (e.target.matches('.wz-item-field')) {
                this._schedulePreview();
            }
            if (e.target.matches('.wz-scope-input')) {
                this._schedulePreview();
            }
            if (e.target.matches('#wz-catalog-search-input')) {
                this._renderCatalogModal(e.target.value);
            }
            if (e.target.matches('#wz-client-search')) {
                this._renderClientOptions(e.target.value);
            }
        });

        document.getElementById('wz-save-btn')?.addEventListener('click', (e) => this._save(e));
    }

    _onClientChange(sel) {
        const client = this._clients.find(c => c.id === sel.value);
        if (client) {
            this.formData.clientId = client.id;
            this.formData.clientName = client.name || '';
            this.formData.clientRNC = client.rnc || '';
            this.formData.clientContact = client.contactPerson || '';
            this.formData.clientEmail = client.email || '';
            this.formData.clientPhone = this._formatPhone(client.phone || '');
            this.formData.clientAddress = client.address || '';
            this._syncFields();
            const searchInput = document.getElementById('wz-client-search');
            if (searchInput) searchInput.value = '';
        }
    }

    _formatPhone(phone) {
        const digits = phone.replace(/\D/g, '');
        if (digits.length === 10) {
            return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`;
        }
        if (digits.length === 11 && digits[0] === '1') {
            return `${digits.slice(1, 4)}-${digits.slice(4, 7)}-${digits.slice(7)}`;
        }
        if (digits.length >= 7) {
            return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6, 10)}`;
        }
        return phone;
    }

    _onFieldChange(el) {
        const field = el.dataset.wzField;
        if (field) {
            this.formData[field] = el.value;
        }
    }

    _syncFields() {
        document.querySelectorAll('[data-wz-field]').forEach(el => {
            const field = el.dataset.wzField;
            if (this.formData[field] !== undefined) {
                el.value = this.formData[field];
            }
        });
        this._renderItemsPreview();
        this._renderScopePreview();
        this._renderDeliverablesPreview();
        this._renderTimelinePreview();
        this._renderPaymentPreview();
    }

    _goToStep(step) {
        this.currentStep = Math.max(1, Math.min(step, this.totalSteps));
        document.querySelectorAll('.wz-step').forEach(el => el.classList.remove('active'));
        const stepEl = document.querySelector(`.wz-step[data-step="${this.currentStep}"]`);
        if (stepEl) stepEl.classList.add('active');
        document.querySelectorAll('.wz-step-indicator').forEach(el => {
            el.classList.toggle('active', parseInt(el.dataset.step) === this.currentStep);
            el.classList.toggle('completed', parseInt(el.dataset.step) < this.currentStep);
        });
        this._updateNavButtons();
        this._schedulePreview();
    }

    _nextStep() {
        if (this.currentStep < this.totalSteps) {
            this._goToStep(this.currentStep + 1);
        }
    }

    _prevStep() {
        if (this.currentStep > 1) {
            this._goToStep(this.currentStep - 1);
        }
    }

    _updateNavButtons() {
        const prevBtn = document.querySelector('.wz-nav-prev');
        const nextBtn = document.querySelector('.wz-nav-next');
        if (prevBtn) prevBtn.style.display = this.currentStep === 1 ? 'none' : '';
        if (nextBtn) {
            nextBtn.style.display = this.currentStep === this.totalSteps ? 'none' : '';
            nextBtn.textContent = this.currentStep === this.totalSteps - 1 ? 'Revisar y Guardar →' : 'Siguiente →';
        }
        const saveBtn = document.getElementById('wz-save-btn');
        if (saveBtn) saveBtn.style.display = this.currentStep === this.totalSteps ? '' : 'none';
    }

    _schedulePreview() {
        clearTimeout(this._previewTimer);
        this._previewTimer = setTimeout(() => this._updatePreview(), 600);
    }

    async _updatePreview() {
        if (this._previewUpdating) return;
        this._previewUpdating = true;

        const previewContainer = document.getElementById('wz-preview-container');
        if (!previewContainer) { this._previewUpdating = false; return; }

        previewContainer.classList.add('preview-loading');

        try {
            const data = this._collectFormData();
            const resp = await fetch('/api/quotations/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            if (!resp.ok) throw new Error('Error en preview');
            const html = await resp.text();
            previewContainer.innerHTML = html;
        } catch (e) {
            previewContainer.innerHTML = `<div style="padding:20px;text-align:center;color:#999;">
                <i class="fa-solid fa-file-pen" style="font-size:48px;display:block;margin-bottom:12px;"></i>
                Complete los datos para ver la vista previa</div>`;
        } finally {
            previewContainer.classList.remove('preview-loading');
            this._previewUpdating = false;
        }
    }

    _collectFormData() {
        const data = { ...this.formData };

        data.items = this._collectItems();
        data.scopeIncluded = this._collectList('scope-included');
        data.scopeExcluded = this._collectList('scope-excluded');
        data.deliverables = this._collectDeliverables();
        data.timeline = this._collectTimeline();
        data.paymentSchedule = this._collectPayments();

        return data;
    }

    _collectItems() {
        return this.formData.items.map(item => ({
            code: item.code || '',
            name: item.name || '',
            quantity: item.quantity || 1,
            price: item.price || 0,
            itbisRate: item.itbisRate || 0.18,
            discountRate: item.discountRate || 0,
            catalogId: item.catalogId || ''
        }));
    }

    _collectList(className) {
        return Array.from(document.querySelectorAll(`.wz-${className}-list .wz-scope-input`)).map(el => el.value).filter(v => v.trim());
    }

    _collectDeliverables() {
        const items = [];
        document.querySelectorAll('.wz-deliverable-row').forEach(row => {
            items.push({
                name: row.querySelector('.wz-del-name')?.value || '',
                description: row.querySelector('.wz-del-desc')?.value || '',
                estimatedDate: row.querySelector('.wz-del-date')?.value || ''
            });
        });
        return items;
    }

    _collectTimeline() {
        const items = [];
        document.querySelectorAll('.wz-timeline-row').forEach(row => {
            items.push({
                phase: row.querySelector('.wz-tl-phase')?.value || '',
                description: row.querySelector('.wz-tl-desc')?.value || '',
                duration: row.querySelector('.wz-tl-duration')?.value || ''
            });
        });
        return items;
    }

    _collectPayments() {
        const items = [];
        document.querySelectorAll('.wz-payment-row').forEach(row => {
            items.push({
                installment: parseInt(row.querySelector('.wz-pay-num')?.value) || items.length + 1,
                description: row.querySelector('.wz-pay-desc')?.value || '',
                percentage: parseFloat(row.querySelector('.wz-pay-pct')?.value) || 0,
                trigger: row.querySelector('.wz-pay-trigger')?.value || ''
            });
        });
        return items;
    }

    async _generateFullWithAI() {
        const contextEl = document.getElementById('wz-ai-context');
        const context = contextEl?.value?.trim();
        if (!context) {
            this._showToast('Escriba el contexto del proyecto primero', 'warning');
            return;
        }

        const btn = document.querySelector('.wz-btn-ai-full');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generando...'; }

        try {
            const resp = await fetch('/api/quotations/ai-generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ context })
            });
            const data = await resp.json();

            if (data.success && data.data) {
                this._applyAIData(data.data);
                this._showToast('Cotización generada con IA exitosamente', 'success');
            } else {
                this._showToast(data.message || 'Error al generar', 'error');
            }
        } catch (e) {
            this._showToast('Error de conexión', 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generar Cotización Completa con IA'; }
        }
    }

    _applyAIData(data) {
        Object.keys(data).forEach(key => {
            if (this.formData[key] !== undefined) {
                this.formData[key] = data[key];
            }
        });

        if (data.items) {
            this.formData.items = data.items;
        }

        this._syncFields();
        this._renderScopePreview();
        this._renderDeliverablesPreview();
        this._renderTimelinePreview();
        this._renderPaymentPreview();
        this._schedulePreview();

        if (data.subject) {
            document.querySelector('[data-wz-field="subject"]').value = data.subject;
        }
    }

    async _suggestSection(section) {
        const btn = document.querySelector(`.wz-btn-ai-section[data-section="${section}"]`);
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; }

        const contextData = this._collectFormData();
        delete contextData.items;

        try {
            const resp = await fetch('/api/quotations/ai-suggest-section', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ section, contextData })
            });
            const data = await resp.json();

            if (data.success && data.data) {
                if (section === 'items' && data.data.items) {
                    this.formData.items = data.data.items;
                    this._renderItemsPreview();
                }
                this._showToast('Sección generada con IA', 'success');
                this._schedulePreview();
            } else {
                this._showToast(data.message || 'Error al generar', 'error');
            }
        } catch (e) {
            this._showToast('Error de conexión', 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Ayuda con IA'; }
        }
    }

    _renderItemsPreview() {
        const container = document.getElementById('wz-items-container');
        if (!container) return;
        container.innerHTML = '';
        (this.formData.items || []).forEach((item, idx) => {
            const row = document.createElement('div');
            row.className = 'wz-item-row';
            row.dataset.catalogId = item.catalogId || '';
            const itbisLabel = (item.itbisRate || 0.18) === 0.18 ? '18%' : '0%';
            const discount = parseFloat(item.discountRate) || 0;
            row.innerHTML = `
                <span class="wz-item-name-display" title="${this._escapeAttr(item.code || '')}">${this._escapeHtml(item.name || '—')}</span>
                <span class="wz-item-qty-display">${item.quantity || 1}</span>
                <span class="wz-item-price-display">${this._formatCurrency(item.price || 0)}</span>
                <span class="wz-item-itbis-display">${itbisLabel}</span>
                <span class="wz-item-discount-display">${discount > 0 ? discount + '%' : '—'}</span>
                <button type="button" class="wz-edit-item btn btn-sm" title="Editar partida"><i class="fa-solid fa-pen"></i></button>
                <button type="button" class="wz-remove-item btn btn-sm btn-danger" title="Eliminar"><i class="fa-solid fa-trash-can"></i></button>
            `;
            row.querySelector('.wz-edit-item').addEventListener('click', () => this._openEditModal(idx));
            container.appendChild(row);
        });
    }

    _formatCurrency(val) {
        const num = parseFloat(val) || 0;
        return 'RD$ ' + num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }

    _addItem(data) {
        const item = data || this._getEmptyItem();
        this.formData.items.push(item);
        this._renderItemsPreview();
        this._schedulePreview();
        this._openEditModal(this.formData.items.length - 1);
    }

    _removeItem(btn) {
        const row = btn.closest('.wz-item-row');
        if (row) {
            const idx = Array.from(row.parentElement.children).indexOf(row);
            this.formData.items.splice(idx, 1);
            this._renderItemsPreview();
            this._schedulePreview();
        }
    }

    _openEditModal(idx) {
        const item = this.formData.items[idx];
        if (!item) return;
        this._editIdx = idx;

        document.getElementById('edit-item-code').value = item.code || '';
        document.getElementById('edit-item-name').value = item.name || '';
        document.getElementById('edit-item-qty').value = item.quantity || 1;
        document.getElementById('edit-item-price').value = item.price || 0;
        document.getElementById('edit-item-itbis').value = (item.itbisRate || 0.18).toString();
        document.getElementById('edit-item-discount').value = item.discountRate || 0;

        const addCatBtn = document.getElementById('edit-add-catalog-btn');
        if (item.catalogId) {
            addCatBtn.style.display = 'none';
        } else {
            addCatBtn.style.display = '';
            addCatBtn.dataset.idx = idx;
        }

        document.getElementById('wz-item-edit-modal').classList.add('active');
    }

    _saveEditItem() {
        const idx = this._editIdx;
        if (idx === null || idx === undefined || !this.formData.items[idx]) return;

        this.formData.items[idx].code = document.getElementById('edit-item-code').value.trim();
        this.formData.items[idx].name = document.getElementById('edit-item-name').value.trim();
        this.formData.items[idx].quantity = parseFloat(document.getElementById('edit-item-qty').value) || 1;
        this.formData.items[idx].price = parseFloat(document.getElementById('edit-item-price').value) || 0;
        this.formData.items[idx].itbisRate = parseFloat(document.getElementById('edit-item-itbis').value) || 0.18;
        this.formData.items[idx].discountRate = parseFloat(document.getElementById('edit-item-discount').value) || 0;

        this._closeEditModal();
        this._renderItemsPreview();
        this._schedulePreview();
    }

    _closeEditModal() {
        document.getElementById('wz-item-edit-modal').classList.remove('active');
        this._editIdx = null;
    }

    async _addItemToCatalog() {
        const name = document.getElementById('edit-item-name').value.trim();
        const price = parseFloat(document.getElementById('edit-item-price').value) || 0;
        const code = document.getElementById('edit-item-code').value.trim();
        const itbis = parseFloat(document.getElementById('edit-item-itbis').value) || 0.18;

        if (!name || price <= 0) {
            this._showToast('Complete nombre y precio antes de agregar al catálogo', 'warning');
            return;
        }

        const btn = document.getElementById('edit-add-catalog-btn');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; }

        try {
            const resp = await fetch('/api/items/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, price, code, itbisRate: itbis, type: 'Producto', isActive: true })
            });
            const data = await resp.json();
            if (data.success && data.item) {
                const newItem = data.item;
                const idx = this._editIdx;
                if (idx !== null && idx !== undefined && this.formData.items[idx]) {
                    this.formData.items[idx].catalogId = newItem.id || newItem._id || '';
                }
                this._catalogItems.push(newItem);
                document.getElementById('edit-add-catalog-btn').style.display = 'none';
                this._showToast('Agregado al catálogo exitosamente', 'success');
            } else {
                this._showToast(data.message || 'Error al agregar al catálogo', 'error');
            }
        } catch (e) {
            this._showToast('Error de conexión', 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-bookmark"></i> Agregar al Catálogo'; }
        }
    }

    _openCatalogModal(btn) {
        this._catalogTargetIdx = null;
        if (btn) {
            const row = btn.closest('.wz-item-row');
            if (row) {
                const idx = Array.from(row.parentElement.children).indexOf(row);
                this._catalogTargetIdx = idx;
            }
        }
        this._renderCatalogModal('');
        document.getElementById('wz-catalog-search-input').value = '';
        document.getElementById('wz-catalog-modal').classList.add('active');
        setTimeout(() => document.getElementById('wz-catalog-search-input')?.focus(), 100);
    }

    _closeCatalogModal() {
        document.getElementById('wz-catalog-modal').classList.remove('active');
        this._catalogTargetIdx = null;
    }

    _renderCatalogModal(filterText) {
        const body = document.getElementById('wz-catalog-modal-body');
        if (!body) return;
        const query = (filterText || '').toLowerCase().trim();
        let items = this._catalogItems;
        if (query) {
            items = items.filter(it =>
                (it.name || '').toLowerCase().includes(query) ||
                (it.code || '').toLowerCase().includes(query) ||
                (it.barcode || '').toLowerCase().includes(query)
            );
        }
        if (items.length === 0) {
            body.innerHTML = '<div class="wz-catalog-empty"><i class="fa-solid fa-box-open" style="font-size:32px;display:block;margin-bottom:8px;"></i>No se encontraron productos</div>';
            return;
        }
        body.innerHTML = items.map(it => `
            <div class="wz-catalog-item">
                <div class="wz-catalog-item-info">
                    <div class="wz-catalog-item-name">${this._escapeHtml(it.name || '')}</div>
                    <div class="wz-catalog-item-meta">
                        ${it.code ? '<strong>Código:</strong> ' + this._escapeHtml(it.code) : ''}
                        ${it.code && it.type ? ' &middot; ' : ''}
                        ${it.type ? '<strong>Tipo:</strong> ' + this._escapeHtml(it.type) : ''}
                        ${(it.code || it.type) && it.unit ? ' &middot; ' : ''}
                        ${it.unit ? '<strong>Unidad:</strong> ' + this._escapeHtml(it.unit) : ''}
                    </div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div class="wz-catalog-item-price">RD$ ${(it.price || 0).toFixed(2)}</div>
                    <button type="button" class="btn-select-item" data-catalog-id="${it.id || it._id || ''}"
                        data-name="${this._escapeAttr(it.name || '')}"
                        data-price="${it.price || 0}"
                        data-itbis="${it.itbisRate || 0.18}"
                        data-code="${this._escapeAttr(it.code || '')}"
                        data-unit="${this._escapeAttr(it.unit || 'Unidad')}">
                        <i class="fa-solid fa-plus"></i> Seleccionar
                    </button>
                </div>
            </div>
        `).join('');
    }

    _selectCatalogItem(btn) {
        const id = btn.dataset.catalogId;
        const name = btn.dataset.name;
        const price = parseFloat(btn.dataset.price) || 0;
        const itbis = parseFloat(btn.dataset.itbis) || 0.18;
        const code = btn.dataset.code || '';
        const item = { code, name, quantity: 1, price, itbisRate: itbis, discountRate: 0, catalogId: id };

        if (this._catalogTargetIdx !== null && this.formData.items[this._catalogTargetIdx]) {
            const existing = this.formData.items[this._catalogTargetIdx];
            existing.code = code;
            existing.name = name;
            existing.price = price;
            existing.itbisRate = itbis;
            existing.catalogId = id;
        } else {
            this.formData.items.push(item);
        }

        this._closeCatalogModal();
        this._renderItemsPreview();
        this._schedulePreview();
    }

    _escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    _escapeAttr(str) {
        return String(str).replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    _addScopeItem(type) {
        const list = document.querySelector(`.wz-${type === 'scopeIncluded' ? 'scope-included' : 'scope-excluded'}-list`);
        if (!list) return;
        const div = document.createElement('div');
        div.className = 'wz-scope-item';
        div.innerHTML = `<input type="text" class="wz-scope-input" placeholder="Agregar item..." value="">
            <button type="button" class="wz-remove-scope btn btn-sm btn-danger"><i class="fa-solid fa-xmark"></i></button>`;
        list.appendChild(div);
        this._schedulePreview();
    }

    _removeScopeItem(btn) {
        btn.closest('.wz-scope-item')?.remove();
        this._schedulePreview();
    }

    _renderScopePreview() {
        ['scopeIncluded', 'scopeExcluded'].forEach(type => {
            const list = document.querySelector(`.wz-${type === 'scopeIncluded' ? 'scope-included' : 'scope-excluded'}-list`);
            if (!list) return;
            list.innerHTML = '';
            (this.formData[type] || []).forEach(item => {
                const div = document.createElement('div');
                div.className = 'wz-scope-item';
                div.innerHTML = `<input type="text" class="wz-scope-input" value="${item}">
                    <button type="button" class="wz-remove-scope btn btn-sm btn-danger"><i class="fa-solid fa-xmark"></i></button>`;
                list.appendChild(div);
            });
        });
    }

    _addDeliverable() {
        this.formData.deliverables.push({ name: '', description: '', estimatedDate: '' });
        this._renderDeliverablesPreview();
        this._schedulePreview();
    }

    _removeDeliverable(btn) {
        const row = btn.closest('.wz-deliverable-row');
        if (row) {
            const idx = Array.from(row.parentElement.children).indexOf(row);
            this.formData.deliverables.splice(idx, 1);
            this._renderDeliverablesPreview();
            this._schedulePreview();
        }
    }

    _renderDeliverablesPreview() {
        const container = document.getElementById('wz-deliverables-container');
        if (!container) return;
        container.innerHTML = '';
        (this.formData.deliverables || []).forEach(d => {
            const row = document.createElement('div');
            row.className = 'wz-deliverable-row';
            row.innerHTML = `
                <input type="text" class="wz-del-name" value="${d.name || ''}" placeholder="Nombre del entregable">
                <input type="text" class="wz-del-desc" value="${d.description || ''}" placeholder="Descripción">
                <input type="text" class="wz-del-date" value="${d.estimatedDate || ''}" placeholder="Tiempo estimado">
                <button type="button" class="wz-remove-deliverable btn btn-sm btn-danger"><i class="fa-solid fa-xmark"></i></button>
            `;
            container.appendChild(row);
        });
    }

    _addTimeline() {
        this.formData.timeline.push({ phase: '', description: '', duration: '' });
        this._renderTimelinePreview();
        this._schedulePreview();
    }

    _removeTimeline(btn) {
        const row = btn.closest('.wz-timeline-row');
        if (row) {
            const idx = Array.from(row.parentElement.children).indexOf(row);
            this.formData.timeline.splice(idx, 1);
            this._renderTimelinePreview();
            this._schedulePreview();
        }
    }

    _renderTimelinePreview() {
        const container = document.getElementById('wz-timeline-container');
        if (!container) return;
        container.innerHTML = '';
        (this.formData.timeline || []).forEach(t => {
            const row = document.createElement('div');
            row.className = 'wz-timeline-row';
            row.innerHTML = `
                <input type="text" class="wz-tl-phase" value="${t.phase || ''}" placeholder="Nombre de la fase">
                <input type="text" class="wz-tl-desc" value="${t.description || ''}" placeholder="Descripción">
                <input type="text" class="wz-tl-duration" value="${t.duration || ''}" placeholder="Duración">
                <button type="button" class="wz-remove-timeline btn btn-sm btn-danger"><i class="fa-solid fa-xmark"></i></button>
            `;
            container.appendChild(row);
        });
    }

    _addPayment() {
        const pct = this.formData.paymentSchedule.reduce((s, p) => s + (p.percentage || 0), 0);
        const remaining = Math.max(0, 100 - pct);
        this.formData.paymentSchedule.push({
            installment: this.formData.paymentSchedule.length + 1,
            description: '',
            percentage: remaining > 0 ? remaining : 0,
            trigger: ''
        });
        this._renderPaymentPreview();
        this._schedulePreview();
    }

    _removePayment(btn) {
        const row = btn.closest('.wz-payment-row');
        if (row) {
            const idx = Array.from(row.parentElement.children).indexOf(row);
            this.formData.paymentSchedule.splice(idx, 1);
            this._renderPaymentPreview();
            this._schedulePreview();
        }
    }

    _renderPaymentPreview() {
        const container = document.getElementById('wz-payment-container');
        if (!container) return;
        container.innerHTML = '';
        (this.formData.paymentSchedule || []).forEach((p, idx) => {
            const row = document.createElement('div');
            row.className = 'wz-payment-row';
            row.innerHTML = `
                <span class="wz-pay-num-display">#${idx + 1}</span>
                <input type="hidden" class="wz-pay-num" value="${idx + 1}">
                <input type="text" class="wz-pay-desc" value="${p.description || ''}" placeholder="Descripción del hito">
                <input type="number" class="wz-pay-pct" value="${p.percentage || 0}" step="0.1" min="0" max="100" style="width:80px;" placeholder="%">
                <span style="font-size:12px;color:#64748b;">%</span>
                <input type="text" class="wz-pay-trigger" value="${p.trigger || ''}" placeholder="Evento que activa el pago" style="flex:1;">
                <button type="button" class="wz-remove-payment btn btn-sm btn-danger"><i class="fa-solid fa-xmark"></i></button>
            `;
            container.appendChild(row);
        });
    }

    async _save(e) {
        e.preventDefault();

        const formData = this._collectFormData();

        if (!formData.clientId && !formData.clientName) {
            this._showToast('Seleccione o ingrese un cliente', 'error');
            this._goToStep(2);
            return;
        }
        if (formData.items.length === 0) {
            this._showToast('Agregue al menos un item a la cotización', 'error');
            this._goToStep(3);
            return;
        }

        const btn = document.getElementById('wz-save-btn');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Guardando...'; }

        try {
            const resp = await fetch('/quotations/new/professional', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });
            const data = await resp.json();

            if (data.success) {
                this._showToast('Cotización guardada exitosamente', 'success');
                setTimeout(() => {
                    window.location.href = data.redirect || '/quotations';
                }, 800);
            } else {
                this._showToast(data.message || 'Error al guardar', 'error');
            }
        } catch (e) {
            this._showToast('Error de conexión al guardar', 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Guardar Cotización'; }
        }
    }

    _showToast(message, type = 'info') {
        const container = document.getElementById('wz-toast-container') || (() => {
            const c = document.createElement('div');
            c.id = 'wz-toast-container';
            c.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px;';
            document.body.appendChild(c);
            return c;
        })();

        const toast = document.createElement('div');
        const colors = { success: '#16A34A', error: '#DC2626', warning: '#F59E0B', info: '#1E3A8A' };
        toast.style.cssText = `padding:12px 20px;border-radius:8px;color:white;font-size:14px;font-weight:500;
            background:${colors[type] || colors.info};box-shadow:0 4px 12px rgba(0,0,0,0.15);
            animation:slideInUp 0.3s ease;display:flex;align-items:center;gap:8px;`;
        toast.innerHTML = message;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.quotation-wizard')) {
        window.wizard = new QuotationWizard();
    }
});
