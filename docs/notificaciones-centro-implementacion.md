# Implementación — Centro de Notificaciones unificado de VykOne

**Fecha:** 10 de noviembre de 2026

## 1. Resumen

Se transformó la campana de notificaciones (dropdown de 320px) en un **Centro de
Notificaciones** a pantalla completa (página standalone, sin sidebar/topbar) con una
**línea de tiempo unificada** y filtros por categoría. Las alertas de obligaciones
tributarias se integran **en vivo** a través de `TaxObligationService` (fuente de verdad),
sin persistirlas ni duplicar su lógica. Se añadió una capa `NotificationAggregator` que
normaliza y clasifica fuentes independientes (CRM menciones, CRM compromisos, Fiscal,
Sistema/RRHH preparadas).

## 2. Archivos

### Nuevos
- `app/services/notification_center.py` — `NotificationAggregator` (agregación, contadores,
  autorización fiscal) y `NotificationStateService` (estado de lectura por usuario+empresa).
- `templates/notifications_center.html` — página standalone (timeline, filtros, KPIs, responsive).
- `tests/test_notification_center.py` — 14 pruebas.

### Modificados
- `app/web/notifications.py` — rutas `/notifications/center` y `/notifications/center/mark-read`.
- `templates/layout.html` — la campana pasa a ser un enlace al centro con badge numérico.
- `app/__init__.py` — context processor `inject_crm_commitments` ahora inyecta también
  `notification_badge` (contadores separados).

## 3. Decisiones arquitectónicas

- **Modelo normalizado** por elemento: `id`, `type`, `category` (`crm|fiscal|system|hr`),
  `title`, `description`, `severity` (`critical|warning|info`), `status`, `is_read`,
  `created_at`, `due_date`, `action_url`, `action_label`, `source`.
- **ID estables**: `fiscal:{obligation_key}:{period_key}`, `commitment:{activityId|id}`,
  `mention:{id}` → deduplicación entre recargas.
- **Estados separados**:
  - Tributario: exclusivo de `TaxObligationService` (`completed_periods`). Marcar leída NO lo
    modifica (no se llama a `toggle_complete`).
  - Lectura: `NotificationStateService` en `users/{uid}/notification_state/{company_id}/read_items/{sha1(item_id)}`
    (subcolección escalable, no mapa ilimitado).
- **Autorización fiscal en backend**: `get_company_access(uid, company_id)` +
  `can_view_fiscal()` (owner o permiso explícito `canAccounting`/`canAccountingDashboard`/
  `canManageTaxes`/`canReportsFiscal`/`canReportsAccounting`). Si no hay permiso **no se
  consulta** `TaxObligationService` ni se devuelven datos fiscales (ocultar en UI no es
  suficiente). El aislamiento usa `company_authorization` (membresía activa).
- **Contadores separados** (sin duplicar): `mentions_unread`, `commitments_pending`,
  `fiscal_overdue`, `fiscal_upcoming`; el badge total es la suma. La fiscal se cachea 60s.

## 4. Resultados de pruebas

`./venv/bin/python -m pytest tests/test_notification_center.py tests/test_tax_obligation_service.py tests/test_company_authorization.py tests/test_dgii.py`

- **92 passed**.
- `test_notification_center.py`: 14 pruebas (autorización fiscal, aislamiento, dedup por id,
  separación de estado de lectura vs tributario, contadores, badge, rutas y auth).
- `test_tax_obligation_service.py`: 52 pruebas (regresión del módulo fiscal — intacto).
- `test_company_authorization.py` + `test_dgii.py`: regresión de autorización/régimen.

## 5. Compatibilidad

- `TaxObligationService` y `app/countries/do/tax_obligation_rules.py` **no se modificaron**.
- `/notifications/poll` permanece intacto (regresión verificada: exige sesión, devuelve JSON).

## 6. Limitaciones pendientes

1. **Categorías Sistema y RRHH**: preparadas en el agregador (`source_system`/`source_hr`
   vacías) sin fuentes reales ni datos ficticios. Quedan listas para conectar futuras fuentes.
2. **Estado de atención**: no se implementó un estado independiente (por decisión aprobada);
   el estado tributario depende solo de `TaxObligationService`.
3. **Badge de menciones**: usa el campo `read` legacy de cada notificación (comportamiento
   existente conservado); la lectura de menciones se mantiene vía `/notifications/mark-read`.
4. **"Marcar todo como leído"**: el centro marca elementos de forma individual; no se añadió
   un botón global (el endpoint legacy `/notifications/mark-read` sigue disponible).
5. **Nota de entorno**: la suite completa del repositorio presenta fallos preexistentes
   (p. ej. `test_audit_web.py`) ajenos a este cambio, causados por la indisponibilidad de
   `google-cloud-firestore`/`grpc` y el guard de `production-agreement` en el entorno local.
