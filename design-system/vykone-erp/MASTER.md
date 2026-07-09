# Design System Master File — VykOne ERP

> **LOGIC:** When building a specific page, first check `design-system/vykone-erp/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** VykOne ERP
**Generated:** 2026-07-09 (refined manually post-audit)
**Product Type:** ERP / Business Management / Fintech / Compliance
**Design Dials:** Variance 3/10 (Minimal/Centered) | Motion 4/10 (Standard) | Density 8/10 (Dashboard)

---

## Global Rules

### Color Palette

| Role | Hex | CSS Variable | Notes |
|------|-----|--------------|-------|
| Primary | `#2563EB` | `--color-primary` | Professional blue |
| Primary Hover | `#1D4ED8` | `--color-primary-hover` | |
| Secondary | `#3B82F6` | `--color-secondary` | |
| Accent / CTA | `#059669` | `--color-accent` | Emerald green (success, CTA) |
| Background | `#F8FAFC` | `--color-background` | |
| Foreground | `#0F172A` | `--color-foreground` | |
| Muted | `#F1F5FD` | `--color-muted` | |
| Border | `#E4ECFC` | `--color-border` | |
| Success | `#059669` | `--color-success` | Green for completed/paid |
| Warning | `#D97706` | `--color-warning` | Amber for pending/attention |
| Error | `#DC2626` | `--color-error` | Red for rejected/voided |
| Info | `#3B82F6` | `--color-info` | Blue for informational |
| Destructive | `#DC2626` | `--color-destructive` | Delete/danger actions |
| Ring | `#2563EB` | `--color-ring` | Focus rings |

**Dark mode surfaces:**
| Role | Hex | Variable |
|------|-----|----------|
| Dark BG | `#0F172A` | `--dark-bg` |
| Dark Surface | `#1E293B` | `--dark-surface` |
| Dark Border | `#334155` | `--dark-border` |

### Typography

- **Heading Font:** Fira Code (monospace — ideal for ERP with NCF, fiscal codes, tabular data)
- **Body Font:** Fira Sans (sans-serif, tabular figures, highly legible)
- **Mono Font:** Fira Code (numbers in tables, codes, amounts)
- **Mood:** dashboard, data, analytics, code, technical, precise, professional

**CSS Fonts:** loaded in `layout.html` via Google Fonts with `preconnect` + `display=swap`

```css
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
```

**Type Scale:**

| Token | Size | Usage |
|-------|------|-------|
| `--text-xs` | `0.7rem` | Badges, metadata, timestamps |
| `--text-sm` | `0.78rem` | Secondary text, tables, breadcrumbs |
| `--text-base` | `0.85rem` | Body text, labels, inputs |
| `--text-md` | `0.9rem` | Subtitles |
| `--text-lg` | `1rem` | Page title |
| `--text-xl` | `1.1rem` | Section heading |
| `--text-2xl` | `1.25rem` | Card title |
| `--text-3xl` | `1.5rem` | KPI values |
| `--text-4xl` | `1.75rem` | Hero / Large display |

### Spacing (Density 8/10)

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `2px` | Tight gaps |
| `--space-sm` | `4px` | Icon gaps, inline spacing |
| `--space-md` | `8px` | Cell padding, grid gap |
| `--space-lg` | `12px` | Card padding, section gap |
| `--space-xl` | `16px` | Modal padding, section margin |
| `--space-2xl` | `24px` | Page content padding |
| `--space-3xl` | `32px` | Large section separation |

### Z-Index Scale (Unified)

