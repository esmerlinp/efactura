# Offboarding Roadmap Técnico v1.0

**Anexo técnico al Blueprint de Offboarding**  
**Audiencia:** Dirección de producto, project managers, desarrolladores  
**Propósito:** Plan de implementación del módulo de Offboarding en 12 sprints

---

## 1. Resumen

| Métrica | Valor |
|---|---|
| Sprints totales | 12 |
| Duración por sprint | 2 semanas |
| Duración total estimada | 24 semanas (~6 meses) |
| Capacidad por sprint | 40 puntos de historia (asumiendo equipo 4-5 devs) |
| Puntos de historia totales estimados | ~480 |
| Dependencias externas | Core HR (empleados), Payroll (nómina), Assets |

---

## 2. Fase 1: Gobierno y Dominio (Sprints 1-3)

**Objetivo:** Establecer la base del módulo con modelo de datos, state machine y eventos.

### Sprint 1: Modelo de Datos Fundamental

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Crear entidad `TerminationRequest` con Firestore collection | Modelo | 5 | Ninguna |
| Crear catálogo `TerminationType` (11 tipos) | Modelo | 2 | Ninguna |
| Crear catálogo `TerminationStatus` (12 estados) | Modelo | 1 | Ninguna |
| Implementar `requestNumber` auto-generado (OFF-YYYY-NNNNN) | Modelo | 3 | Ninguna |
| Crear `TerminationApproval` value object | Modelo | 2 | Ninguna |
| Crear `StatusChange` value object | Modelo | 1 | Ninguna |
| Implementar CRUD básico en `hr_data_service.py` | Data | 5 | Modelo |
| Crear blueprint Flask `app/web/rrhh/offboarding/` | Controller | 3 | CRUD |
| Pruebas unitarias del modelo | QA | 5 | Modelo |

**Total sprint 1: 27 pts**

### Sprint 2: State Machine y Workflow

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Implementar state machine (12 estados, transiciones) | Service | 8 | Sprint 1 |
| Validación de pre/post condiciones por transición | Service | 5 | State machine |
| Implementar `TransitionValidator` con reglas embebidas | Service | 5 | Validación |
| Crear endpoint `GET /transitions` (transiciones disponibles) | API | 3 | State machine |
| Crear endpoint `POST /requests/{id}/transition` | API | 5 | State machine |
| Validar transiciones inválidas con códigos de error | Service | 3 | State machine |
| Pruebas de state machine (todos los caminos) | QA | 8 | State machine |

**Total sprint 2: 37 pts**

### Sprint 3: Eventos de Dominio

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Definir 11 eventos de dominio del offboarding | Modelo | 3 | Sprint 1 |
| Implementar event bus para offboarding | Service | 5 | Sprint 2 |
| Publicar `TerminationRequested` al crear solicitud | Service | 3 | Event bus |
| Publicar `TerminationApproved` al aprobar RRHH | Service | 2 | Event bus |
| Publicar `TerminationCompleted` al cerrar proceso | Service | 2 | Event bus |
| Publicar eventos restantes en transiciones clave | Service | 5 | Event bus |
| Integrar con sistema de notificaciones existente | Service | 5 | Event bus |
| Pruebas de eventos | QA | 5 | Eventos |

**Total sprint 3: 30 pts**

**Fase 1 total: 94 pts** ✅

---

## 3. Fase 2: Workflow y SOD (Sprints 4-5)

**Objetivo:** Implementar flujo de aprobación, matriz de permisos y reglas SOD.

### Sprint 4: Flujo de Aprobación

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Implementar lógica de aprobación de supervisor | Service | 5 | Sprint 2 |
| Implementar lógica de aprobación de RRHH | Service | 5 | Sprint 2 |
| Implementar rechazo con comentario obligatorio | Service | 3 | Sprint 2 |
| Implementar notificaciones por nivel de aprobación | Service | 5 | Sprint 3 |
| Crear UI de bandeja de aprobaciones pendientes | Frontend | 8 | Sprint 2 |
| Crear UI de detalle de aprobación (aprobar/rechazar) | Frontend | 5 | Sprint 2 |
| Pruebas de flujo de aprobación | QA | 5 | Service |

