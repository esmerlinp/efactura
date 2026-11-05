/* VykOne POS — lógica de terminal de venta */
(function () {
    "use strict";

    const bootstrapEl = document.getElementById("pos-bootstrap");
    const boot = bootstrapEl ? JSON.parse(bootstrapEl.textContent) : { items: [], categories: [], ecfTypes: [], config: {} };
    const cfg = boot.config || {};

    const PENDING_KEY = "vykone_pos_pending_v1";
    const DRAFT_KEY = "vykone_pos_draft_v1";
    const DEFAULT_CLIENT = { id: "default", name: "Consumidor final", rnc: "000000000", email: "" };

    const state = {
        items: (boot.items || []).map((item) => ({
            ...item,
            price: Number(item.price) || 0,
            itbisRate: item.itbisRate === null || item.itbisRate === undefined ? 0.18 : Number(item.itbisRate),
            totalStock: Number(item.totalStock) || 0,
            availableStock: item.availableStock === null || item.availableStock === undefined
                ? Number(item.totalStock) || 0
                : Number(item.availableStock) || 0,
            search: `${item.name || ""} ${item.code || ""} ${item.barcode || ""}`.toLowerCase(),
        })),
        categories: Array.isArray(boot.categories) ? boot.categories.slice() : [],
        ecfTypes: Array.isArray(boot.ecfTypes) ? boot.ecfTypes : [],
        cart: [],
        client: { ...DEFAULT_CLIENT },
        ecfCode: "E32",
        globalDiscount: 0,
        category: "all",
        search: "",
        quote: null,
        quoteSeq: 0,
        quoteErrorShown: false,
        quoteTimer: null,
        selectedLineId: null,
        payments: [],
        usdRate: 58.5,
        discountTarget: null,
        pending: [],
        lastInvoice: null,
        checkoutKey: null,
        checkoutKeyHash: null,
        mobileView: "catalog",
        draftTimer: null,
        clientCache: null,
        clientLookupTimer: null,
        lastDgiiLookupRnc: "",
        isSubmitting: false,
        modalReturnFocus: null,
    };

    const $ = (id) => document.getElementById(id);
    const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

    const numberFormat = new Intl.NumberFormat("es-DO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const money = (value) => `RD$ ${numberFormat.format(Number(value) || 0)}`;
    const moneyNeg = (value) => `− ${money(value)}`;
    const usd = (value) => `US$ ${numberFormat.format(Number(value) || 0)}`;
    const qtyLabel = (value) => new Intl.NumberFormat("es-DO", { maximumFractionDigits: 2 }).format(Number(value) || 0);
    const round2 = (value) => Math.round((Number(value) + Number.EPSILON) * 100) / 100;
    const clamp = (value, min, max) => Math.min(max, Math.max(min, Number(value) || 0));

    function escapeHtml(value) {
        return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, (char) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        }[char]));
    }

    function csrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }

    function isPlainBody(body) {
        return body !== null && typeof body === "object"
            && !(body instanceof FormData)
            && !(body instanceof Blob)
            && !(body instanceof URLSearchParams)
            && !(body instanceof ArrayBuffer);
    }

    async function api(url, options = {}) {
        if (options.body && typeof options.body === "object" && options.body.rnc !== undefined && !String(options.body.rnc).trim()) {
            throw new Error("Escribe un RNC o cédula para consultar.");
        }
        const headers = Object.assign({ Accept: "application/json" }, options.headers || {});
        let body = options.body;
        if (isPlainBody(body)) {
            body = JSON.stringify(body);
            headers["Content-Type"] = "application/json";
        }
        if (!["GET", "HEAD", "OPTIONS"].includes((options.method || "GET").toUpperCase())) {
            const token = csrfToken();
            if (token) headers["X-CSRFToken"] = token;
        }
        const response = await fetch(url, {
            credentials: "same-origin",
            ...options,
            headers,
            body,
        });
        let data = {};
        try {
            data = await response.json();
        } catch (error) {
            data = { error: `Respuesta no válida del servidor (${response.status}).` };
        }
        if (!response.ok) {
            const err = new Error(data.error || data.message || `Error ${response.status}`);
            err.status = response.status;
            err.data = data;
            throw err;
        }
        return data;
    }

    function readStorage(key, fallback) {
        try {
            const raw = window.localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (error) {
            return fallback;
        }
    }

    function writeStorage(key, value) {
        try {
            window.localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (error) {
            return false;
        }
    }

    function removeStorage(key) {
        try {
            window.localStorage.removeItem(key);
        } catch (error) {
            /* almacenamiento no disponible */
        }
    }

    function toast(message, type = "info") {
        const stack = $("toast-stack");
        if (!stack) return;
        const icons = { success: "fa-circle-check", error: "fa-circle-exclamation", warning: "fa-triangle-exclamation", info: "fa-circle-info" };
        const node = document.createElement("div");
        node.className = `pos-toast is-${type}`;
        node.innerHTML = `<i class="fa-solid ${icons[type] || icons.info}"></i><span>${escapeHtml(message)}</span>`;
        stack.appendChild(node);
        window.setTimeout(() => {
            node.style.opacity = "0";
            node.style.transform = "translateY(6px)";
            window.setTimeout(() => node.remove(), 180);
        }, 3600);
    }

    function debounce(fn, delay) {
        let timer = null;
        return function (...args) {
            window.clearTimeout(timer);
            timer = window.setTimeout(() => fn.apply(this, args), delay);
        };
    }

    function itemById(id) {
        return state.items.find((item) => String(item.id) === String(id)) || null;
    }

    function lineById(id) {
        return state.cart.find((line) => String(line.id) === String(id)) || null;
    }

    function quantityInCart(id) {
        return state.cart
            .filter((line) => String(line.id) === String(id))
            .reduce((sum, line) => sum + line.quantity, 0);
    }

    function isService(product) {
        const type = String((product && product.type) || "").trim().toLowerCase();
        return type === "servicio" || type === "service";
    }

    function availableStock(product) {
        if (!product || isService(product)) return Infinity;
        const raw = product.availableStock === null || product.availableStock === undefined
            ? product.totalStock
            : product.availableStock;
        const available = Number(raw);
        return Math.max(0, Number.isFinite(available) ? available : 0);
    }

    function isOutOfStock(product) {
        return !isService(product) && availableStock(product) <= 0;
    }

    function stockRemaining(product) {
        if (!product || isService(product)) return Infinity;
        return round2(Math.max(0, availableStock(product) - quantityInCart(product.id)));
    }

    function hasValidRnc(client) {
        const rnc = String((client && client.rnc) || "").replace(/\D/g, "");
        return rnc.length >= 9 && rnc !== "000000000";
    }

    function ecfValue(code) {
        const found = state.ecfTypes.find((type) => type.code === code);
        if (found) return found.value;
        return code === "E31" ? "Factura de Crédito Fiscal (E31)" : "Factura de Consumo (E32)";
    }

    /* ── Cotización ───────────────────────────────────────────────────── */
    function localQuote() {
        const items = state.cart.map((line) => {
            const raw = round2(line.price * line.quantity);
            const lineDiscount = round2(raw * (line.discountRate || 0));
            const net = raw - lineDiscount;
            const afterGlobal = round2(net * (1 - state.globalDiscount));
            const itbis = round2(afterGlobal * (line.itbisRate || 0));
            return {
                id: line.id,
                quantity: line.quantity,
                price: line.price,
                discountRate: line.discountRate || 0,
                subtotal: afterGlobal,
                itbisAmount: itbis,
                total: round2(afterGlobal + itbis),
            };
        });
        const subtotalRaw = round2(items.reduce((sum, item) => sum + item.price * item.quantity, 0));
        const lineDiscounts = round2(state.cart.reduce((sum, line) => sum + line.price * line.quantity * (line.discountRate || 0), 0));
        const globalDiscount = round2(state.cart.reduce((sum, line) => sum + line.price * line.quantity * (1 - (line.discountRate || 0)), 0) * state.globalDiscount);
        const subtotal = round2(items.reduce((sum, item) => sum + item.subtotal, 0));
        const totalItbis = round2(items.reduce((sum, item) => sum + item.itbisAmount, 0));
        return {
            success: true,
            subtotalRaw,
            discountAmount: round2(lineDiscounts + globalDiscount),
            totalITBIS: totalItbis,
            subtotal,
            total: round2(subtotal + totalItbis),
            items,
            local: true,
        };
    }

    function currentTotals() {
        return state.quote || localQuote();
    }

    function scheduleQuote() {
        window.clearTimeout(state.quoteTimer);
        state.quoteTimer = window.setTimeout(() => refreshQuote(false), 180);
    }

    async function refreshQuote(notify = false) {
        if (!state.cart.length) {
            state.quote = null;
            renderTotals();
            renderCart();
            return null;
        }
        const seq = ++state.quoteSeq;
        try {
            const result = await api("/pos/cart/quote", {
                method: "POST",
                body: {
                    branchId: cfg.branchId || "",
                    discountRate: state.globalDiscount,
                    items: state.cart.map((line) => ({
                        id: line.id,
                        quantity: line.quantity,
                        discountRate: line.discountRate || 0,
                    })),
                },
            });
            if (seq !== state.quoteSeq) return state.quote;
            if (!result.success) throw new Error(result.error || "No se pudo calcular la venta.");
            state.quote = result;
            state.quoteErrorShown = false;
        } catch (error) {
            if (seq !== state.quoteSeq) return state.quote;
            state.quote = localQuote();
            if (notify && !state.quoteErrorShown) {
                state.quoteErrorShown = true;
                toast("No se pudo validar la cotización con el servidor. Se muestra un cálculo local.", "warning");
            }
        }
        renderTotals();
        renderCart();
        return state.quote;
    }

    /* ── Catálogo ─────────────────────────────────────────────────────── */
    function buildCategories() {
        const map = new Map();
        state.categories.forEach((category) => {
            if (category && category.id) map.set(String(category.id), category.name || "General");
        });
        state.items.forEach((item) => {
            const id = String(item.categoryId || "general");
            if (!map.has(id)) map.set(id, id);
        });
        state.categories = Array.from(map.entries()).map(([id, name]) => ({ id, name }));
    }

    function categoryIcon(categoryId) {
        const icons = {
            alimentos: "fa-apple-whole",
            bebidas: "fa-bottle-water",
            lacteos: "fa-cow",
            limpieza: "fa-spray-can-sparkles",
            electronica: "fa-laptop",
            servicios: "fa-handshake",
            ferreteria: "fa-screwdriver-wrench",
            general: "fa-box",
        };
        return icons[String(categoryId || "").toLowerCase()] || "fa-box";
    }

    function renderCategories() {
        const container = $("category-chips");
        if (!container) return;
        const counts = {};
        state.items.forEach((item) => {
            const id = String(item.categoryId || "general");
            counts[id] = (counts[id] || 0) + 1;
        });
        const entries = [{ id: "all", name: "Todos", count: state.items.length }]
            .concat(state.categories.map((category) => ({
                id: String(category.id),
                name: category.name,
                count: counts[String(category.id)] || 0,
            })));
        container.innerHTML = entries.map((entry) => `
            <button type="button" class="pos-cat-chip ${state.category === entry.id ? "is-active" : ""}" data-category="${escapeHtml(entry.id)}">
                ${entry.id === "all" ? '<i class="fa-solid fa-border-all"></i>' : `<i class="fa-solid ${categoryIcon(entry.id)}"></i>`}
                <span>${escapeHtml(entry.name)}</span>
                <span class="pos-chip-count">${entry.count}</span>
            </button>
        `).join("");
    }

    function filteredItems() {
        const query = state.search.trim().toLowerCase();
        return state.items.filter((item) => {
            if (state.category !== "all" && String(item.categoryId) !== state.category) return false;
            if (!query) return true;
            return item.search.includes(query);
        });
    }

    function renderProducts() {
        const grid = $("product-grid");
        const empty = $("catalog-empty");
        const count = $("catalog-count");
        if (!grid) return;
        const products = filteredItems();
        if (count) count.textContent = `${products.length} ${products.length === 1 ? "producto" : "productos"}`;
        if (empty) empty.hidden = products.length > 0;
        grid.innerHTML = products.map((product) => {
            const inCart = quantityInCart(product.id);
            const stock = availableStock(product);
            const low = stock > 0 && stock <= 5;
            const out = isOutOfStock(product);
            const maxed = !out && stockRemaining(product) <= 0;
            const blocked = out || maxed;
            const badge = out
                ? '<span class="pos-product-badge is-out">Agotado</span>'
                : (maxed
                    ? '<span class="pos-product-badge is-maxed">Máximo en carrito</span>'
                    : (product.isDemo ? '<span class="pos-product-badge">Demo</span>' : (low ? '<span class="pos-product-badge is-low">Stock bajo</span>' : "")));
            const label = out
                ? `${product.name || "Producto"} agotado`
                : (maxed ? `${product.name || "Producto"}, máximo en carrito` : `Agregar ${product.name || "Producto"}`);
            const media = product.imageUrl
                ? `<img src="${escapeHtml(product.imageUrl)}" alt="" loading="lazy" onerror="this.style.display='none'">`
                : `<i class="fa-solid ${categoryIcon(product.categoryId)}"></i>`;
            return `
                <button type="button" class="pos-product ${inCart ? "is-in-cart" : ""} ${out ? "is-out-of-stock" : ""} ${maxed ? "is-maxed" : ""}" data-product-id="${escapeHtml(product.id)}" role="listitem" aria-label="${escapeHtml(label)}" ${blocked ? 'disabled aria-disabled="true"' : ""}>
                    <span class="pos-product-media">
                        ${media}
                        ${badge}
                        ${inCart ? `<span class="pos-product-qty">${inCart}</span>` : ""}
                    </span>
                    <span class="pos-product-body">
                        <span class="pos-product-name">${escapeHtml(product.name || "Producto")}</span>
                        <span class="pos-product-sku">${escapeHtml(product.code || product.barcode || product.unit || "")}</span>
                        <span class="pos-product-foot">
                            <span class="pos-product-price">${money(product.price)}</span>
                            <span class="pos-product-tax">${product.itbisRate > 0 ? `ITBIS ${Math.round(product.itbisRate * 100)}%` : "Exento"}</span>
                        </span>
                    </span>
                </button>
            `;
        }).join("");
    }

    function setCategory(categoryId) {
        state.category = categoryId;
        renderCategories();
        renderProducts();
    }

    function applySearch(value) {
        state.search = value;
        const clear = $("search-clear");
        if (clear) clear.hidden = !value;
        renderProducts();
    }

    function addToCart(productId) {
        const product = itemById(productId);
        if (!product) return false;
        let increment = 1;
        if (!isService(product)) {
            const available = availableStock(product);
            const inCart = quantityInCart(product.id);
            if (available <= 0) {
                toast(`"${product.name}" está agotado en ${cfg.warehouseName || "el almacén"}.`, "warning");
                return false;
            }
            const free = round2(available - inCart);
            if (free <= 0.0001) {
                toast(`No hay más stock disponible de "${product.name}".`, "warning");
                return false;
            }
            increment = Math.min(1, free);
        }
        const existing = lineById(product.id);
        if (existing) {
            existing.quantity = round2(existing.quantity + increment);
        } else {
            state.cart.push({
                id: product.id,
                name: product.name,
                code: product.code,
                price: product.price,
                itbisRate: product.itbisRate,
                unit: product.unit,
                categoryId: product.categoryId,
                quantity: increment,
                discountRate: 0,
            });
        }
        state.selectedLineId = product.id;
        afterCartChange();
        return true;
    }

    function setQuantity(id, quantity) {
        const line = lineById(id);
        if (!line) return;
        const product = itemById(id);
        if (product && !isService(product)) {
            const available = availableStock(product);
            if (quantity > available + 0.0001) {
                toast(`Solo hay ${qtyLabel(available)} disponible(s) de "${product.name}".`, "warning");
                quantity = available;
            }
        }
        if (quantity <= 0) {
            removeLine(id);
            return;
        }
        line.quantity = round2(quantity);
        afterCartChange();
    }

    function removeLine(id) {
        state.cart = state.cart.filter((line) => String(line.id) !== String(id));
        if (String(state.selectedLineId) === String(id)) state.selectedLineId = null;
        afterCartChange();
    }

    function clampCartToStock(notify = false) {
        let changed = false;
        state.cart = state.cart.map((line) => {
            const product = itemById(line.id);
            if (!product || isService(product)) return line;
            const available = availableStock(product);
            if (available <= 0) {
                changed = true;
                return null;
            }
            if (Number(line.quantity) > available + 0.0001) {
                changed = true;
                return { ...line, quantity: round2(available) };
            }
            return line;
        }).filter(Boolean);
        if (changed && notify) toast("Se ajustó el carrito por falta de stock.", "warning");
        return changed;
    }

    function afterCartChange() {
        state.quote = null;
        renderProducts();
        renderCart();
        renderTotals();
        saveDraftSoon();
        scheduleQuote();
    }

    /* ── Carrito ──────────────────────────────────────────────────────── */
    function quoteItemFor(line) {
        if (!state.quote || !Array.isArray(state.quote.items)) return null;
        const found = state.quote.items.find((item) => String(item.id) === String(line.id));
        if (!found || Number(found.quantity) !== Number(line.quantity)) return null;
        return found;
    }

    function lineTotal(line) {
        const quoted = quoteItemFor(line);
        if (quoted) return Number(quoted.total) || 0;
        const raw = line.price * line.quantity;
        const net = raw * (1 - (line.discountRate || 0));
        const afterGlobal = net * (1 - state.globalDiscount);
        return round2(afterGlobal * (1 + (line.itbisRate || 0)));
    }

    function renderCart() {
        const container = $("cart-lines");
        const empty = $("cart-empty");
        const badge = $("cart-count-badge");
        const mobileBadge = $("mobile-cart-count");
        const clearBtn = $("btn-clear-cart");
        if (!container) return;

        const count = state.cart.reduce((sum, line) => sum + line.quantity, 0);
        if (badge) badge.textContent = state.cart.length;
        if (mobileBadge) mobileBadge.textContent = state.cart.length;
        if (empty) empty.hidden = state.cart.length > 0;
        if (clearBtn) clearBtn.hidden = state.cart.length === 0;
        container.hidden = state.cart.length === 0;

        container.innerHTML = state.cart.map((line) => {
            const discount = Math.round((line.discountRate || 0) * 10000) / 100;
            const tax = line.itbisRate > 0 ? `ITBIS ${Math.round(line.itbisRate * 100)}%` : "Exento";
            return `
                <div class="pos-cart-line ${String(state.selectedLineId) === String(line.id) ? "is-selected" : ""}" data-line-id="${escapeHtml(line.id)}">
                    <div>
                        <div class="pos-line-name">${escapeHtml(line.name)}</div>
                        <div class="pos-line-meta">
                            <span>${money(line.price)} c/u</span>
                            <span class="pos-dot"></span>
                            <span>${tax}</span>
                            ${discount > 0 ? `<span class="pos-line-discount">−${discount}%</span>` : ""}
                            <button type="button" class="pos-line-discount-button" data-action="line-discount">Descuento</button>
                        </div>
                    </div>
                    <div class="pos-line-total">${money(lineTotal(line))}</div>
                    <div class="pos-line-controls">
                        <div class="pos-qty">
                            <button type="button" data-action="qty-minus" aria-label="Disminuir"><i class="fa-solid fa-minus"></i></button>
                            <span>${line.quantity % 1 === 0 ? line.quantity : numberFormat.format(line.quantity)}</span>
                            <button type="button" data-action="qty-plus" aria-label="Aumentar"><i class="fa-solid fa-plus"></i></button>
                        </div>
                        <button type="button" class="pos-line-remove" data-action="remove" aria-label="Eliminar línea">
                            <i class="fa-regular fa-trash-can"></i>
                        </button>
                    </div>
                </div>
            `;
        }).join("");

        if ($("cart-empty")) $("cart-empty").hidden = state.cart.length > 0;
        renderTotals();
    }

    function renderTotals() {
        const totals = currentTotals();
        const total = Number(totals.total) || 0;
        const subtotalRaw = Number(totals.subtotalRaw) || 0;
        const discount = Number(totals.discountAmount) || 0;
        const itbis = Number(totals.totalITBIS) || 0;

        $("sum-subtotal").textContent = money(subtotalRaw);
        $("sum-itbis").textContent = money(itbis);
        $("sum-total").textContent = money(total);
        const tabletTotal = $("tablet-cart-total");
        if (tabletTotal) tabletTotal.textContent = money(total);
        $("checkout-total").textContent = money(total);
        $("sum-usd").textContent = usd(state.usdRate > 0 ? total / state.usdRate : 0);
        $("usd-rate-label").textContent = state.usdRate > 0 ? `Tasa ${money(state.usdRate)}` : "Tasa —";

        const discountRow = $("discount-row");
        discountRow.hidden = discount < 0.005;
        $("sum-discount").textContent = moneyNeg(discount);

        const checkout = $("btn-checkout");
        checkout.disabled = state.cart.length === 0 || total <= 0 || state.isSubmitting;
    }

    /* ── Descuentos ───────────────────────────────────────────────────── */
    function openDiscount(target) {
        state.discountTarget = target;
        const isLine = target && target.type === "line";
        const current = isLine ? (lineById(target.id)?.discountRate || 0) : state.globalDiscount;
        $("discount-eyebrow").textContent = isLine ? "Descuento de línea" : "Descuento global";
        $("discount-title").textContent = isLine ? "Ajustar producto" : "Ajustar venta";
        $("discount-input").value = String(round2(current * 100));
        openModal("discount-modal");
        window.setTimeout(() => $("discount-input").focus(), 40);
    }

    function applyDiscount() {
        const percent = clamp($("discount-input").value, 0, 100);
        const rate = round2(percent / 100 * 10000) / 10000;
        if (state.discountTarget && state.discountTarget.type === "line") {
            const line = lineById(state.discountTarget.id);
            if (line) line.discountRate = rate;
        } else {
            state.globalDiscount = rate;
        }
        closeModal("discount-modal");
        state.quote = null;
        saveDraftSoon();
        renderCart();
        renderTotals();
        scheduleQuote();
    }

    /* ── Cliente ──────────────────────────────────────────────────────── */
    function updateClientUI() {
        const valid = hasValidRnc(state.client);
        $("client-name").textContent = state.client.name || "Consumidor final";
        $("client-rnc").textContent = `RNC ${state.client.rnc || "000000000"}`;
        $("topbar-client-label").textContent = state.client.id === "default" ? "Consumidor final" : (state.client.name || "Cliente");
        $("client-avatar").innerHTML = valid
            ? escapeHtml((state.client.name || "C").slice(0, 2).toUpperCase())
            : '<i class="fa-regular fa-user"></i>';
        const e31Button = document.querySelector('[data-ecf="E31"]');
        if (e31Button) e31Button.disabled = !valid;
        if (!valid && state.ecfCode === "E31") setEcf("E32");
        updateEcfUI();
    }

    function updateEcfUI() {
        $$("#ecf-switch [data-ecf]").forEach((button) => {
            button.classList.toggle("is-active", button.dataset.ecf === state.ecfCode);
        });
        const badge = $("checkout-ecf-badge");
        if (badge) badge.textContent = state.ecfCode;
    }

    function setEcf(code) {
        if (code === "E31" && !hasValidRnc(state.client)) {
            toast("Para emitir E31 selecciona un cliente con RNC o cédula.", "warning");
            return;
        }
        state.ecfCode = code;
        updateEcfUI();
        saveDraftSoon();
    }

    function selectClient(client) {
        const rnc = String(client.rnc || "").replace(/\D/g, "");
        state.client = {
            id: client.id || client.uid || "",
            name: client.razonSocial || client.name || client.companyName || "Cliente",
            rnc: rnc || "000000000",
            email: client.email || "",
            telefono: client.telefono || client.phone || "",
            direccion: client.direccion || client.address || "",
            isDgiiLookup: Boolean(client.isDgiiLookup) || client.id === "dgii-lookup",
        };
        if (!hasValidRnc(state.client)) state.client.rnc = "000000000";
        updateClientUI();
        closeModal("client-modal");
        closeModal("new-client-modal");
        saveDraftSoon();
        if (hasValidRnc(state.client)) {
            toast(`Cliente: ${state.client.name}`, "success");
        }
    }

    function clearClient() {
        state.client = { ...DEFAULT_CLIENT };
        setEcf("E32");
        updateClientUI();
        saveDraftSoon();
    }

    async function loadClients() {
        if (state.clientCache) return state.clientCache;
        try {
            const result = await api("/api/clients/list");
            state.clientCache = Array.isArray(result.clients) ? result.clients : [];
        } catch (error) {
            state.clientCache = [];
        }
        return state.clientCache;
    }

    function renderClientList() {
        const list = $("client-list");
        const empty = $("client-list-empty");
        if (!list) return;
        const query = ($("client-search").value || "").trim().toLowerCase();
        const clients = (state.clientCache || []).filter((client) => {
            if (!query) return true;
            return `${client.name || ""} ${client.rnc || ""}`.toLowerCase().includes(query);
        }).slice(0, 80);
        empty.hidden = clients.length > 0;
        list.innerHTML = clients.map((client) => `
            <button type="button" class="pos-client-row" data-client-id="${escapeHtml(client.id)}">
                <span class="pos-client-avatar">${escapeHtml((client.name || "C").slice(0, 2).toUpperCase())}</span>
                <span>
                    <strong>${escapeHtml(client.name || "Cliente")}</strong>
                    <small>RNC ${escapeHtml(client.rnc || "—")}${client.email ? ` · ${escapeHtml(client.email)}` : ""}</small>
                </span>
            </button>
        `).join("");
        list._clients = clients;
    }

    function isTaxIdQuery(value) {
        const digits = String(value || "").replace(/\D/g, "");
        return digits.length === 9 || digits.length === 11;
    }

    function clearDgiiResult() {
        const result = $("client-dgii-result");
        if (!result) return;
        result.hidden = true;
        result.innerHTML = "";
        delete result._client;
    }

    async function lookupClientInDgii(rawValue = $("client-search").value) {
        const raw = String(rawValue || "").trim();
        const rnc = raw.replace(/\D/g, "");
        if (!rnc || !isTaxIdQuery(raw)) return;
        const local = (state.clientCache || []).find((client) => String(client.rnc || "").replace(/\D/g, "") === rnc);
        if (local) return;
        if (state.lastDgiiLookupRnc === rnc) return;
        state.lastDgiiLookupRnc = rnc;
        const result = $("client-dgii-result");
        result.hidden = false;
        result.innerHTML = '<span class="pos-client-dgii-loading"><i class="fa-solid fa-spinner fa-spin"></i> Consultando padrón DGII…</span>';
        try {
            const response = await api("/pos/client/lookup", { method: "POST", body: { rnc: String(rnc), query: String(rnc), source: "client-search" } });
            if (!response.success || !response.client) throw new Error(response.error || "No encontrado en la DGII.");
            const client = response.client;
            result.innerHTML = `
                <div class="pos-client-dgii-copy">
                    <span class="pos-client-avatar"><i class="fa-solid fa-building-circle-check"></i></span>
                    <span><strong>${escapeHtml(client.name || client.razonSocial || "Contribuyente")}</strong><small>${escapeHtml(client.rnc || rnc)} · Verificado en DGII</small></span>
                </div>
                <button type="button" class="pos-btn pos-btn-primary" data-select-dgii>Usar para esta venta</button>
                <button type="button" class="pos-btn pos-btn-ghost" data-register-dgii>Registrar cliente</button>
            `;
            result._client = client;
        } catch (error) {
            result.innerHTML = `<span class="pos-client-dgii-error"><i class="fa-solid fa-circle-exclamation"></i> ${escapeHtml(error.message || "No se encontró en la DGII.")}</span>`;
            toast(error.message || "No se pudo consultar la DGII.", "error");
        }
    }

    async function openClientModal() {
        openModal("client-modal");
        $("client-search").value = "";
        clearDgiiResult();
        await loadClients();
        renderClientList();
        window.setTimeout(() => $("client-search").focus(), 40);
    }

    function openNewClientModal() {
        const rnc = ($("client-search").value || "").replace(/\D/g, "");
        $("new-client-rnc").value = rnc;
        $("new-client-name").value = "";
        $("new-client-email").value = "";
        $("new-client-phone").value = "";
        $("new-client-address").value = "";
        $("new-client-error").hidden = true;
        closeModal("client-modal");
        openModal("new-client-modal");
        window.setTimeout(() => $("new-client-rnc").focus(), 40);
    }

    async function lookupRnc() {
        const rnc = ($("new-client-rnc").value || "").replace(/\D/g, "");
        if (!rnc || !isTaxIdQuery(rnc)) {
            toast("Escribe un RNC de 9 dígitos o una cédula de 11 dígitos.", "warning");
            return;
        }
        if (state.lastDgiiLookupRnc === rnc && $("new-client-name").value.trim()) {
            toast("Este RNC ya fue consultado.", "info");
            return;
        }
        const button = $("btn-lookup-rnc");
        button.disabled = true;
        try {
            const result = await api("/pos/client/lookup", { method: "POST", body: { rnc: String(rnc), source: "new-client" } });
            state.lastDgiiLookupRnc = rnc;
            if (result.success && result.client) {
                selectClient(result.client);
                toast("Cliente encontrado y seleccionado.", "success");
            } else {
                toast(result.error || "No se encontró el RNC.", "warning");
            }
        } catch (error) {
            toast(error.message || "No se pudo consultar el RNC.", "error");
        } finally {
            button.disabled = false;
        }
    }

    async function saveNewClient(event) {
        event.preventDefault();
        const rnc = ($("new-client-rnc").value || "").replace(/\D/g, "");
        const name = ($("new-client-name").value || "").trim();
        if (!name || !rnc) {
            showNewClientError("RNC y razón social son obligatorios.");
            return;
        }
        const button = $("btn-save-client");
        button.disabled = true;
        try {
            const result = await api("/clients/ajax_create", {
                method: "POST",
                body: {
                    rnc,
                    razonSocial: name,
                    email: $("new-client-email").value.trim(),
                    telefono: $("new-client-phone").value.trim(),
                    direccion: $("new-client-address").value.trim(),
                },
            });
            if (!result.success) throw new Error(result.error || "No se pudo guardar el cliente.");
            state.clientCache = null;
            selectClient(result.client);
            toast("Cliente registrado.", "success");
        } catch (error) {
            showNewClientError(error.message || "No se pudo guardar el cliente.");
        } finally {
            button.disabled = false;
        }
    }

    function showNewClientError(message) {
        const error = $("new-client-error");
        error.textContent = message;
        error.hidden = false;
    }

    /* ── Cobro ────────────────────────────────────────────────────────── */
    function paymentTotal() {
        return round2(state.payments.reduce((sum, payment) => sum + (Number(payment.amount) || 0), 0));
    }

    function totalsForCheckout() {
        return currentTotals();
    }

    function resetPayments(total, method = "Efectivo") {
        state.payments = [{ method, amount: round2(total), reference: "", cashReceived: 0, usdAmount: 0 }];
    }

    function paymentMethods() {
        const methods = ["Efectivo", "Tarjeta", "Transferencia", "Cheque", "Efectivo USD"];
        if (hasValidRnc(state.client)) methods.push("Crédito");
        return methods;
    }

    function creditTotal() {
        return round2(state.payments
            .filter((payment) => payment.method === "Crédito")
            .reduce((sum, payment) => sum + (Number(payment.amount) || 0), 0));
    }

    function paymentCondition(total) {
        const credit = creditTotal();
        const amount = round2(Number(total) || 0);
        if (credit <= 0.009) return "contado";
        if (amount > 0 && credit >= amount - 0.009) return "credito";
        return "mixto";
    }

    function updateConditionUI(total) {
        const badge = $("pay-condition-badge");
        const detail = $("pay-condition-detail");
        if (!badge || !detail) return;
        const amount = round2(Number(total) || 0);
        const credit = creditTotal();
        const condition = paymentCondition(amount);
        const labels = { contado: "Contado", mixto: "Mixto", credito: "Crédito" };
        badge.textContent = labels[condition];
        badge.dataset.state = condition;
        if (condition === "contado") {
            detail.textContent = "Sin monto a crédito";
        } else if (condition === "mixto") {
            detail.textContent = `${money(credit)} a crédito · ${money(Math.max(0, round2(amount - credit)))} de contado`;
        } else {
            detail.textContent = `${money(credit)} a crédito`;
        }
    }

    function addCreditPayment() {
        const total = round2(totalsForCheckout().total);
        if (!hasValidRnc(state.client)) {
            toast("Selecciona un cliente con RNC o cédula para vender a crédito.", "warning");
            openClientModal();
            return;
        }
        const remaining = round2(total - paymentTotal());
        if (remaining < -0.009) {
            toast("Los pagos exceden el total. Ajusta los montos.", "warning");
            return;
        }
        const creditRow = state.payments.find((payment) => payment.method === "Crédito");
        if (remaining <= 0.009) {
            toast(
                creditRow
                    ? "El pago ya está completo."
                    : "Reduce el monto de contado para dejar un saldo a crédito.",
                "info",
            );
            return;
        }
        if (creditRow) {
            creditRow.amount = round2((Number(creditRow.amount) || 0) + remaining);
        } else {
            state.payments.push({ method: "Crédito", amount: remaining, reference: "", cashReceived: 0, usdAmount: 0 });
        }
        renderPaymentRows();
    }

    function setAllCash() {
        resetPayments(totalsForCheckout().total, "Efectivo");
        renderPaymentRows();
    }

    function setAllCredit() {
        if (!hasValidRnc(state.client)) {
            toast("Selecciona un cliente con RNC o cédula para vender a crédito.", "warning");
            openClientModal();
            return;
        }
        resetPayments(totalsForCheckout().total, "Crédito");
        renderPaymentRows();
    }

    function needsReference(method) {
        return ["Tarjeta", "Transferencia", "Cheque"].includes(method);
    }

    function renderPaymentRows() {
        const container = $("payment-rows");
        if (!container) return;
        const methods = paymentMethods();
        container.innerHTML = state.payments.map((payment, index) => {
            const isUsd = payment.method === "Efectivo USD";
            const amountValue = isUsd
                ? (payment.usdAmount || (state.usdRate > 0 ? round2((payment.amount || 0) / state.usdRate) : 0))
                : (payment.amount || 0);
            const methodOptions = methods
                .concat(methods.includes(payment.method) ? [] : [payment.method])
                .map((method) => `<option value="${escapeHtml(method)}" ${method === payment.method ? "selected" : ""}>${escapeHtml(method)}</option>`)
                .join("");
            return `
                <div class="pos-payment-row" data-payment-index="${index}">
                    <div class="pos-field">
                        <label>Método</label>
                        <select data-pay-method>${methodOptions}</select>
                    </div>
                    <div class="pos-field">
                        <label>${isUsd ? "Monto USD" : "Monto DOP"}</label>
                        <input type="number" min="0" step="0.01" inputmode="decimal" data-pay-amount value="${escapeHtml(amountValue)}">
                    </div>
                    <button type="button" class="pos-payment-remove" data-pay-remove aria-label="Eliminar pago">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                    ${needsReference(payment.method) ? `
                        <div class="pos-field pos-payment-ref">
                            <label>Referencia / autorización</label>
                            <input type="text" data-pay-reference maxlength="80" value="${escapeHtml(payment.reference || "")}" placeholder="Últimos dígitos, autorización, cheque…">
                        </div>
                    ` : ""}
                    ${isUsd ? `<div class="pos-usd-hint">${usd(amountValue)} = ${money(payment.amount || 0)} · Tasa ${money(state.usdRate)}</div>` : ""}
                    ${payment.method === "Efectivo" ? `
                        <div class="pos-cash-hint">
                            <input type="number" min="0" step="0.01" inputmode="decimal" data-cash-received value="${escapeHtml(payment.cashReceived || "")}" placeholder="Recibido">
                            <span data-cash-change>${cashChangeLabel(payment)}</span>
                        </div>
                    ` : ""}
                </div>
            `;
        }).join("");
        renderCashPresets();
        updatePaySummary();
    }

    function renderCashPresets() {
        const container = $("cash-presets");
        if (!container) return;
        const cash = state.payments.find((payment) => payment.method === "Efectivo");
        const cashAmount = round2(Number(cash && cash.amount) || 0);
        if (!cash || cashAmount <= 0) {
            container.hidden = true;
            container.innerHTML = "";
            return;
        }
        const amounts = [...new Set([cashAmount, Math.ceil(cashAmount / 100) * 100, Math.ceil(cashAmount / 500) * 500])]
            .filter((amount) => amount >= cashAmount)
            .slice(0, 3);
        container.hidden = false;
        container.innerHTML = amounts.map((amount) => `
            <button type="button" class="pos-cash-preset" data-cash-preset="${amount}">${money(amount)}</button>
        `).join("");
    }

    function cashChangeLabel(payment) {
        const received = Number(payment.cashReceived) || 0;
        if (!received) return "Opcional: calcula el cambio";
        const diff = round2(received - (Number(payment.amount) || 0));
        if (diff > 0.009) return `Cambio ${money(diff)}`;
        if (diff < -0.009) return `Falta ${money(Math.abs(diff))}`;
        return "Monto exacto";
    }

    function updatePaySummary() {
        const total = round2(totalsForCheckout().total);
        const paid = paymentTotal();
        const remaining = round2(total - paid);
        const credit = creditTotal();
        const conditionLabel = { contado: "Contado", mixto: "Mixto", credito: "Crédito" }[paymentCondition(total)];
        const paySummary = document.querySelector(".pos-pay-summary");
        if (paySummary) {
            paySummary.classList.toggle("is-paid", Math.abs(remaining) <= 0.01);
            paySummary.classList.toggle("is-over", remaining < -0.01);
        }
        $("pay-total").textContent = money(total);
        $("pay-remaining").textContent = remaining >= -0.009 ? money(Math.max(0, remaining)) : `Excede ${money(Math.abs(remaining))}`;
        updateConditionUI(total);

        const status = $("checkout-payment-status");
        if (!state.payments.length) {
            status.textContent = "Agrega un método de pago";
            status.dataset.state = "pending";
        } else if (Math.abs(remaining) <= 0.01) {
            status.textContent = credit > 0
                ? `Pago completo · ${conditionLabel} (${money(credit)} a crédito)`
                : `Pago completo · ${conditionLabel}`;
            status.style.color = "var(--pos-green)";
            status.dataset.state = "paid";
        } else if (remaining > 0) {
            status.textContent = `Falta ${money(remaining)}`;
            status.style.color = "var(--pos-orange-strong)";
            status.dataset.state = "pending";
        } else {
            status.textContent = `Excede ${money(Math.abs(remaining))}`;
            status.style.color = "var(--pos-red)";
            status.dataset.state = "over";
        }

        const hasCredit = state.payments.some((payment) => payment.method === "Crédito");
        const creditValid = !hasCredit || hasValidRnc(state.client);
        const amountsValid = state.payments.length > 0 && state.payments.every((payment) => Number(payment.amount) > 0);
        const canConfirm = amountsValid && Math.abs(remaining) <= 0.01 && creditValid && !state.isSubmitting;
        $("btn-confirm-sale").disabled = !canConfirm;
        $("btn-confirm-sale").classList.toggle("is-ready", canConfirm);

        if (hasCredit && !creditValid) {
            showCheckoutError("El pago a crédito requiere un cliente con RNC o cédula.", "credit");
        } else {
            hideCheckoutError("credit");
        }
    }

    function showCheckoutError(message, kind) {
        const error = $("checkout-error");
        error.textContent = message;
        error.dataset.kind = kind || "general";
        error.hidden = false;
    }

    function hideCheckoutError(kind) {
        const error = $("checkout-error");
        if (kind && error.dataset.kind !== kind) return;
        error.hidden = true;
        error.textContent = "";
        delete error.dataset.kind;
    }

    function renderCheckout() {
        const totals = totalsForCheckout();
        $("pay-total").textContent = money(totals.total);
        $("checkout-ecf-badge").textContent = state.ecfCode;
        $("checkout-notes").value = state.cart.notes || "";

        const client = state.client;
        $("checkout-client").innerHTML = `
            <span class="pos-client-avatar">${hasValidRnc(client) ? escapeHtml((client.name || "C").slice(0, 2).toUpperCase()) : '<i class="fa-regular fa-user"></i>'}</span>
            <span>
                <strong>${escapeHtml(client.name || "Consumidor final")}</strong>
                <small>RNC ${escapeHtml(client.rnc || "000000000")} · ${state.ecfCode === "E31" ? "Crédito fiscal" : "Consumo"}</small>
            </span>
        `;

        const lines = state.cart.map((line) => {
            const quoted = quoteItemFor(line);
            const total = quoted ? quoted.total : lineTotal(line);
            return `<div class="pos-checkout-line"><span>${line.quantity} × ${escapeHtml(line.name)}</span><strong>${money(total)}</strong></div>`;
        }).join("");
        $("checkout-lines").innerHTML = lines;

        const discount = Number(totals.discountAmount) || 0;
        $("checkout-breakdown").innerHTML = `
            <div class="pos-total-row"><span>Subtotal</span><strong>${money(totals.subtotalRaw)}</strong></div>
            ${discount > 0.005 ? `<div class="pos-total-row"><span>Descuento</span><strong class="pos-negative">${moneyNeg(discount)}</strong></div>` : ""}
            <div class="pos-total-row"><span>ITBIS</span><strong>${money(totals.totalITBIS)}</strong></div>
            <div class="pos-total-row pos-total-grand"><span>Total</span><strong>${money(totals.total)}</strong></div>
        `;

        const currentPaid = paymentTotal();
        if (!state.payments.length || Math.abs(currentPaid - Number(totals.total)) > 0.01) {
            resetPayments(totals.total);
        }
        renderPaymentRows();
        updatePaySummary();
    }

    async function openCheckout() {
        if (!state.cart.length) {
            toast("Agrega productos al carrito.", "warning");
            return;
        }
        if (state.ecfCode === "E31" && !hasValidRnc(state.client)) {
            toast("Selecciona un cliente con RNC para emitir E31.", "warning");
            openClientModal();
            return;
        }
        hideCheckoutError();
        state.isSubmitting = false;
        await refreshQuote(true);
        const totals = totalsForCheckout();
        if (!totals || Number(totals.total) <= 0) {
            toast("No se pudo calcular el total de la venta.", "error");
            return;
        }
        renderCheckout();
        openModal("checkout-modal");
    }

    function addPayment() {
        const total = round2(totalsForCheckout().total);
        const remaining = round2(total - paymentTotal());
        if (remaining <= 0.009) {
            toast("El pago ya está completo.", "info");
            return;
        }
        state.payments.push({ method: "Efectivo", amount: remaining, reference: "", cashReceived: 0, usdAmount: 0 });
        renderPaymentRows();
    }

    function applyExactPayment() {
        const total = round2(totalsForCheckout().total);
        if (!state.payments.length) {
            resetPayments(total);
        } else if (state.payments.length === 1) {
            state.payments[0].amount = total;
            if (state.payments[0].method === "Efectivo USD") {
                state.payments[0].usdAmount = state.usdRate > 0 ? round2(total / state.usdRate) : 0;
            }
        } else {
            const remaining = round2(total - paymentTotal());
            if (remaining > 0.009) {
                state.payments.push({ method: "Efectivo", amount: remaining, reference: "", cashReceived: 0, usdAmount: 0 });
            }
        }
        renderPaymentRows();
    }

    function syncPaymentRow(index) {
        const row = document.querySelector(`[data-payment-index="${index}"]`);
        const payment = state.payments[index];
        if (!row || !payment) return;
        const amountInput = row.querySelector("[data-pay-amount]");
        if (amountInput) {
            const value = Number(amountInput.value) || 0;
            if (payment.method === "Efectivo USD") {
                payment.usdAmount = value;
                payment.amount = round2(value * state.usdRate);
            } else {
                payment.amount = value;
                payment.usdAmount = 0;
            }
        }
        const referenceInput = row.querySelector("[data-pay-reference]");
        if (referenceInput) payment.reference = referenceInput.value;
        const cashInput = row.querySelector("[data-cash-received]");
        if (cashInput) payment.cashReceived = Number(cashInput.value) || 0;
        const change = row.querySelector("[data-cash-change]");
        if (change) change.textContent = cashChangeLabel(payment);
        const usdHint = row.querySelector(".pos-usd-hint");
        if (usdHint && payment.method === "Efectivo USD") {
            usdHint.textContent = `${usd(payment.usdAmount)} = ${money(payment.amount)} · Tasa ${money(state.usdRate)}`;
        }
        updatePaySummary();
    }

    function ensureCheckoutKey(payload) {
        const hash = JSON.stringify(payload);
        if (!state.checkoutKey || state.checkoutKeyHash !== hash) {
            state.checkoutKey = (window.crypto && window.crypto.randomUUID)
                ? window.crypto.randomUUID()
                : `pos-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            state.checkoutKeyHash = hash;
        }
        return state.checkoutKey;
    }

    async function confirmSale() {
        if ($("btn-confirm-sale").disabled || state.isSubmitting) return;
        if (!Array.isArray(state.cart) || state.cart.length === 0) {
            closeModal("checkout-modal");
            toast("El carrito está vacío. Agrega al menos un producto.", "warning");
            renderCart();
            return;
        }
        const totals = totalsForCheckout();
        const paid = paymentTotal();
        if (Math.abs(round2(totals.total - paid)) > 0.01) {
            showCheckoutError(`La suma de pagos debe ser igual al total (${money(totals.total)}).`);
            return;
        }
        if (state.payments.some((payment) => payment.method === "Crédito") && !hasValidRnc(state.client)) {
            showCheckoutError("El pago a crédito requiere un cliente con RNC o cédula.");
            return;
        }

        const ephemeralClient = Boolean(state.client.isDgiiLookup) || state.client.id === "dgii-lookup";
        const payload = {
            clientId: ephemeralClient ? "dgii-lookup" : (state.client.id === "default" ? "" : state.client.id),
            clientRnc: ephemeralClient ? state.client.rnc : "",
            clientName: ephemeralClient ? state.client.name : "",
            clientEmail: ephemeralClient ? state.client.email : "",
            clientPhone: ephemeralClient ? state.client.telefono : "",
            clientAddress: ephemeralClient ? state.client.direccion : "",
            ecfType: ecfValue(state.ecfCode),
            branchId: cfg.branchId || "",
            warehouseId: cfg.warehouseId || "",
            discountRate: state.globalDiscount,
            notes: $("checkout-notes").value.trim(),
            items: state.cart.map((line) => ({
                id: line.id,
                quantity: line.quantity,
                discountRate: line.discountRate || 0,
            })),
            payments: state.payments.map((payment) => ({
                method: payment.method,
                amount: round2(payment.amount),
                reference: payment.reference || "",
                cashReceived: Number(payment.cashReceived) || 0,
                usdAmount: Number(payment.usdAmount) || 0,
                usdExchangeRate: state.usdRate,
            })),
        };

        const key = ensureCheckoutKey(payload);
        state.isSubmitting = true;
        $("btn-confirm-sale").disabled = true;
        $("btn-confirm-sale").innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Procesando…';
        hideCheckoutError();

        try {
            const result = await api("/pos/invoice/new", {
                method: "POST",
                headers: { "Idempotency-Key": key },
                body: payload,
            });
            if (!result.success) throw new Error(result.error || "No se pudo registrar la venta.");
            if (result.clientRegistered) {
                state.clientCache = null;
                toast("Cliente registrado para la venta a crédito.", "success");
            }
            state.lastInvoice = result;
            state.checkoutKey = null;
            state.checkoutKeyHash = null;
            closeModal("checkout-modal");
            showSuccess(result, totals);
            resetAfterSale();
        } catch (error) {
            showCheckoutError(error.message || "No se pudo registrar la venta. Intenta de nuevo.");
            toast(error.message || "No se pudo registrar la venta.", "error");
        } finally {
            state.isSubmitting = false;
            const button = $("btn-confirm-sale");
            if (button) {
                button.innerHTML = '<i class="fa-solid fa-lock"></i> Confirmar venta';
                updatePaySummary();
            }
        }
    }

    function showSuccess(result, totals) {
        const consolidated = Boolean(result.consolidated);
        $("success-title").textContent = consolidated ? "Venta en consolidado" : "Venta registrada";
        $("success-message").textContent = consolidated
            ? "La venta se incluirá en el comprobante consolidado al cerrar el turno."
            : `Comprobante ${result.encf || "emitido"} generado correctamente.`;

        const methods = state.payments.map((payment) => payment.method).join(" · ");
        $("success-meta").innerHTML = `
            <div class="pos-total-row"><span>Factura</span><strong>${escapeHtml(result.invoiceNumber || "")}</strong></div>
            <div class="pos-total-row"><span>Total</span><strong>${money(result.total || totals.total)}</strong></div>
            <div class="pos-total-row"><span>Pago</span><strong>${escapeHtml(methods || "—")}</strong></div>
            ${result.encf ? `<div class="pos-total-row"><span>e-NCF</span><strong>${escapeHtml(result.encf)}</strong></div>` : ""}
        `;
        $("btn-print-receipt").dataset.invoiceId = result.invoiceId || "";
        $("btn-return-sale").hidden = !result.invoiceId || consolidated;
        openModal("success-modal");
    }

    function resetAfterSale() {
        state.cart = [];
        state.quote = null;
        state.payments = [];
        state.globalDiscount = 0;
        state.selectedLineId = null;
        state.client = { ...DEFAULT_CLIENT };
        state.ecfCode = "E32";
        removeStorage(DRAFT_KEY);
        updateClientUI();
        renderProducts();
        renderCart();
        renderTotals();
    }

    function newSale() {
        closeModal("success-modal");
        state.lastInvoice = null;
        updateClientUI();
        renderProducts();
        renderCart();
        renderTotals();
        focusSearch();
    }

    /* ── Ventas en espera ─────────────────────────────────────────────── */
    function pendingSnapshot() {
        return {
            id: `pending-${Date.now()}-${Math.random().toString(16).slice(2, 7)}`,
            createdAt: new Date().toISOString(),
            cart: state.cart.map((line) => ({ ...line })),
            client: { ...state.client },
            ecfCode: state.ecfCode,
            globalDiscount: state.globalDiscount,
            total: round2(currentTotals().total),
        };
    }

    function loadPending() {
        state.pending = readStorage(PENDING_KEY, []);
        if (!Array.isArray(state.pending)) state.pending = [];
        updatePendingCount();
    }

    function persistPending() {
        writeStorage(PENDING_KEY, state.pending);
        updatePendingCount();
    }

    function updatePendingCount() {
        const count = state.pending.length;
        const badge = $("pending-count");
        if (badge) {
            badge.textContent = count;
            badge.hidden = count === 0;
        }
    }

    function savePendingSale() {
        if (!state.cart.length) {
            toast("El carrito está vacío.", "warning");
            return;
        }
        state.pending.unshift(pendingSnapshot());
        persistPending();
        state.cart = [];
        state.quote = null;
        state.globalDiscount = 0;
        state.selectedLineId = null;
        state.client = { ...DEFAULT_CLIENT };
        state.ecfCode = "E32";
        removeStorage(DRAFT_KEY);
        updateClientUI();
        renderProducts();
        renderCart();
        renderTotals();
        toast("Venta guardada en este dispositivo.", "success");
    }

    function renderPendingList() {
        const list = $("pending-list");
        const empty = $("pending-empty");
        if (!list) return;
        empty.hidden = state.pending.length > 0;
        list.innerHTML = state.pending.map((sale) => {
            const date = new Date(sale.createdAt);
            const label = Number.isNaN(date.getTime()) ? "" : date.toLocaleString("es-DO", { dateStyle: "short", timeStyle: "short" });
            return `
                <div class="pos-pending-row" data-pending-id="${escapeHtml(sale.id)}">
                    <span class="pos-pending-info">
                        <strong>${escapeHtml(sale.client?.name || "Consumidor final")}</strong>
                        <small>${sale.cart?.length || 0} líneas · ${money(sale.total)} ${label ? `· ${escapeHtml(label)}` : ""}</small>
                    </span>
                    <button type="button" class="pos-btn pos-btn-ghost" data-pending-restore>Retomar</button>
                    <button type="button" class="pos-icon-btn" data-pending-delete aria-label="Eliminar"><i class="fa-regular fa-trash-can"></i></button>
                </div>
            `;
        }).join("");
    }

    function openPendingModal() {
        loadPending();
        renderPendingList();
        openModal("pending-modal");
    }

    function restorePending(id) {
        const sale = state.pending.find((item) => item.id === id);
        if (!sale) return;
        state.cart = (sale.cart || []).map((line) => ({ ...line }));
        clampCartToStock(true);
        if (!state.cart.length) {
            toast("La venta no tiene artículos disponibles.", "warning");
            return;
        }
        state.client = { ...(sale.client || DEFAULT_CLIENT) };
        state.ecfCode = sale.ecfCode === "E31" && hasValidRnc(state.client) ? "E31" : "E32";
        state.globalDiscount = Number(sale.globalDiscount) || 0;
        state.pending = state.pending.filter((item) => item.id !== id);
        persistPending();
        closeModal("pending-modal");
        state.quote = null;
        updateClientUI();
        renderProducts();
        renderCart();
        renderTotals();
        scheduleQuote();
        toast("Venta retomada.", "success");
    }

    /* ── Borrador local ───────────────────────────────────────────────── */
    function saveDraft() {
        if (!state.cart.length) {
            removeStorage(DRAFT_KEY);
            return;
        }
        writeStorage(DRAFT_KEY, {
            cart: state.cart,
            client: state.client,
            ecfCode: state.ecfCode,
            globalDiscount: state.globalDiscount,
            savedAt: new Date().toISOString(),
        });
    }

    const saveDraftSoon = debounce(saveDraft, 250);

    function restoreDraft() {
        const draft = readStorage(DRAFT_KEY, null);
        if (!draft || !Array.isArray(draft.cart) || !draft.cart.length) return false;
        state.cart = draft.cart.map((line) => ({
            ...line,
            price: Number(line.price) || 0,
            quantity: Number(line.quantity) || 1,
            discountRate: Number(line.discountRate) || 0,
        })).filter((line) => itemById(line.id));
        clampCartToStock(true);
        if (!state.cart.length) {
            removeStorage(DRAFT_KEY);
            return false;
        }
        state.client = draft.client && draft.client.id ? { ...draft.client } : { ...DEFAULT_CLIENT };
        state.ecfCode = draft.ecfCode === "E31" && hasValidRnc(state.client) ? "E31" : "E32";
        state.globalDiscount = Number(draft.globalDiscount) || 0;
        updateClientUI();
        renderProducts();
        renderCart();
        renderTotals();
        scheduleQuote();
        toast("Borrador anterior restaurado.", "info");
        return true;
    }

    /* ── Modales ──────────────────────────────────────────────────────── */
    function openModal(id) {
        const modal = $(id);
        if (!modal) return;
        state.modalReturnFocus = document.activeElement;
        const stackedModals = $$(".pos-modal").filter((node) => !node.hidden && node !== modal).length;
        modal.style.zIndex = stackedModals ? String(100 + stackedModals * 10) : "";
        modal.hidden = false;
        document.body.classList.add("pos-modal-open");
        const firstInput = modal.querySelector("input:not([type=hidden]), select, textarea");
        if (firstInput && !["client-modal", "checkout-modal"].includes(id)) {
            window.setTimeout(() => firstInput.focus(), 60);
        }
    }

    function closeModal(id) {
        const modal = $(id);
        if (!modal) return;
        modal.hidden = true;
        if (!anyModalOpen()) document.body.classList.remove("pos-modal-open");
        if (!anyModalOpen() && state.modalReturnFocus && typeof state.modalReturnFocus.focus === "function") {
            state.modalReturnFocus.focus();
            state.modalReturnFocus = null;
        }
    }

    function anyModalOpen() {
        return $$(".pos-modal").some((modal) => !modal.hidden);
    }

    function closeTopModal() {
        const order = ["success-modal", "pending-modal", "checkout-modal", "discount-modal", "new-client-modal", "client-modal"];
        const found = order.find((id) => {
            const modal = $(id);
            return modal && !modal.hidden;
        });
        if (found) closeModal(found);
    }

    /* ── Búsqueda y atajos ────────────────────────────────────────────── */
    function focusSearch() {
        const input = $("search-input");
        if (!input) return;
        input.focus();
        input.select();
    }

    function submitSearch() {
        const input = $("search-input");
        const query = (input.value || "").trim().toLowerCase();
        if (!query) return;
        const exact = state.items.find((item) =>
            String(item.code || "").toLowerCase() === query ||
            String(item.barcode || "").toLowerCase() === query
        );
        if (exact) {
            if (addToCart(exact.id)) {
                input.value = "";
                applySearch("");
            }
            return;
        }
        const results = filteredItems();
        if (results.length === 1) {
            if (addToCart(results[0].id)) {
                input.value = "";
                applySearch("");
            }
        }
    }

    function setMobileView(view) {
        state.mobileView = view;
        const content = $("pos-content");
        if (content) content.dataset.mobileView = view;
        $$("[data-mobile-view]").forEach((button) => {
            button.classList.toggle("is-active", button.dataset.mobileView === view);
        });
    }

    function bindEvents() {
        /* Catálogo */
        $("category-chips").addEventListener("click", (event) => {
            const button = event.target.closest("[data-category]");
            if (button) setCategory(button.dataset.category);
        });

        $("product-grid").addEventListener("click", (event) => {
            const card = event.target.closest("[data-product-id]");
            if (card) addToCart(card.dataset.productId);
        });

        /* Búsqueda */
        const searchInput = $("search-input");
        searchInput.addEventListener("input", () => applySearch(searchInput.value));
        searchInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                submitSearch();
            }
        });
        $("search-clear").addEventListener("click", () => {
            searchInput.value = "";
            applySearch("");
            focusSearch();
        });

        /* Carrito */
        $("cart-lines").addEventListener("click", (event) => {
            const lineEl = event.target.closest("[data-line-id]");
            if (!lineEl) return;
            const id = lineEl.dataset.lineId;
            state.selectedLineId = id;
            const action = event.target.closest("[data-action]");
            const line = lineById(id);
            if (!line) return;
            if (action) {
                if (action.dataset.action === "qty-plus") setQuantity(id, line.quantity + 1);
                else if (action.dataset.action === "qty-minus") setQuantity(id, line.quantity - 1);
                else if (action.dataset.action === "remove") removeLine(id);
                else if (action.dataset.action === "line-discount") openDiscount({ type: "line", id });
            } else {
                renderCart();
            }
        });

        $("btn-clear-cart").addEventListener("click", () => {
            if (!state.cart.length) return;
            if (!window.confirm("¿Vaciar el carrito de la venta actual?")) return;
            state.cart = [];
            state.quote = null;
            state.selectedLineId = null;
            afterCartChange();
        });

        $("btn-global-discount").addEventListener("click", () => openDiscount({ type: "global" }));
        $("btn-edit-global-discount").addEventListener("click", () => openDiscount({ type: "global" }));

        /* Cliente */
        $("btn-client").addEventListener("click", openClientModal);
        $("cart-client-chip").addEventListener("click", openClientModal);
        $("client-search").addEventListener("input", () => {
            renderClientList();
            clearDgiiResult();
            const currentRnc = $("client-search").value.replace(/\D/g, "");
            if (currentRnc !== state.lastDgiiLookupRnc) state.lastDgiiLookupRnc = "";
            window.clearTimeout(state.clientLookupTimer);
            const valueAtSchedule = $("client-search").value;
            if (isTaxIdQuery(valueAtSchedule)) {
                state.clientLookupTimer = window.setTimeout(() => {
                    if ($("client-search").value === valueAtSchedule) lookupClientInDgii(valueAtSchedule);
                }, 450);
            }
        });
        $("client-dgii-result").addEventListener("click", (event) => {
            const result = $("client-dgii-result");
            const client = result._client;
            if (!client) return;
            if (event.target.closest("[data-select-dgii]")) {
                selectClient(client);
                toast("Contribuyente verificado en la DGII.", "success");
            } else if (event.target.closest("[data-register-dgii]")) {
                $("new-client-rnc").value = client.rnc || "";
                $("new-client-name").value = client.name || client.razonSocial || "";
                $("new-client-email").value = client.email || "";
                $("new-client-phone").value = client.telefono || "";
                $("new-client-address").value = client.direccion || "";
                closeModal("client-modal");
                openModal("new-client-modal");
            }
        });
        $("client-search").addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                const first = $("client-list").querySelector("[data-client-id]");
                if (first) first.click();
            }
        });
        $("client-list").addEventListener("click", (event) => {
            const row = event.target.closest("[data-client-id]");
            if (!row) return;
            const clients = $("client-list")._clients || [];
            const client = clients.find((item) => String(item.id) === String(row.dataset.clientId));
            if (client) selectClient(client);
        });
        $("btn-consumer-final").addEventListener("click", clearClient);
        $("btn-new-client").addEventListener("click", openNewClientModal);
        $("new-client-form").addEventListener("submit", saveNewClient);
        $("btn-lookup-rnc").addEventListener("click", lookupRnc);

        /* ECF */
        $("ecf-switch").addEventListener("click", (event) => {
            const button = event.target.closest("[data-ecf]");
            if (button) setEcf(button.dataset.ecf);
        });

        /* Descuento */
        $("discount-presets").addEventListener("click", (event) => {
            const button = event.target.closest("[data-discount]");
            if (button) $("discount-input").value = button.dataset.discount;
        });
        $("btn-apply-discount").addEventListener("click", applyDiscount);

        /* Cobro */
        $("btn-checkout").addEventListener("click", openCheckout);
        $("btn-pay-exact").addEventListener("click", applyExactPayment);
        $("btn-add-payment").addEventListener("click", addPayment);
        $("btn-all-cash").addEventListener("click", setAllCash);
        $("btn-add-credit").addEventListener("click", addCreditPayment);
        $("btn-all-credit").addEventListener("click", setAllCredit);
        $("cash-presets").addEventListener("click", (event) => {
            const button = event.target.closest("[data-cash-preset]");
            if (!button) return;
            const cash = state.payments.find((payment) => payment.method === "Efectivo");
            if (!cash) return;
            cash.cashReceived = Number(button.dataset.cashPreset) || 0;
            renderPaymentRows();
        });

        $("payment-rows").addEventListener("input", (event) => {
            const row = event.target.closest("[data-payment-index]");
            if (!row) return;
            syncPaymentRow(Number(row.dataset.paymentIndex));
        });
        $("payment-rows").addEventListener("change", (event) => {
            const row = event.target.closest("[data-payment-index]");
            if (!row) return;
            const index = Number(row.dataset.paymentIndex);
            if (event.target.matches("[data-pay-method]")) {
                const payment = state.payments[index];
                payment.method = event.target.value;
                payment.reference = "";
                if (payment.method === "Efectivo USD") {
                    payment.usdAmount = state.usdRate > 0 ? round2((payment.amount || 0) / state.usdRate) : 0;
                } else {
                    payment.usdAmount = 0;
                    payment.cashReceived = 0;
                }
                renderPaymentRows();
            }
        });
        $("payment-rows").addEventListener("click", (event) => {
            const button = event.target.closest("[data-pay-remove]");
            if (!button) return;
            const row = button.closest("[data-payment-index]");
            const index = Number(row.dataset.paymentIndex);
            state.payments.splice(index, 1);
            renderPaymentRows();
        });

        $("btn-confirm-sale").addEventListener("click", confirmSale);

        /* Éxito */
        $("btn-print-receipt").addEventListener("click", () => {
            const id = $("btn-print-receipt").dataset.invoiceId;
            if (id) window.open(`/pos/invoice/${encodeURIComponent(id)}/print`, "_blank");
        });
        $("btn-download-receipt").addEventListener("click", () => {
            const id = $("btn-print-receipt").dataset.invoiceId;
            if (id) window.open(`/pos/invoice/${encodeURIComponent(id)}/print?download=1`, "_blank");
        });
        $("btn-share-receipt").addEventListener("click", async () => {
            const id = $("btn-print-receipt").dataset.invoiceId;
            const invoice = state.lastInvoice || {};
            const text = `Venta ${invoice.invoiceNumber || invoice.encf || id || "VykOne"} · ${money(invoice.total || 0)}`;
            if (navigator.share) {
                try {
                    await navigator.share({ title: "Comprobante VykOne", text });
                    return;
                } catch (error) {
                    if (error.name === "AbortError") return;
                }
            }
            await navigator.clipboard?.writeText(text);
            toast("Resumen copiado para compartir.", "success");
        });
        $("btn-return-sale").addEventListener("click", () => {
            const id = $("btn-print-receipt").dataset.invoiceId;
            if (id) window.open(`/fiscal-notes/create?type=E34&reference_invoice_id=${encodeURIComponent(id)}`, "_blank");
        });
        $("btn-new-sale").addEventListener("click", newSale);

        /* En espera */
        $("btn-save-pending").addEventListener("click", savePendingSale);
        $("btn-pending-sales").addEventListener("click", openPendingModal);
        $("btn-pending-top").addEventListener("click", openPendingModal);
        $("pending-list").addEventListener("click", (event) => {
            const row = event.target.closest("[data-pending-id]");
            if (!row) return;
            if (event.target.closest("[data-pending-restore]")) restorePending(row.dataset.pendingId);
            else if (event.target.closest("[data-pending-delete]")) {
                state.pending = state.pending.filter((item) => item.id !== row.dataset.pendingId);
                persistPending();
                renderPendingList();
            }
        });

        /* Backdrops / cierres */
        $$("[data-close]").forEach((element) => {
            element.addEventListener("click", () => closeModal(element.dataset.close));
        });

        /* Menú y móvil */
        $("btn-menu").addEventListener("click", () => $("pos-app").classList.toggle("is-menu-open"));
        $("btn-tablet-cart")?.addEventListener("click", () => setMobileView("cart"));
        $$(".pos-nav-item").forEach((item) => item.addEventListener("click", () => $("pos-app").classList.remove("is-menu-open")));
        $$("[data-mobile-view]").forEach((button) => {
            button.addEventListener("click", () => setMobileView(button.dataset.mobileView));
        });

        /* Teclado */
        document.addEventListener("keydown", (event) => {
            const activeModal = $$(".pos-modal").find((modal) => !modal.hidden);
            if (activeModal && event.key === "Tab") {
                const focusable = $$('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])', activeModal)
                    .filter((element) => element.offsetParent !== null);
                if (focusable.length) {
                    const first = focusable[0];
                    const last = focusable[focusable.length - 1];
                    if (event.shiftKey && document.activeElement === first) {
                        event.preventDefault();
                        last.focus();
                    } else if (!event.shiftKey && document.activeElement === last) {
                        event.preventDefault();
                        first.focus();
                    }
                }
            }
            if (event.key === "Escape") {
                if (anyModalOpen()) {
                    event.preventDefault();
                    closeTopModal();
                } else {
                    $("pos-app").classList.remove("is-menu-open");
                }
                return;
            }
            if (event.key === "F2") {
                event.preventDefault();
                focusSearch();
                return;
            }
            if (event.key === "F4") {
                event.preventDefault();
                openClientModal();
                return;
            }
            if (event.key === "F8") {
                event.preventDefault();
                openCheckout();
                return;
            }
            if (event.key === "F1") {
                event.preventDefault();
                setMobileView("catalog");
                return;
            }
            if (event.key === "Delete" && !anyModalOpen() && state.selectedLineId) {
                event.preventDefault();
                removeLine(state.selectedLineId);
                return;
            }
            if (event.key === "Enter" && !$("success-modal").hidden) {
                event.preventDefault();
                newSale();
            }
            if (event.key === "Enter" && !$("client-modal").hidden && event.target === $("client-search")) {
                event.preventDefault();
                const first = $("client-list").querySelector("[data-client-id]");
                if (first) first.click();
            }
        });

        /* Cerrar menú móvil al hacer click fuera */
        document.addEventListener("click", (event) => {
            const app = $("pos-app");
            if (!app.classList.contains("is-menu-open")) return;
            if (event.target.closest(".pos-sidebar") || event.target.closest("#btn-menu")) return;
            app.classList.remove("is-menu-open");
        });
    }

    async function loadUsdRate() {
        try {
            const result = await api("/pos/usd-rate");
            const rate = Number(result.rate);
            if (rate > 0) state.usdRate = rate;
        } catch (error) {
            state.usdRate = 58.5;
        }
        renderTotals();
    }

    function init() {
        setMobileView(state.mobileView);
        buildCategories();
        renderCategories();
        renderProducts();
        loadPending();
        updateClientUI();
        renderCart();
        renderTotals();
        bindEvents();
        loadUsdRate();
        if (!restoreDraft()) {
            window.setTimeout(() => focusSearch(), 120);
        } else {
            window.setTimeout(() => focusSearch(), 120);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
