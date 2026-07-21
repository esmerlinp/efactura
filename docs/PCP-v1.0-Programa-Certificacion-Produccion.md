# Programa de Certificación para Producción — VykOne ERP v1.0

**Fecha:** 2026-07-21
**Versión:** 1.0
**Estado:** Aprobado para ejecución
**Horizonte:** 10 semanas
**Clasificación actual:** Apto con correcciones críticas
**Clasificación objetivo:** Apto para Producción Empresarial

---

## Tabla de Contenidos

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Objetivos](#2-objetivos)
3. [Alcance](#3-alcance)
4. [Fase -1 — Validación de Auditoría](#4-fase--1--validación-de-auditoría)
5. [Fase 0 — Congelamiento Funcional](#5-fase-0--congelamiento-funcional)
6. [Fase 1 — Corrección de Bloqueantes (P0)](#6-fase-1--corrección-de-bloqueantes-p0)
7. [Fase 2 — Operación Empresarial (P1)](#7-fase-2--operación-empresarial-p1)
8. [Fase 3 — Endurecimiento Empresarial (P2)](#8-fase-3--endurecimiento-empresarial-p2)
9. [Fase 4 — Certificación Go-Live](#9-fase-4--certificación-go-live)
10. [Cronograma](#10-cronograma)
11. [Matriz RACI](#11-matriz-raci)
12. [Criterios Go / No-Go](#12-criterios-go--no-go)
13. [Plan de Rollback](#13-plan-de-rollback)
14. [KPIs de Calidad](#14-kpis-de-calidad)
15. [Checklist de Certificación](#15-checklist-de-certificación)

---

## 1. Resumen Ejecutivo

### Diagnóstico

Tras auditoría integral del ERP VykOne (análisis de 95+ servicios, 34 módulos web, 38 submódulos de RRHH, 58 tests), el sistema obtuvo un score promedio de **5.7/10**. Las áreas más afectadas son nómina (5.3/10), escalabilidad (4.0/10) y cumplimiento legal (4.0/10).

### Hallazgos por clasificación

| Clasificación | Cantidad | Definición |
|--------------|----------|------------|
| Defecto confirmado en código | 14 | Error funcional, de cálculo o de arquitectura con evidencia directa en el código fuente |
| Funcionalidad faltante | 12 | Proceso de negocio necesario no implementado |
| Cumplimiento / Endurecimiento | 5 | Riesgo regulatorio o de estándar de calidad |
| Roadmap | 2 | Mejora deseable a largo plazo pero no bloqueante |

### Falsos positivos detectados en Fase -1

| Hallazgo | Clasificación original | Corrección |
|----------|----------------------|------------|
| Retroactivos de nómina "no existen" | Defecto (2/10) | **Falso positivo.** Existe `calculate_retroactive_pay()` en `payroll_service.py:808` y endpoint en `reports.py:467`. Sí existe pero usa motor legacy, no integrado en `payroll_process.py`. Reclasificado a **Funcionalidad parcial** (5/10) |
| Reingreso de empleado "no existe" | Defecto (1/10) | **Falso positivo.** Existe endpoint `offboarding_rehire()` en `offboarding.py:733` con preservación de antigüedad. Reclasificado a **Funcionalidad parcial** (6/10) — solo accesible desde offboarding, no standalone |

### Estrategia

1. **Semanas 1-4**: Solo P0 — defectos que impiden producción
2. **Semanas 5-8**: P1 — funcionalidad empresarial requerida
3. **Semanas 9-10**: Certificación, pruebas de carga, Go/No-Go

**Regla de oro:** Ninguna funcionalidad nueva de roadmap entra hasta cerrar 100% de P0 y ≥80% de P1.

---

## 2. Objetivos

### Objetivo primario

Elevar VykOne de "Apto con correcciones críticas" a "Apto para Producción Empresarial" en 10 semanas.

### Objetivos secundarios

1. Eliminar el 100% de los defectos P0 confirmados
2. Completar ≥80% de las funcionalidades empresariales P1
3. Alcanzar 100 usuarios concurrentes con tiempo de respuesta <2s
4. Obtener score ≥8.0/10 en todas las áreas de la matriz de evaluación
5. No introducir regresiones en módulos ya estables

### No-objetivos (fuera de alcance)

- Aplicación móvil nativa
- Data warehouse / BI avanzado
- Contabilidad multi-libro (IFRS + fiscal)
- Módulo de inventario avanzado (WMS)
- Nuevos países (fuera de DO)
- Funcionalidades de roadmap no relacionadas con estabilidad

---

## 3. Alcance

### Dentro del alcance

| Módulo | P0 | P1 | P2 |
|--------|----|----|-----|
| Seguridad (SoD + Workflow) | 2 | 1 | 1 |
| Nómina (TSS, Garnishments, Cálculos) | 3 | 5 | 1 |
| Contabilidad (Conciliación, Activos) | 1 | 3 | 0 |
| Facturación (Split Payment, Crédito) | 0 | 3 | 0 |
| Infraestructura (Escalabilidad, Webhooks) | 1 | 0 | 2 |
| Integridad de datos (Huérfanos) | 1 | 0 | 1 |
| Cumplimiento (TSS, GDPR) | 0 | 1 | 1 |
| API REST | 0 | 0 | 1 |
| **Totales** | **8** | **13** | **7** |

### Fuera del alcance

- Mobile App
- BI Warehouse
- Módulo de inventario WMS
- Nuevos países (MX)
- OCR avanzado
- Chatbot IA (mejoras)
- Módulo de herramientas

---

## 4. Fase -1 — Validación de Auditoría

**Duración:** 3 días (completada)
**Objetivo:** Confirmar técnicamente cada hallazgo antes de asignar recursos de desarrollo.

### Matriz de validación

#### P0 — Defectos

| # | Hallazgo | Tipo | Validación | Evidencia | Veredicto |
|---|----------|------|-----------|-----------|-----------|
| C1 | SoD general no aplicado | Defecto | ✅ | `decorators.py:13-48` — `SOD_CONFLICT_MATRIX` nunca consultado en `check_permission()` | **CONFIRMADO** |
| C2 | TSS calculado sobre base, no grossIncome | Defecto | ✅ | `concept_engine.py:67-74` — ambas ramas asignan `tss_base = base` ignorando `context.gross_income` | **CONFIRMADO** |
| C3 | GarnishmentService no integrado | Defecto | ✅ | `garnishment_service.py` implementa `process_all_garnishments()` pero `payroll_process.py:501-513` nunca lo llama | **CONFIRMADO** |
| C4 | Conciliación bancaria sin contabilidad | Defecto | ✅ | `banks.py:625-632` — completa conciliación con `con_diferencias` sin generar asiento contable | **CONFIRMADO** |
| C5 | Sin detección de datos huérfanos | Defecto | ✅ | Búsqueda exhaustiva en `app/services/` — cero resultados para `orphan`, `huerfano`, `integrity` | **CONFIRMADO** |
| C6 | Regalía pascual incorrecta | Defecto | ✅ | `payroll_process.py:348` — fórmula `max(1, month(today)-month(hireDate)+1)` falla para empleados con >1 año | **CONFIRMADO** |
| C7 | Single gunicorn worker | Defecto | ✅ | `Dockerfile:28` — `--workers 1 --threads 8` limita concurrencia | **CONFIRMADO** |
| C8 | Disposición activos no contabiliza ganancia/pérdida | Defecto | ✅ | `accounting_service.py:28-31` — `_find_account_by_usage(accounts, None)` retorna None; `fixed_asset_service.py:199-201` nunca genera líneas de ganancia/pérdida | **CONFIRMADO** |

#### P0 — Falsos positivos

| # | Hallazgo original | Corrección | Evidencia |
|---|------------------|-----------|-----------|
| FP1 | "No existe pago retroactivo" | **Falso positivo.** Existe `calculate_retroactive_pay()` en `payroll_service.py:808` y endpoint en `reports.py:467` | Reclasificado a P1 como "funcionalidad parcial — migrar a ConceptEngine" |
| FP2 | "No existe reingreso de empleado" | **Falso positivo.** Existe `offboarding_rehire()` en `offboarding.py:733` con preservación de antigüedad | Reclasificado a P1 como "funcionalidad parcial — endpoint standalone" |

#### P1 — Confirmados

| # | Hallazgo | Tipo | Validación | Veredicto |
|---|----------|------|-----------|-----------|
| H1 | Sin split payment (múltiples métodos por pago) | Func. faltante | ✅ `invoices.py:2758` — solo un `paymentMethod` | **CONFIRMADO** |
| H2 | Anulación no revierte pagos ni banco | Defecto | ✅ `invoices.py:4909` — solo revierte asiento contable | **CONFIRMADO** |
| H3 | Sin límite de crédito por cliente | Func. faltante | ✅ `clients.py` — sin campo creditLimit | **CONFIRMADO** |
| H4 | Retroactivo usa motor legacy | Func. parcial | ✅ `payroll_service.py:860` — llama `calculate_payroll_line()` legacy | **CONFIRMADO** |
| H5 | Reingreso solo desde offboarding | Func. parcial | ✅ `offboarding.py:733` — no hay endpoint standalone | **CONFIRMADO** |
| H6 | SoD ausente en workflow nómina | Defecto | ✅ `payroll_workflow.py:51-123` — sin validación creador ≠ aprobador | **CONFIRMADO** |
| H7 | Sin planillas TSS-3-01/02 | Func. faltante | ✅ `dgt.py:27-294` — solo DGT-2/3/4/5/9 | **CONFIRMADO** |
| H8 | Sin Estado de Flujo de Efectivo | Func. faltante | ✅ `accounting_service.py:312-400` — BS y ER existen, EFE ausente | **CONFIRMADO** |
| H9 | Sin revaluación cambiaria automática | Func. faltante | ✅ `multi_currency_service.py:67` — `compute_unrealized_gain_loss` no genera asiento | **CONFIRMADO** |
| H10 | Vacation days no descuenta días tomados | Defecto | ✅ `payroll_service.py:592-635` — solo acumulado bruto | **CONFIRMADO** |
| H11 | Sin provisiones contables de nómina | Func. faltante | ✅ `payroll_service.py:1036` — solo asiento de pago, no devengo | **CONFIRMADO** |
| H12 | Webhooks sin retry ni idempotencia | Defecto | ✅ `webhook_service.py:71` — errores silenciados | **CONFIRMADO** |
| H13 | Lecturas sin paginación (10+ funciones) | Defecto | ✅ `db_service.py:385` — `coll_ref.get()` sin límite | **CONFIRMADO** |

#### Resumen de validación

| Categoría | Cantidad |
|-----------|----------|
| Defectos confirmados | 14 |
| Funcionalidad faltante | 9 |
| Funcionalidad parcial (existe pero incompleta) | 3 |
| Falsos positivos | 2 |
| Roadmap (pospuesto) | 2 |

---

## 5. Fase 0 — Congelamiento Funcional

**Duración:** 2 días
**Objetivo:** Detener desarrollo de features, preparar infraestructura de estabilización.

### Entregables

| # | Entregable | Responsable |
|---|-----------|-------------|
| E0.1 | Branch `release/vykone-production-readiness` creado desde `main` | Tech Lead |
| E0.2 | Lista oficial de hallazgos publicada (este documento) | QA Lead |
| E0.3 | CI/CD configurado para ejecutar test suite completa en cada PR a `release/*` | DevOps |
| E0.4 | Ambiente de staging aislado con datos de prueba representativos (500 empleados, 10K facturas) | DevOps |
| E0.5 | Dashboard de tracking con % completado por epic | Tech Lead |
| E0.6 | Comunicación al equipo: no se aceptan PRs de features nuevas hasta nuevo aviso | PM |

### Reglas de la Fase 0

1. **Commits a `main` solo hotfixes de seguridad.** Todo desarrollo P0/P1 va a `release/vykone-production-readiness`.
2. **Code review obligatorio** en cada PR con al menos 2 approvals para cambios en nómina/contabilidad.
3. **Tests obligatorios** — cada fix de defecto debe incluir test que reproduzca el bug y verifique la corrección.
4. **No merge sin CI verde.**

---

## 6. Fase 1 — Corrección de Bloqueantes (P0)

**Duración:** 4 semanas (semanas 1-4)
**Objetivo:** Eliminar el 100% de los defectos P0. Al finalizar esta fase, el sistema debe ser funcionalmente correcto aunque incompleto.

---

### PRD-001 — Segregación de Funciones (SoD)

**Prioridad:** P0 | **Estimación:** 5 días | **Riesgo:** Alto (tocar el sistema de permisos)

#### Objetivo
Impedir que un mismo usuario ejecute acciones incompatibles (crear factura + anularla, crear proveedor + aprobar pago, procesar nómina + aprobarla).

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T1.1 | Activar `SOD_CONFLICT_MATRIX` en `check_permission()` — si el usuario tiene un permiso en conflicto ya ejercido, denegar | `app/utils/decorators.py:32-48` | 1d |
| T1.2 | Persistir historial de acciones SoD por usuario — `users/{uid}/sod_actions/{id}` con timestamp, acción, entidad | `app/services/db_service.py` | 1d |
| T1.3 | Implementar `check_sod_conflict(user_uid, permission)` que consulta historial SoD y matriz | `app/utils/decorators.py` | 1d |
| T1.4 | Aplicar SoD al rol owner — el owner puede delegar excepciones explícitamente | `app/utils/decorators.py:45-46` | 1d |
| T1.5 | Registrar excepción SoD autorizada con auditoría | `app/services/audit_service.py` | 0.5d |
| T1.6 | Agregar SoD al workflow de nómina — `_transition()` debe validar que `user_email != period.get("calculatedBy")` al aprobar, `user_email != period.get("approvedBy")` al contabilizar | `app/web/rrhh/payroll_workflow.py:51-123` | 0.5d |

#### Criterios de aceptación

| ID | Criterio | Cómo verificar |
|----|----------|---------------|
| CA1.1 | Usuario con `canInvoice` NO puede anular factura que él mismo creó | Test automatizado |
| CA1.2 | Usuario con `canCreateSupplier` NO puede aprobar pago a proveedor que él creó | Test automatizado |
| CA1.3 | Usuario con `canHR` NO puede aprobar nómina que él mismo procesó | Test automatizado |
| CA1.4 | Owner PUEDE delegar excepción SoD (ej: empresa unipersonal) | Test manual |
| CA1.5 | Toda violación SoD queda registrada en auditoría | Verificar en `/audit` |
| CA1.6 | El mismo usuario NO puede transicionar nómina de "calculada" → "aprobada" → "contabilizada" | Test automatizado |

---

### PRD-002 — Corrección TSS

**Prioridad:** P0 | **Estimación:** 4 días | **Riesgo:** Alto (implicaciones legales, cálculo masivo)

#### Objetivo
Garantizar que TSS (AFP, SFS, SRL, INFOTEP) se calcule sobre el ingreso bruto real del período, no solo sobre el salario base.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T2.1 | Modificar `TSSResolver.resolve_concept()` para usar `context.gross_income` como base cuando corresponda | `app/services/concept_engine.py:67-74` | 0.5d |
| T2.2 | Agregar atributos por concepto: `affectsTSS`, `affectsISR`, `affectsSeverance` en el modelo `PayrollConcept` | `app/models/employee.py` | 0.5d |
| T2.3 | Construir `gross_income` como suma de transacciones con `affectsTSS=True` (no todas las earning afectan TSS) | `app/web/rrhh/payroll_process.py:460` | 1d |
| T2.4 | Validar que ISR usa `gross_income - AFP - SFS` correctamente en `ISRResolver` | `app/services/concept_engine.py:144-169` | 0.5d |
| T2.5 | Test: empleado con salario base RD$30,000 + comisión RD$5,000 → TSS cotiza sobre RD$35,000, no RD$30,000 | `tests/test_payroll_service.py` | 1d |
| T2.6 | Test: empleado con horas extra → AFP y SFS cotizan sobre base + horas extra | `tests/test_payroll_service.py` | 0.5d |

#### Criterios de aceptación

| ID | Criterio | Cómo verificar |
|----|----------|---------------|
| CA2.1 | AFP empleado = 2.87% sobre `gross_income` (capped a RD$464,460/mes) | Test unitario |
| CA2.2 | SFS empleado = 3.04% sobre `gross_income` (capped a RD$232,230/mes) | Test unitario |
| CA2.3 | Empleado quincenal: topes divididos entre 2 | Test unitario |
| CA2.4 | Comisiones marcadas `affectsTSS=True` se incluyen en base cotizable | Test unitario |
| CA2.5 | Bono extraordinario marcado `affectsTSS=False` NO se incluye en base cotizable | Test unitario |

---

### PRD-003 — Integración de Embargos y Pensiones

**Prioridad:** P0 | **Estimación:** 3 días | **Riesgo:** Medio (servicio ya implementado, solo integrar)

#### Objetivo
Integrar `GarnishmentService` en el flujo de cálculo de nómina para que embargos judiciales, pensiones alimenticias y deducciones de cooperativa se apliquen antes del neto a pagar, respetando prioridad legal y topes.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T3.1 | Cargar garnishments activos del empleado antes de calcular neto | `app/web/rrhh/payroll_process.py` (insertar después de línea 500) | 0.5d |
| T3.2 | Llamar `GarnishmentService.process_all_garnishments(net_before_garnishments, garnishments)` | `app/web/rrhh/payroll_process.py` | 0.5d |
| T3.3 | Integrar resultado de garnishments en el `DeductionPriorityEngine` con prioridad máxima (0-99) | `app/services/deduction_priority_engine.py` | 0.5d |
| T3.4 | Generar transacciones de tipo `garnishment` para cada embargo procesado | `app/web/rrhh/payroll_process.py` | 0.5d |
| T3.5 | Actualizar `remainingBalance` en el embargo original después del descuento | `app/services/garnishment_service.py` | 0.5d |
| T3.6 | Test: empleado con embargo judicial + pensión alimenticia → pensión se descuenta primero | `tests/test_payroll_service.py` | 0.5d |

#### Criterios de aceptación

| ID | Criterio | Cómo verificar |
|----|----------|---------------|
| CA3.1 | Pensión alimenticia se descuenta antes que embargo judicial | Test (prioridad 0 < prioridad 1) |
| CA3.2 | Deducción total de embargos no excede el máximo legal por tipo | Test con net_salary y garnishable max |
| CA3.3 | Embargo saldado (remainingBalance=0) no genera descuento en siguiente período | Test con remainingBalance=0 |
| CA3.4 | Embargo pausado (status=paused) no genera descuento | Test |

---

### PRD-004 — Contabilización de Conciliación Bancaria

**Prioridad:** P0 | **Estimación:** 3 días | **Riesgo:** Medio

#### Objetivo
Generar asientos contables automáticos al completar una conciliación bancaria: comisiones, intereses, diferencias y ajustes.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T4.1 | Al completar conciliación con diferencia ≠ 0, generar asiento de ajuste: débito/crédito a "Diferencias de conciliación" | `app/web/banks.py:611-633` | 1d |
| T4.2 | Permitir registrar comisiones bancarias e intereses devengados como transacciones manuales en la conciliación | `app/web/banks.py` (nueva sección) | 1d |
| T4.3 | Generar asientos separados para comisiones (gasto) e intereses (ingreso) al completar conciliación | `app/services/accounting_service.py` (nuevo método) | 0.5d |
| T4.4 | Vincular asientos de conciliación al registro de conciliación (`referenceType: "bank_reconciliation"`) | `app/web/banks.py` | 0.5d |

#### Criterios de aceptación

| ID | Criterio | Cómo verificar |
|----|----------|---------------|
| CA4.1 | Conciliación con diferencia de RD$500 genera asiento de ajuste por RD$500 | Test automatizado |
| CA4.2 | Conciliación con comisión de RD$150 genera asiento: débito gasto bancario, crédito banco | Test automatizado |
| CA4.3 | Conciliación con interés de RD$75 genera asiento: débito banco, crédito ingreso financiero | Test automatizado |
| CA4.4 | Conciliación sin diferencia no genera asiento de ajuste | Test automatizado |

---

### PRD-005 — Escáner de Integridad Referencial

**Prioridad:** P0 | **Estimación:** 5 días | **Riesgo:** Medio

#### Objetivo
Implementar detector de datos huérfanos para Firestore (facturas sin cliente, pagos sin factura, asientos sin documento origen, empleados sin compañía).

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T5.1 | Crear `IntegrityScanner` service con método `scan_all(owner_uid)` | `app/services/integrity_scanner.py` (nuevo) | 2d |
| T5.2 | Implementar reglas: `invoice_has_client`, `payment_has_invoice`, `entry_has_reference`, `employee_has_company`, `item_has_warehouse` | `app/services/integrity_scanner.py` | 1.5d |
| T5.3 | Modo dry-run: reportar sin modificar (Fase 1, semana 3-4) | `app/services/integrity_scanner.py` | 0.5d |
| T5.4 | Dashboard de integridad con conteo de huérfanos por tipo y severidad | `app/web/integrity.py` (nuevo) + template | 1d |

#### Criterios de aceptación

| ID | Criterio | Cómo verificar |
|----|----------|---------------|
| CA5.1 | Scanner detecta factura con `clientId` que no existe en `clients` | Test con datos sintéticos |
| CA5.2 | Scanner detecta pago con `invoiceId` que no existe en `invoices` | Test con datos sintéticos |
| CA5.3 | Modo dry-run nunca modifica datos | Test automatizado |
| CA5.4 | Dashboard muestra: tipo de huérfano, severidad (alta/media/baja), fecha de detección | Verificación manual |

---

### PRD-006 — Corrección Regalía Pascual

**Prioridad:** P0 | **Estimación:** 1 día | **Riesgo:** Bajo

#### Objetivo
Corregir cálculo de meses trabajados para regalía pascual. La fórmula actual solo considera meses dentro del año en curso.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T6.1 | Reemplazar fórmula `max(1, month(today)-month(hireDate)+1)` por cálculo correcto que considere años completos: si el empleado tiene ≥1 año → 12 meses | `app/web/rrhh/payroll_process.py:348` | 0.5d |
| T6.2 | Agregar test con matriz de casos | `tests/test_payroll_service.py` | 0.5d |

#### Matriz de pruebas

| Ingreso | Fecha cálculo | Meses esperados | Resultado bug actual | Resultado esperado |
|---------|--------------|-----------------|---------------------|-------------------|
| 2025-01-15 | 2025-12-15 | 12 | 12 ✓ | 12 |
| 2025-07-01 | 2025-12-15 | 6 | 6 ✓ | 6 |
| 2024-10-01 | 2026-07-15 | 12 | 1 ✗ | 12 |
| 2025-12-01 | 2025-12-15 | 1 | 1 ✓ | 1 |
| 2026-03-15 | 2026-07-15 | 5 | 5 ✓ | 5 |

---

### PRD-007 — Corrección Disposición de Activos Fijos

**Prioridad:** P0 | **Estimación:** 1 día | **Riesgo:** Bajo

#### Objetivo
Corregir bug donde `_find_account_by_usage(accounts, None)` siempre retorna `None`, causando que la ganancia/pérdida por disposición de activos nunca se contabilice.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T7.1 | Buscar cuenta de ganancia por código `"4.2.3"` (Ganancia por diferencia en cambio) o `"4.2"` (Ingresos financieros) | `app/services/fixed_asset_service.py:198-201` | 0.25d |
| T7.2 | Buscar cuenta de pérdida por código `"6.4.02"` (Pérdida por diferencia en cambio) o `"6.4"` (Gastos financieros) | `app/services/fixed_asset_service.py:198-201` | 0.25d |
| T7.3 | Agregar líneas contables de ganancia/pérdida al asiento de disposición | `app/services/fixed_asset_service.py:202` | 0.25d |
| T7.4 | Test: disposición con ganancia genera línea de crédito en cuenta de ingreso | `tests/test_accounting_by_ecf_type.py` | 0.25d |

---

### PRD-008 — Escalabilidad Infraestructura

**Prioridad:** P0 | **Estimación:** 3 días | **Riesgo:** Medio

#### Objetivo
Preparar infraestructura para manejar carga de producción: múltiples workers, Redis para sesiones y caché, rate limiting distribuido.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T8.1 | Cambiar `Dockerfile` a `--workers 4` (ajustable por variable de entorno) | `Dockerfile:28` | 0.25d |
| T8.2 | Configurar Redis como backend de sesiones Flask (`SESSION_TYPE = 'redis'`) | `config.py`, `app/__init__.py` | 0.5d |
| T8.3 | Configurar Redis como backend de Flask-Caching | `config.py`, `app/extensions.py` | 0.5d |
| T8.4 | Migrar Flask-Limiter a storage Redis (actualmente `memory://`) | `config.py:96` | 0.25d |
| T8.5 | Agregar health check endpoint (`/health`) para Cloud Run | `app/__init__.py` | 0.5d |
| T8.6 | Prueba de carga: 50 usuarios concurrentes → verificar <2s response time | JMeter / Locust | 1d |

---

## 7. Fase 2 — Operación Empresarial (P1)

**Duración:** 4 semanas (semanas 5-8)
**Objetivo:** Completar funcionalidades empresariales requeridas para operación real. Al finalizar, el sistema debe ser operativamente completo.

---

### PRD-101 — Split Payment (Múltiples Métodos de Pago)

**Prioridad:** P1 | **Estimación:** 4 días

#### Objetivo
Permitir que una factura se pague con múltiples métodos en una sola operación (ej: RD$4,000 tarjeta + RD$3,000 transferencia + RD$3,000 efectivo).

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T101.1 | Modificar `pay_invoice_route` para aceptar array `payments[]` en lugar de un solo método | `app/web/invoices.py:2732-2864` | 1.5d |
| T101.2 | Adaptar `register_invoice_payment` para procesar múltiples payment_dicts con distribución secuencial del saldo | `app/services/db_service.py:2844-3016` | 1.5d |
| T101.3 | UI: formulario dinámico de métodos de pago con botón "Agregar método" | `templates/invoices/` | 0.5d |
| T101.4 | Test: factura RD$10,000 con 3 métodos (40%+30%+30%) = pagada | `tests/` | 0.5d |

---

### PRD-102 — Reversión Completa al Anular Factura

**Prioridad:** P1 | **Estimación:** 2 días

#### Objetivo
Al anular factura, revertir pagos registrados, saldos bancarios y CxC, no solo el asiento contable.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T102.1 | En `void_invoice_route`, iterar pagos de la factura y revertir cada uno (invertir saldo bancario) | `app/web/invoices.py:4909-4925` | 1d |
| T102.2 | Verificar que el asiento de reversión ya cubre la reversión contable (confirmado en línea 4909) | `app/services/accounting_service.py:989` | 0.25d |
| T102.3 | Test: factura pagada → anulada → saldo banco restaurado, CxC en cero | `tests/` | 0.75d |

---

### PRD-103 — Límite de Crédito por Cliente

**Prioridad:** P1 | **Estimación:** 2 días

#### Objetivo
Agregar límite de crédito configurable por cliente y bloquear facturas a crédito que excedan el disponible.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T103.1 | Agregar campos `creditLimit`, `creditUsed`, `availableCredit` al modelo y formulario de cliente | `app/web/clients.py`, `app/models/` | 0.5d |
| T103.2 | Al emitir factura a crédito, validar `creditUsed + newInvoiceTotal ≤ creditLimit` | `app/web/invoices.py` | 0.5d |
| T103.3 | Al registrar pago de factura a crédito, actualizar `creditUsed` del cliente | `app/services/db_service.py:2844` | 0.5d |
| T103.4 | Configuración: permitir "bloquear" o "advertir" al exceder límite | `app/web/clients.py` | 0.5d |

---

### PRD-104 — Migrar Retroactivo a ConceptEngine

**Prioridad:** P1 | **Estimación:** 3 días

#### Objetivo
Migrar el cálculo de pago retroactivo (actualmente en `calculate_payroll_line` legacy) al nuevo `ConceptEngine` para consistencia con el resto de la nómina.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T104.1 | Refactorizar `calculate_retroactive_pay` para usar `ConceptEngine.evaluate()` en lugar de `calculate_payroll_line` | `app/services/payroll_service.py:808-870` | 1.5d |
| T104.2 | Generar transacciones individuales por mes retroactivo con `periodSubType: "retroactive"` | `app/services/payroll_service.py` | 1d |
| T104.3 | Test: aumento RD$5,000 con 3 meses retroactivos → 3 transacciones de diferencia | `tests/test_payroll_service.py` | 0.5d |

---

### PRD-105 — Reingreso Standalone

**Prioridad:** P1 | **Estimación:** 2 días

#### Objetivo
Permitir reingreso de empleado sin requerir un proceso de offboarding previo (caso: empleado que renunció hace 6 meses y es recontratado).

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T105.1 | Crear endpoint `/rrhh/employees/<id>/rehire` independiente del offboarding | `app/web/rrhh/employees.py` | 1d |
| T105.2 | Opción de preservar o resetear antigüedad, vacaciones acumuladas, YTD | `app/web/rrhh/employees.py` | 0.5d |
| T105.3 | Limpiar campos de terminación (`terminationDate`, `terminationReason`) y cambiar status a "activo" | `app/services/hr_data_service.py` | 0.5d |

---

### PRD-106 — Planillas TSS-3-01 y TSS-3-02

**Prioridad:** P1 | **Estimación:** 4 días

#### Objetivo
Generar archivos de pago a la Tesorería de Seguridad Social (TSS) en formato requerido.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T106.1 | Implementar layout TSS-3-01 (Planilla de Pago de Seguridad Social) según especificación TSS | `app/services/dgt_service.py` | 2d |
| T106.2 | Implementar layout TSS-3-02 (Relación de Empleados) según especificación TSS | `app/services/dgt_service.py` | 1d |
| T106.3 | Exportación a TXT con formato de columna fija requerido por TSS | `app/services/dgt_export_service.py` | 0.5d |
| T106.4 | Validación previa: totales cuadran con resumen de nómina | `app/web/rrhh/dgt.py` | 0.5d |

---

### PRD-107 — Estado de Flujo de Efectivo

**Prioridad:** P1 | **Estimación:** 3 días

#### Objetivo
Implementar Estado de Flujo de Efectivo (método indirecto) en el módulo de contabilidad.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T107.1 | Implementar `get_cash_flow(owner_uid, year)` en AccountingService — método indirecto | `app/services/accounting_service.py` | 2d |
| T107.2 | Template de visualización con secciones: operación, inversión, financiamiento | `templates/accounting/cash_flow.html` | 0.5d |
| T107.3 | Ruta web `/accounting/cash-flow` | `app/web/accounting.py` | 0.5d |

---

### PRD-108 — Revaluación Cambiaria Automática

**Prioridad:** P1 | **Estimación:** 2 días

#### Objetivo
Generar asientos de ganancia/pérdida por diferencia en cambio al cierre de período.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T108.1 | Modificar `compute_unrealized_gain_loss` para generar asiento contable al cierre mensual | `app/services/multi_currency_service.py:67-87` | 1d |
| T108.2 | Programar revaluación automática en cierre de período fiscal | `app/services/fiscal_period_service.py` | 0.5d |
| T108.3 | Permitir ejecución manual desde UI de cierre | `app/web/accounting.py` | 0.5d |

---

### PRD-109 — Corrección Vacation Days

**Prioridad:** P1 | **Estimación:** 1 día

#### Objetivo
`calculate_vacation_days()` debe devolver días disponibles (acumulados - tomados), no acumulado bruto.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T109.1 | Restar días de vacaciones aprobadas (`vacation_requests` status="aprobada") del acumulado bruto | `app/services/payroll_service.py:592-635` | 0.5d |
| T109.2 | Test: empleado con 28 días acumulados y 7 tomados → disponible = 21 | `tests/test_payroll_service.py` | 0.5d |

---

### PRD-110 — Provisiones Contables de Nómina

**Prioridad:** P1 | **Estimación:** 3 días

#### Objetivo
Generar asientos de provisión mensual para vacaciones y regalía pascual (devengo), no solo asiento de pago.

#### Tareas

| ID | Tarea | Archivo | Estimación |
|----|-------|---------|------------|
| T110.1 | Implementar `build_vacation_provision_lines(period, employees, tax_rates)` | `app/services/payroll_service.py` | 1d |
| T110.2 | Implementar `build_christmas_bonus_provision_lines(period, employees, tax_rates)` | `app/services/payroll_service.py` | 1d |
| T110.3 | Integrar en cierre mensual automático (opcional: job programado) | `app/services/fiscal_period_service.py` | 0.5d |
| T110.4 | Reversión automática de provisión al mes siguiente | `app/services/accounting_service.py` | 0.5d |

---

## 8. Fase 3 — Endurecimiento Empresarial (P2)

**Duración:** Incluida en semanas 5-8 (paralelo con P1 donde no haya dependencias)
**Objetivo:** Robustecer seguridad, trazabilidad y completitud de API.

---

### PRD-201 — Auditoría Avanzada

**Prioridad:** P2 | **Estimación:** 3 días

#### Objetivo
Unificar sistema de auditoría de nómina con el sistema central. Agregar IP y device info a todos los registros.

#### Tareas

| ID | Tarea | Archivo |
|----|-------|---------|
| T201.1 | Migrar `payroll_audit_service` para usar `AuditService` central en lugar de colección separada | `app/web/rrhh/payroll_workflow.py:119-121` |
| T201.2 | Agregar `ipAddress`, `userAgent` a todos los registros de auditoría de nómina | `app/services/payroll_audit_service.py` |
| T201.3 | Agregar auditoría a creación/anulación de asientos contables | `app/web/accounting.py` |

---

### PRD-202 — Webhooks con Retry y DLQ

**Prioridad:** P2 | **Estimación:** 3 días

#### Objetivo
Agregar reintentos con backoff exponencial, dead letter queue y registro de entregas a webhooks.

#### Tareas

| ID | Tarea | Archivo |
|----|-------|---------|
| T202.1 | Implementar retry con backoff exponencial (1s, 2s, 4s, 8s, 16s — máximo 5 intentos) | `app/services/webhook_service.py:71` |
| T202.2 | Dead Letter Queue: webhooks que fallan 5 veces van a colección `webhooks_dlq` | `app/services/webhook_service.py` |
| T202.3 | Agregar `Idempotency-Key` a cada dispatch de webhook | `app/services/webhook_service.py` |
| T202.4 | Dashboard de webhooks con estado de entrega y reintentos | `app/web/` |

---

### PRD-203 — Paginación Obligatoria

**Prioridad:** P2 | **Estimación:** 3 días

#### Objetivo
Reemplazar lecturas de colección completa (`coll_ref.get()` sin límite) con cursores paginados.

#### Tareas

| ID | Tarea | Archivo |
|----|-------|---------|
| T203.1 | Implementar `paginated_get(collection, page_size=100, cursor=None)` en `DatabaseService` | `app/services/db_service.py` |
| T203.2 | Migrar `_cached_invoices`, `_cached_clients`, `_cached_expenses`, `_cached_items` a paginación | `app/services/db_service.py:377-450` |
| T203.3 | Migrar `_cached_sequences`, `_cached_crm_contacts`, `_cached_suppliers` y demás funciones cacheadas | `app/services/db_service.py` |
| T203.4 | Validar que la paginación no rompe la caché (invalidación por lote, no por colección completa) | `app/services/db_service.py` |

---

### PRD-204 — Cumplimiento de Datos Personales

**Prioridad:** P2 | **Estimación:** 4 días

#### Objetivo
Implementar medidas básicas de privacidad de datos: exportación DSAR, derecho al olvido, banner de cookies.

#### Tareas

| ID | Tarea | Archivo |
|----|-------|---------|
| T204.1 | Endpoint de exportación de datos del titular (empleado o contacto) en formato JSON/CSV | `app/web/` (nuevo) |
| T204.2 | Endpoint de anonimización: reemplaza PII con hash en lugar de eliminar (preserva integridad referencial) | `app/services/` (nuevo) |
| T204.3 | Banner de consentimiento de cookies con opción aceptar/rechazar | `templates/layout.html` |
| T204.4 | Política de retención de datos: auditoría se archiva a los 5 años, logs a 1 año | `app/services/scheduler.py` |

---

### PRD-205 — API REST Endpoints Faltantes

**Prioridad:** P2 | **Estimación:** 3 días

#### Objetivo
Completar endpoints de API REST para pagos, estado de cuenta y notas de crédito.

#### Tareas

| ID | Tarea | Archivo |
|----|-------|---------|
| T205.1 | `POST /api/v1/invoices/{id}/payments` — registrar pago | `app/api/v1/invoices.py` |
| T205.2 | `GET /api/v1/clients/{id}/statement` — estado de cuenta con aging | `app/api/v1/clients.py` |
| T205.3 | `POST /api/v1/invoices/{id}/credit-notes` — emitir nota de crédito | `app/api/v1/invoices.py` |
| T205.4 | Documentar nuevos endpoints en `docs/api_documentation.md` | `docs/` |

---

## 9. Fase 4 — Certificación Go-Live

**Duración:** 2 semanas (semanas 9-10)
**Objetivo:** Validar que el sistema está listo para producción mediante pruebas integrales, carga y aceptación.

---

### 9.1 QA Funcional Integral

#### Facturación

| # | Escenario | Datos | Criterio |
|---|-----------|-------|----------|
| F1 | Emitir 500 facturas E31 en lote | 500 facturas con 1-10 items cada una | 0 fallos de emisión DGII |
| F2 | Anular 50 facturas emitidas | 50 facturas en estado "Emitida" | Todas reportadas a DGII, asientos revertidos, pagos revertidos |
| F3 | Emitir 50 notas de crédito E34 | Referenciando 50 facturas distintas | Validación de monto máximo, tracking de saldo acreditado |
| F4 | Split payment: 30 facturas con 2-4 métodos | 30 facturas de diversos montos | Total aplicado = suma de métodos, factura en estado correcto |
| F5 | Límite de crédito: bloquear factura | Cliente con crédito RD$50,000, CxC RD$48,000, nueva factura RD$5,000 | Bloqueada por exceder límite |

#### Nómina

| # | Escenario | Datos | Criterio |
|---|-----------|-------|----------|
| N1 | Procesar nómina quincenal | 500 empleados, 3 departamentos | TSS calculado sobre grossIncome, neto correcto |
| N2 | Nómina con empleados variables | 50 empleados con comisiones + horas extra | AFP/SFS/ISR correctos |
| N3 | Nómina con embargos | 5 empleados con embargo judicial + pensión | Prioridad respetada, topes legales |
| N4 | Liquidación compleja | 3 escenarios: renuncia, despido, dimisión justificada | Preaviso, cesantía, vacaciones, regalía correctos |
| N5 | Reingreso de empleado | 1 empleado recontratado tras 6 meses | Antigüedad preservada/reseteada según elección |
| N6 | Regalía pascual | 500 empleados en diciembre | 12 meses para empleados con >1 año |

#### Contabilidad

| # | Escenario | Datos | Criterio |
|---|-----------|-------|----------|
| C1 | Cierre fiscal anual | Ejercicio completo simulado con 5,000 asientos | Asientos de cierre generados, BS/ER/EFE correctos |
| C2 | Conciliación bancaria con diferencia | 3 cuentas con diferencias | Asientos de ajuste generados |
| C3 | Revaluación cambiaria | 2 cuentas en USD, tasa varía 5% | Asientos de ganancia/pérdida generados |
| C4 | Disposición de activo fijo | Venta de vehículo con ganancia | Asiento incluye línea de ganancia |
| C5 | Nómina → Contabilidad | 1 período cerrado | Provisiones de vacaciones y regalía generadas |

---

### 9.2 Pruebas de Carga

| Métrica | Meta | Herramienta | Criterio |
|---------|------|------------|----------|
| Usuarios concurrentes | 100 | Locust | 0 errores, p95 < 2s |
| Facturas emitidas/día | 10,000 | Script batch | 0 fallos DGII |
| Empleados procesados en nómina | 5,000 | Nómina quincenal completa | < 5 minutos |
| Asientos contables generados | 50,000 | Carga masiva | < 10 minutos |
| Consulta aging 1,000 clientes | 1,000 | API call paginado | < 3s por página |

---

### 9.3 Pruebas de Seguridad

| # | Prueba | Herramienta | Criterio |
|---|--------|------------|----------|
| S1 | SoD: verificar 10 combinaciones prohibidas | Script automatizado | 100% bloqueadas |
| S2 | CSRF en formularios críticos | OWASP ZAP | 0 vulnerabilidades |
| S3 | Session fixation | Manual | Token rotado en login |
| S4 | Multi-tenant isolation | Script (Company A intenta leer datos de Company B) | Bloqueado |

---

### 9.4 Pruebas de Integridad

| # | Prueba | Criterio |
|---|--------|----------|
| I1 | Integrity Scanner en dataset de 10,000 documentos | 0 huérfanos (o huérfanos conocidos y documentados) |
| I2 | Secuencias NCF sin huecos ni duplicados | 5,000 emisiones concurrentes → 0 gaps |
| I3 | Paginación: lista 100,000 facturas sin timeout | < 5s por página |

---

## 10. Cronograma

```
Semana 1          Semana 2          Semana 3          Semana 4
[PRD-001 SoD      ] [PRD-001 cont  ] [PRD-005 Integ ] [PRD-005 cont  ]
[PRD-002 TSS      ] [PRD-003 Embarg] [PRD-003 cont  ] [PRD-008 Escal ]
[PRD-006 Regalía  ] [PRD-004 Concil] [PRD-004 cont  ] [PRD-008 cont  ]
[PRD-007 Activos  ] [PRD-007 cont  ] [PRD-007 integ ] [               ]

Semana 5          Semana 6          Semana 7          Semana 8
[PRD-101 Split   ] [PRD-104 Retroa] [PRD-107 Flujo  ] [PRD-110 Provis]
[PRD-102 Revers  ] [PRD-105 Reingr] [PRD-108 Revalu ] [PRD-203 Pagin ]
[PRD-103 Crédito ] [PRD-106 TSS    ] [PRD-109 Vacac  ] [PRD-204 GDPR  ]
[PRD-201 Auditor ] [PRD-202 Webhk ] [PRD-205 API    ] [               ]

Semana 9                       Semana 10
[QA Funcional Integral   ]    [Pruebas de Carga         ]
[Correcciones de bugs QA ]    [Pruebas de Seguridad      ]
[                          ]   [Pruebas de Integridad     ]
[                          ]   [Decisión Go/No-Go         ]
```

---

## 11. Matriz RACI

| Epic | Responsible | Accountable | Consulted | Informed |
|------|-------------|-------------|-----------|----------|
| PRD-001 SoD | Backend Lead | Tech Lead | Security Specialist | PM |
| PRD-002 TSS | Payroll Dev | Tech Lead | Contador | PM |
| PRD-003 Embargos | Payroll Dev | Tech Lead | Contador | PM |
| PRD-004 Conciliación | Backend Lead | Tech Lead | Contador | PM |
| PRD-005 Integridad | Backend Lead | Tech Lead | QA Lead | PM |
| PRD-006 Regalía | Payroll Dev | Tech Lead | Contador | PM |
| PRD-007 Activos | Backend Lead | Tech Lead | Contador | PM |
| PRD-008 Escalabilidad | DevOps | Tech Lead | Backend Lead | PM |
| PRD-101 Split Payment | Backend Lead | Tech Lead | UX Designer | PM |
| PRD-102 Reversión | Backend Lead | Tech Lead | QA Lead | PM |
| PRD-103 Crédito | Backend Lead | Tech Lead | Contador | PM |
| PRD-104 Retroactivo | Payroll Dev | Tech Lead | Contador | PM |
| PRD-105 Reingreso | Payroll Dev | Tech Lead | HR Specialist | PM |
| PRD-106 TSS Planillas | Payroll Dev | Tech Lead | Contador | PM |
| PRD-107 Flujo Efectivo | Backend Lead | Tech Lead | Contador | PM |
| PRD-108 Revaluación | Backend Lead | Tech Lead | Contador | PM |
| PRD-109 Vacaciones | Payroll Dev | Tech Lead | Contador | PM |
| PRD-110 Provisiones | Backend Lead | Tech Lead | Contador | PM |
| PRD-201 Auditoría | Backend Lead | Tech Lead | Security Specialist | PM |
| PRD-202 Webhooks | Backend Lead | Tech Lead | DevOps | PM |
| PRD-203 Paginación | Backend Lead | Tech Lead | DevOps | PM |
| PRD-204 GDPR | Backend Lead | Tech Lead | Legal | PM |
| PRD-205 API | Backend Lead | Tech Lead | QA Lead | PM |
| Fase 4 Certificación | QA Lead | PM | Todo el equipo | Stakeholders |

---

## 12. Criterios Go / No-Go

### Go-Live Checklist

| # | Criterio | Umbral | Estado esperado |
|---|----------|--------|-----------------|
| G1 | 100% de PRDs P0 cerrados | 8/8 | ✅ |
| G2 | ≥80% de PRDs P1 cerrados | ≥10/13 | ✅ |
| G3 | 0 defectos críticos/altos abiertos en staging | 0 | ✅ |
| G4 | Pruebas de carga: 100 usuarios concurrentes <2s p95 | p95 < 2000ms | ✅ |
| G5 | Pruebas de carga: 10,000 facturas/día sin fallos DGII | 0 fallos | ✅ |
| G6 | Pruebas de carga: nómina 5,000 empleados <5 min | <300s | ✅ |
| G7 | SoD: 100% combinaciones prohibidas bloqueadas | 100% | ✅ |
| G8 | Multi-tenant: 0 fugas de datos entre compañías | 0 incidentes | ✅ |
| G9 | Score de auditoría: todas las áreas ≥7.0/10 | ≥7.0 | ✅ |
| G10 | Backup y restore probados en ambiente staging | Restore exitoso | ✅ |

### No-Go Triggers

Cualquiera de los siguientes impide el Go-Live:

1. Más de 2 PRDs P0 pendientes
2. Cualquier defecto que cause corrupción de datos (duplicados, pérdida, inconsistencia)
3. Fuga de datos entre tenants en prueba de seguridad
4. Timeout en nómina >5,000 empleados (>10 minutos)
5. Fallo en emisión DGII >1% de facturas
6. Rollback de staging no exitoso

---

## 13. Plan de Rollback

### Estrategia

Si durante las primeras 48 horas post Go-Live se detecta un defecto crítico:

1. **Rollback inmediato** (< 1 hora):
   - Revertir deploy a última versión estable pre-PCP
   - Congelar escrituras en Firestore (modo lectura)
   - Notificar a todos los clientes activos

2. **Rollback programado** (2-4 horas):
   - Si el defecto es aislado a un módulo, deshabilitar solo ese módulo
   - Mantener el resto del sistema operativo

3. **Hotfix** (< 24 horas):
   - Si el defecto tiene fix conocido y validado, aplicar hotfix directamente en `main`

### Procedimiento de rollback

```bash
# 1. Redirigir tráfico a instancia anterior
gcloud run services update-traffic vykone --to-revisions <stable-revision>=100

# 2. Notificar
# Enviar email a clientes activos con:
# - Naturaleza del incidente
# - Módulos afectados
# - Tiempo estimado de resolución

# 3. Investigar
# Equipo completo en war room
# RCA en <4 horas
```

---

## 14. KPIs de Calidad

| KPI | Medición | Frecuencia | Meta |
|-----|----------|------------|------|
| Cobertura de tests | `pytest --cov` | Cada PR | ≥80% |
| Defectos escapados a staging | Conteo manual | Semanal | 0 críticos |
| Tiempo de respuesta p95 | Locust / Cloud Monitoring | Diario | <2000ms |
| Tasa de error DGII | Logs de emisión | Diario | <0.5% |
| Huérfanos detectados | Integrity Scanner | Diario | 0 nuevos |
| Violaciones SoD | Auditoría | Semanal | 0 |
| PRs merged sin CI verde | GitHub Actions | Continuo | 0 |

---

## 15. Checklist de Certificación Final

### Módulo: Facturación

- [ ] Emisión E31/E32/E33/E34/E41/E43/E45/E46/E47 todos pasan
- [ ] Split payment funcional en UI y API
- [ ] Límite de crédito bloquea factura a crédito cuando excede
- [ ] Anulación revierte pago + banco + CxC + asiento
- [ ] Nota de crédito valida monto máximo contra factura original
- [ ] Secuencias NCF sin huecos ni duplicados bajo concurrencia
- [ ] Cotización → Factura preserva anticipos y ajusta CxC

### Módulo: Nómina

- [ ] TSS calculado sobre grossIncome (base + comisiones + horas extra)
- [ ] Embargos y pensiones descontados en orden de prioridad legal
- [ ] Regalía pascual: 12 meses para empleados con >1 año
- [ ] Retroactivo migrado a ConceptEngine
- [ ] Reingreso funcional con preservación/reset de antigüedad
- [ ] Workflow nómina: creador no puede aprobar ni contabilizar
- [ ] Provisiones contables generadas en cierre mensual
- [ ] TSS-3-01 y TSS-3-02 exportables

### Módulo: Contabilidad

- [ ] Conciliación bancaria genera asientos de diferencia, comisión, interés
- [ ] Estado de Flujo de Efectivo funcional
- [ ] Revaluación cambiaria genera asientos en cierre de período
- [ ] Disposición de activos contabiliza ganancia/pérdida
- [ ] BS, ER, EFE cuadran entre sí

### Cross-Cutting

- [ ] SoD: 10 combinaciones prohibidas bloqueadas
- [ ] Integrity Scanner: 0 huérfanos nuevos
- [ ] Webhooks con retry, DLQ e idempotencia
- [ ] Todas las lecturas de colecciones paginadas
- [ ] Redis para sesiones, caché y rate limiting
- [ ] 100 usuarios concurrentes <2s p95
- [ ] GDPR: exportación DSAR + anonimización funcionales

### Infraestructura

- [ ] Dockerfile con `--workers 4` (ajustable por `WEB_CONCURRENCY`)
- [ ] Health check endpoint `/health` responde 200
- [ ] Cloud Run con mínimo 2 instancias, auto-scale hasta 10
- [ ] Backup diario de Firestore configurado
- [ ] Rollback probado en staging (<10 minutos)

---

## Firmas

| Rol | Nombre | Fecha | Firma |
|-----|--------|-------|-------|
| Tech Lead | | | |
| QA Lead | | | |
| Product Manager | | | |
| CTO | | | |

---

*Documento generado el 2026-07-21. Versión 1.0. Sujeto a actualización según avance del programa.*