| Layer | Value | Element |
|-------|-------|---------|
| `--z-base` | `0` | Normal content |
| `--z-dropdown` | `10` | Dropdowns, selects, tooltips |
| `--z-sticky` | `20` | Sticky headers, breadcrumbs |
| `--z-sidebar-overlay` | `30` | Mobile sidebar overlay |
| `--z-overlay` | `40` | Modal backdrop |
| `--z-modal` | `50` | Modal content |
| `--z-toast` | `60` | Toast notifications |
| `--z-tooltip` | `70` | Tooltips over modals |
| `--z-loader` | `9999` | Full-screen loader |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 3px rgba(0,0,0,0.06)` | Subtle lift, cards |
| `--shadow-md` | `0 4px 12px rgba(0,0,0,0.08)` | Buttons hover |
| `--shadow-lg` | `0 8px 24px rgba(0,0,0,0.12)` | Dropdowns |
| `--shadow-xl` | `0 16px 48px rgba(0,0,0,0.16)` | Modals |

---

## Component Specs

### Buttons — ALL variants MUST be defined in `_components.css`

| Class | Background | Text | Border | Usage |
|-------|-----------|------|--------|-------|
| `.btn` | N/A (base) | inherit | transparent | Layout base |
| `.btn-primary` | `--color-primary` gradient | white | none | Primary action |
| `.btn-secondary` | `--bg-input` | `--text-primary` | `--border-color` | Cancel, secondary |
| `.btn-success` | `--color-success` | white | none | Save, confirm |
| `.btn-danger` | `--color-error` | white | none | Delete, reject |
| `.btn-warning` | `--color-warning` | white | none | Warning action |
| `.btn-accent` | `--color-accent` | white | none | Accent action |
| `.btn-ghost` | transparent | `--text-secondary` | none | Table row actions |
| `.btn-link` | transparent | `--color-primary` | none | Inline navigation |
| `.btn-outline` | transparent | `--color-primary` | `--color-primary` | Outline variant |
| `.btn-icon` | transparent | `--text-muted` | none | Icon-only (32x32 circle) |
| `.btn-xs` | inherit | `0.7rem` | inherit | Extra small |
| `.btn-sm` | inherit | `0.78rem` | inherit | Small (tables) |
| `.btn-lg` | inherit | `0.92rem` | inherit | Large CTAs |
| `.btn-loading` | — | — | — | Loading state |
| `.btn:disabled` | `--border-color` | `--text-muted` | `--border-color` | Disabled (all variants) |

### Modal — ONE system in `_components.css`

**Structure:**
```html
<div class="modal-overlay" id="modal-id" role="dialog" aria-modal="true">
  <div class="modal-backdrop" onclick="closeModal('modal-id')"></div>
  <div class="modal-card modal-card--md">
    <div class="modal-header">
      <h3 class="modal-title">Title</h3>
      <button class="modal-close" onclick="closeModal('modal-id')" aria-label="Close">
        <i class="fa-solid fa-xmark"></i>
      </button>
    </div>
    <div class="modal-body">Content</div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal('modal-id')">Cancel</button>
      <button class="btn btn-primary">Confirm</button>
    </div>
  </div>
</div>
```

**Rules:**
- ONE z-index: `--z-overlay` (40)
- ONE backdrop: `rgba(0,0,0,0.4)` + `blur(8px)`
- ONE close button: `.modal-close` + `fa-xmark`
- ONE footer alignment: `justify-content: flex-end` (right-aligned buttons)
- Size variants: `--sm` (440px), default (640px), `--lg` (800px), `--xl` (960px)
- Animation: `modalFadeIn 0.2s` (backdrop) + `modalSlideIn 0.25s` (card)
- JS: `openModal(id)` / `closeModal(id)` defined in `main.js`

### Dropdown/Select — ONE system

- **Native selects**: ALL must use `class="form-select"` (no bare `<select>` elements)
- **Action menus**: `.action-menu` > `.action-menu-dropdown` (centralized in `_components.css`)
- **Account tree**: `.acco-dropdown` (centralized in `_components.css`)
- **Row menus**: `.row-menu-dropdown` (centralized in `_components.css`)
- **Tom Select**: Only for async search with >100 options

### Form Elements

```css
.form-group { margin-bottom: var(--space-lg); }
.form-label { display: block; font-weight: 500; margin-bottom: 4px; font-size: 0.85rem; }
.form-input {
  width: 100%; height: 34px; padding: 7px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary);
  font-size: 0.85rem; font-family: var(--font-body);
}
.form-input:focus { border-color: var(--color-primary); box-shadow: var(--shadow-glow); outline: none; }
.form-error { color: var(--color-error); font-size: 0.75rem; margin-top: 4px; }
.form-hint { color: var(--text-muted); font-size: 0.75rem; margin-top: 4px; }
```

### Tables

Uses `.table-premium` (defined per theme, shared structure). All tables use sticky headers, hover rows, consistent padding.

### Tabs

ONE pattern in `_components.css`:
- `.tab-nav` container + `.tab-btn` buttons + `.tab-panel` panels
- JS: `switchTab(event, tabId)` in `main.js`
- Active class: `.tab-btn.active` + `.tab-panel.active`

### Breadcrumbs

ONE pattern in `_components.css`:
```html
<nav class="breadcrumb" aria-label="Breadcrumb">
  <a href="...">Inicio</a>
  <span class="breadcrumb-separator">/</span>
  <a href="...">Module</a>
  <span class="breadcrumb-separator">/</span>
  <span class="breadcrumb-current">Page</span>