**Total sprint 4: 36 pts**

### Sprint 5: RBAC y SOD

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Implementar roles: supervisor, hr, hr_manager, finance, it, legal | Auth | 5 | Sprint 1 |
| Implementar matriz de permisos por operación | Auth | 8 | Roles |
| Implementar `SODValidator` con 5 reglas obligatorias | Service | 5 | Sprint 2 |
| Implementar límites de aprobación por monto | Service | 3 | SOD |
| Validar SOD en transiciones de estado | Service | 5 | SOD + State machine |
| Crear endpoint `GET /requests/{id}/available-actions` | API | 3 | Permisos |
| Pruebas de SOD (todos los escenarios) | QA | 8 | SOD |

**Total sprint 5: 37 pts**

**Fase 2 total: 73 pts** ✅

---

## 4. Fase 3: Operación y Checklist (Sprints 6-7)

**Objetivo:** Checklist de activos, integración con gestión de herramientas y entrevista de salida.

### Sprint 6: Checklist de Activos

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Crear entidad `TerminationChecklist` con Firestore | Modelo | 3 | Sprint 1 |
| Crear entidad `ChecklistItem` con categorías | Modelo | 2 | Sprint 1 |
| Definir plantilla de checklist por defecto (12 items) | Data | 3 | Modelo |
| Implementar CRUD de checklist (marcar ítems) | Service | 5 | Modelo |
| Implementar bloqueo de transición si hay activos pendientes | Service | 5 | Sprint 2 + Checklist |
| Registrar incidentes (pérdida/daño) con valor | Service | 3 | Checklist |
| Generar cargo por activo perdido (descuento) | Service | 3 | Checklist |
| Integrar con `herramientas_service` existente | Service | 5 | Checklist |
| Crear UI de checklist con categorías y estados | Frontend | 8 | Sprint 2 |
| Pruebas de checklist | QA | 5 | Service |

**Total sprint 6: 42 pts**

### Sprint 7: Entrevista de Salida

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Crear entidad `TerminationInterview` | Modelo | 3 | Sprint 1 |
| Implementar CRUD de entrevista | Service | 3 | Modelo |
| Implementar preguntas estructuradas (5 dimensiones) | Service | 3 | Entrevista |
| Integrar entrevista como paso opcional/configurable | Service | 5 | Sprint 2 |
| Crear UI de formulario de entrevista | Frontend | 8 | Sprint 2 |
| Crear UI de resumen de entrevista | Frontend | 3 | UI |
| Pruebas de entrevista | QA | 5 | Service |

**Total sprint 7: 30 pts**

**Fase 3 total: 72 pts** ✅

---

## 5. Fase 4: Documentos y Expediente (Sprints 8-9)

**Objetivo:** Generación automática de documentos legales, expediente legal y clasificación de riesgo.

### Sprint 8: Generación de Documentos

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Crear entidad `TerminationDocument` con metadatos | Modelo | 3 | Sprint 1 |
| Implementar sistema de plantillas (Jinja2 para PDF) | Service | 8 | Modelo |
| Generar carta de desvinculación | Service | 5 | Plantillas |
| Generar carta de despido | Service | 3 | Plantillas |
| Generar carta de aceptación de renuncia | Service | 3 | Plantillas |
| Generar acta de liquidación (PDF con desglose) | Service | 8 | Sprint 10 (Settlement) |
| Generar certificación laboral con código QR | Service | 5 | Sprint 8 |
| Implementar sistema de verificación pública por QR | Service | 5 | Documentos |
| Numeración automática de documentos | Service | 3 | Documentos |
| Integrar con `work_certificate.py` existente | Service | 3 | Documentos |
| Pruebas de generación de documentos | QA | 8 | Service |

**Total sprint 8: 54 pts**