</nav>
```

---

## Iconography — Font Awesome 6.4.0 CANONICAL

| Action | Icon | Notes |
|--------|------|-------|
| Create / New | `fa-solid fa-plus` | |
| Edit | `fa-solid fa-pen-to-square` | **NOT fa-pen** (FA5) |
| Delete | `fa-solid fa-trash-can` | **NOT fa-trash** (FA5) |
| View | `fa-solid fa-eye` | |
| Save | `fa-solid fa-floppy-disk` | |
| Close / Cancel | `fa-solid fa-xmark` | |
| Search | `fa-solid fa-magnifying-glass` | |
| Filter | `fa-solid fa-filter` | |
| Download/Export | `fa-solid fa-file-export` | |
| Import | `fa-solid fa-file-import` | |
| Notifications | `fa-solid fa-bell` | |
| Settings | `fa-solid fa-gear` | |
| User | `fa-solid fa-circle-user` | |
| Dashboard | `fa-solid fa-grid-2` | |
| Clock/Pending | `fa-solid fa-clock` | |
| Warning | `fa-solid fa-triangle-exclamation` | |
| Check/Yes | `fa-solid fa-check` | |
| X/No | `fa-solid fa-xmark` | |
| Lightbulb/Tip | `fa-solid fa-lightbulb` | |
| Chevron down | `fa-solid fa-chevron-down` | |
| Chevron right | `fa-solid fa-chevron-right` | |

**Rules:**
- **PROHIBIDO:** Emojis as structural icons (╳ ✗ emoji ✓ ✅ ❌ ⚠️ 💡 📋)
- **PROHIBIDO:** Mixing `fa-solid` and `fa-regular` for the same action across modules
- **PROHIBIDO:** FA5 names (`fa-pen`, `fa-trash`, `fa-calendar-alt`)
- Sidebar section headers: `fa-regular` (outlined) — consistent
- Sidebar items: `fa-solid` (filled) — consistent
- All actions use `fa-solid` (filled)

---

## Navigation Rules

| Rule | Standard |
|-------|----------|
| Sidebar width | `280px` expanded / `80px` collapsed |
| localStorage collapse key | `sidebar-section-{id}` (UNIFORM across all layouts) |
| `active_page` | ONE unique value per nav item (no duplicates) |
| Breadcrumbs | Required on ALL pages deeper than dashboard |
| Back navigation | `url_for()` explicit link, NOT `history.back()` |
| Tabs | `switchTab(event, tabId)` in `main.js` |
| Utility bar items | All must check `active_page` for active state |

---

## CSS File Architecture (Target)

```
static/css/
├── _tokens.css          # Variables: colors, fonts, spacing, z-index, shadows, radii
├── _components.css      # ALL components: modal, btn, form, table, tabs, breadcrumbs, dropdowns
├── _dashboard.css       # Dashboard: KPI cards, widgets, sparklines
├── style_moderno.css    # Moderno theme (imports _tokens.css)
├── style_alegra.css     # Alegra theme (imports _tokens.css)
├── style_clasico.css    # Clasico theme (imports _tokens.css)
├── style_landing.css    # Marketing pages (separate)
└── chatbot.css          # Chatbot widget (separate)
```

**To eliminate:**
- CSS inline `<style>` blocks in templates (>50 files)
- Duplicate CSS in multiple templates (breadcrumbs x25, pagination x10, guide-close x20)
- CSS duplicated across layout.html, style_*.css, and individual templates

---

## Anti-Patterns (DO NOT USE)

- ❌ Emojis as structural icons — use Font Awesome
- ❌ FA5 icon names (`fa-pen`, `fa-trash`, `fa-calendar-alt`) — use FA6
- ❌ Mixing `fa-solid` / `fa-regular` for the same semantic action
- ❌ Hardcoded hex colors (`#ffffff`, `#cbd5e1`, `#e2e8f0`) — use CSS vars
- ❌ Inline `<style>` blocks duplicating existing CSS
- ❌ Multiple modal patterns — use ONLY `.modal-overlay` + `.modal-card`
- ❌ Bare `<select>` without `class="form-select"`
- ❌ `history.back()` for navigation — use explicit `url_for()`
- ❌ Arbitrary z-index values — use `--z-*` tokens
- ❌ Skipped heading levels (h1→h4) — use sequential hierarchy
- ❌ Inline font-size overriding CSS classes

---

## Pre-Delivery Checklist

- [ ] No emojis used as icons (Font Awesome instead)
- [ ] All icons: `fa-solid` for actions, consistent across all modules
- [ ] All selects: `class="form-select"`
- [ ] All modals: `.modal-overlay` + `.modal-card` structure
- [ ] All buttons: use classes defined in `_components.css` (no inline styles)
- [ ] Colors: CSS variables only, no hardcoded hex
- [ ] `cursor: pointer` on clickable elements
- [ ] Hover states with 150-300ms transitions
- [ ] Focus states visible (keyboard nav)
- [ ] `aria-label` on icon-only buttons
- [ ] `aria-modal="true"` on modal overlays
- [ ] `aria-live="polite"` on toast containers
- [ ] Form labels present (not placeholder-only)
- [ ] Heading hierarchy correct (no skipped levels)
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No horizontal scroll on mobile
- [ ] Dark mode contrast verified separately