### Sprint 9: Riesgo Legal y Expediente

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Crear entidad `TerminationRiskAssessment` | Modelo | 3 | Sprint 1 |
| Implementar cálculo de puntuación de riesgo | Service | 8 | Modelo |
| Implementar factores de riesgo predefinidos (10 factores) | Service | 5 | Cálculo |
| Implementar acciones recomendadas por nivel | Service | 3 | Factores |
| Crear entidad `TerminationLegalCase` | Modelo | 5 | Sprint 1 |
| Implementar CRUD de expediente legal | Service | 5 | Modelo |
| Implementar subida de evidencias | Service | 3 | LegalCase |
| Crear entidad `EvidenceFile` | Modelo | 2 | LegalCase |
| Bloquear transiciones si riesgo alto sin revisión | Service | 5 | Sprint 2 + Risk |
| Pruebas de riesgo y expediente | QA | 5 | Service |

**Total sprint 9: 44 pts**

**Fase 4 total: 98 pts** ✅

---

## 6. Fase 5: Integraciones (Sprints 10-11)

**Objetivo:** Nómina de liquidación, TSS, contabilidad, portal del empleado y recontratación.

### Sprint 10: Nómina de Liquidación

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Implementar concepto "salario pendiente" en liquidación | Service | 3 | Sprint 1 |
| Implementar concepto "comisiones pendientes" | Service | 3 | Settlement |
| Implementar concepto "bonificaciones pendientes" | Service | 3 | Settlement |
| Implementar descuentos (préstamos, adelantos) | Service | 3 | Settlement |
| Crear nómina especial con `periodSubType: "liquidation"` | Service | 8 | Payroll |
| Integrar liquidación → nómina de liquidación | Service | 5 | Nómina |
| Generar comprobante de pago desde nómina | Service | 3 | Nómina |
| Generar asientos contables automáticos | Service | 5 | Accounting |
| Versionado de liquidación (crear nueva versión) | Service | 5 | Settlement |
| Pruebas de liquidación extendida | QA | 8 | Settlement |

**Total sprint 10: 46 pts**

### Sprint 11: TSS, Accesos y Recontratación

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Generar datos para novedad TSS | Service | 5 | Sprint 1 |
| Marcar empleado como pendiente de baja TSS | Service | 3 | TSS |
| Implementar confirmación de baja TSS | Service | 3 | TSS |
| Integrar con Security (revocación de accesos) | Service | 5 | Sprint 2 |
| Crear `RehireRequest` entidad y CRUD | Modelo | 5 | Sprint 1 |
| Implementar lógica de recontratación | Service | 8 | RehireRequest |
| Preservar historial del empleado al recontratar | Service | 5 | Rehire |
| Crear endpoint `POST /rehire` | API | 3 | Rehire |
| Pruebas de integraciones | QA | 8 | Todo |

**Total sprint 11: 45 pts**

**Fase 5 total: 91 pts** ✅

---

## 7. Fase 6: Analítica (Sprint 12)

**Objetivo:** Dashboard, KPIs, reportes exportables y cierre técnico.

### Sprint 12: Dashboard y Reportes

| Tarea | Tipo | Puntos | Dependencias |
|---|---|---|---|
| Implementar dashboard de offboarding (estados, rotación) | Service | 5 | Sprint 1-5 |
| Implementar indicadores de riesgo legal | Service | 3 | Sprint 9 |
| Implementar KPIs de tiempo del proceso | Service | 5 | Sprint 2 |
| Exportar reporte de offboarding a Excel | Service | 5 | Sprint 1-11 |
| Exportar reporte a CSV (para inspecciones) | Service | 3 | Reporte |
| Crear UI de dashboard con gráficos | Frontend | 8 | Sprint 1-11 |
| Crear UI de reportes exportables | Frontend | 5 | Reporte |
| Pruebas de dashboard y reportes | QA | 5 | Service |
| Documentación técnica completa | Docs | 5 | Todo |
| Migración de datos existentes (liquidaciones → offboarding) | Data | 8 | Todo |

**Total sprint 12: 52 pts**

**Fase 6 total: 52 pts** ✅

---

## 8. Resumen de Carga por Sprint

```
Sprint  │ Fase          │ Puntos │ Capacidad │  % Uso
────────┼───────────────┼────────┼───────────┼────────
  1     │ Gobierno      │   27   │    40     │   68%
  2     │ Gobierno      │   37   │    40     │   93%
  3     │ Gobierno      │   30   │    40     │   75%
  4     │ Workflow/SOD  │   36   │    40     │   90%
  5     │ Workflow/SOD  │   37   │    40     │   93%
  6     │ Operación     │   42   │    40     │  105% ← ajustar
  7     │ Operación     │   30   │    40     │   75%
  8     │ Documentos    │   54   │    40     │  135% ← dividir
  9     │ Documentos    │   44   │    40     │  110% ← ajustar
 10     │ Integraciones │   46   │    40     │  115% ← ajustar
 11     │ Integraciones │   45   │    40     │  113% ← ajustar
 12     │ Analítica     │   52   │    40     │  130% ← dividir
────────┼───────────────┼────────┼───────────┼────────
Total   │               │  480   │   480     │  100%
```

**Nota:** Los sprints 6, 8, 9, 10, 11 y 12 exceden la capacidad ideal.
Se recomienda:
- Sprint 6: mover "pruebas" al sprint 7
- Sprint 8: mover "pruebas" al sprint 9
- Sprint 10: mover "pruebas" al sprint 11
- Sprint 12: dividir en 2 sprints (12a Dashboard, 12b Migración)

**Total recomendado: 13 sprints (26 semanas)**

---

## 9. Dependencias Críticas

| # | Dependencia | Impacta a | Riesgo |
|---|---|---|---|
| D-01 | Módulo Core HR existente (Employee CRUD) | Todos los sprints | ✅ Existente |
| D-02 | Módulo Payroll existente (PayPeriods) | Sprint 10 | ✅ Existente |
| D-03 | Módulo Assets existente (herramientas_service) | Sprint 6 | ✅ Existente |
| D-04 | Sistema de notificaciones existente | Sprint 3, 4 | ✅ Existente |
| D-05 | StateMachineValidator existente | Sprint 2 | ✅ Existente |
| D-06 | Sistema de plantillas (WeasyPrint) | Sprint 8 | ✅ Existente |
| D-07 | Módulo de contabilidad (accounting entries) | Sprint 10 | ⚠️ Verificar |
| D-08 | Sistema de roles/permisos actual | Sprint 5 | ⚠️ Verificar |
| D-09 | Portal de empleados (employee portal) | Sprint 11 | ❌ No existe |

---

## 10. Hitos Clave

| Hito | Sprint | Fecha estimada | Entregable |
|---|---|---|---|
| **M1: MVP Funcional** | Sprint 3 | Semana 6 | TerminationRequest CRUD + State Machine + Eventos |
| **M2: Con Gobierno** | Sprint 5 | Semana 10 | Aprobaciones + SOD + RBAC funcional |
| **M3: Con Operación** | Sprint 7 | Semana 14 | Checklist + Entrevista + Activos |
| **M4: Con Documentación** | Sprint 9 | Semana 18 | Documentos PDF + Riesgo Legal + Expediente |
| **M5: Con Integraciones** | Sprint 11 | Semana 22 | Nómina liquidación + TSS + Recontratación |
| **M6: Completado** | Sprint 12-13 | Semana 26 | Dashboard + Reportes + Migración + Docs |

---

## 11. Equipo Recomendado

| Rol | Cantidad | Dedicación |
|---|---|---|
| Backend Developer (Python/Flask) | 2 | 100% |
| Frontend Developer (Jinja2/JS) | 1 | 100% |
| QA Engineer | 1 | 50% (compartido con otros módulos) |
| Product Owner / Domain Expert | 1 | 25% |
| **Total** | **5** | |

---

*Fin del documento de roadmap.*  
*Versión 1.0 — Julio 2026*
