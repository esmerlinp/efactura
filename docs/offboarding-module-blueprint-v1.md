# Offboarding Module Blueprint v1.0

**Proyecto:** VykOne ERP — Módulo de Gestión de Salida de Empleados  
**Versión del documento:** 1.0  
**Fecha:** Julio 2026  
**Clasificación:** Arquitectura empresarial  
**Audiencia:** Dirección de producto, arquitectos, desarrolladores, QA, RRHH, auditores  

---

## Índice

1. Visión General
2. Objetivos Estratégicos
3. Arquitectura del Sistema
4. Resumen del Modelo de Dominio
5. Resumen del Workflow
6. Resumen de Permisos y SOD
7. Eventos de Dominio
8. Roadmap
9. Anexos

---

## 1. Visión General

### 1.1 Propósito

Este blueprint define la arquitectura objetivo del módulo de Offboarding de VykOne ERP. Reemplaza el proceso actual donde "calcular liquidación = desvincular empleado" por un proceso empresarial completo, auditable, configurable y alineado con las mejores prácticas de RRHH para la República Dominicana.

### 1.2 Principios de Diseño

| Principio | Descripción |
|---|---|
| **Aggregate Root** | TerminationRequest como entidad raíz del proceso |
| **State Machine** | Ciclo de vida formal con 12 estados y transiciones validades |
| **SOD First** | Segregación de funciones desde el diseño, no como parche |
| **Event-Driven** | Eventos de dominio para integraciones desacopladas |
| **Auditability** | Versionado completo y bitácora inmutable |
| **Legal Compliance** | Cumplimiento Ley 16-92, Ley 87-01, Normas DGII desde el diseño |
| **Configurabilidad** | Reglas de negocio parametrizables, no hardcodeadas |

### 1.3 Estado Actual vs. Estado Objetivo

| Aspecto | Actual (Jul 2026) | Objetivo (V3) |
|---|---|---|
| Proceso | Liquidación = desvinculación | Offboarding completo con 12 estados |
| Entidad raíz | Ninguna (disperso) | TerminationRequest |
| Aprobaciones | Sin flujo | Workflow configurable con SOD |
| Estados | 2 (activo → inactivo) | 12 estados con state machine |
| Tipos de salida | 4 | 11 |
| Documentos | Solo certificación laboral | 6+ documentos automáticos |
| Activos | Checklist offline | Checklist integrado y bloqueante |
| Accesos | No se revocan | Revocación automática |
| Riesgo legal | No clasificado | RiskAssessment obligatorio |
| Recontratación | No soportada | RehireRequest con historial |
| Auditoría | Bitácora básica | Versionado completo + diff |

---

## 2. Objetivos Estratégicos

1. **Convertir el offboarding en un proceso empresarial gobernado** con trazabilidad completa y controles SOX
2. **Proteger a la empresa contra litigios laborales** mediante expediente documental y clasificación de riesgo
3. **Automatizar la generación de documentos legales** (cartas, actas, certificaciones) con código QR verificable
4. **Integrar el offboarding con nómina, activos, TSS y contabilidad** sin acoplamiento
5. **Reducir el tiempo de procesamiento** de una desvinculación de días a horas
6. **Proveer visibilidad gerencial** mediante dashboard de rotación, riesgos y KPIs

---

## 3. Arquitectura del Sistema

### 3.1 Bounded Contexts

El módulo de Offboarding se define como un **Bounded Context** dentro del ecosistema VykOne:

```
┌─────────────────────────────────────────────────────────────┐
│                    VYKONE ECOSYSTEM                         │
│                                                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐   │
│  │  Core HR   │  │  Payroll   │  │    Offboarding     │   │
│  │  Context   │◄─┤  Context   │◄─┤     CONTEXT        │   │
│  │            │  │            │  │  ★ NUEVO ★         │   │
│  │ Employees  │  │ PayPeriods │  │                    │   │
│  │ Contracts  │  │ TSS        │  │ TerminationRequest │   │
│  │ Vacations  │  │ Concepts   │  │ Settlement         │   │
│  │ Leaves     │  │ Accounting │  │ Checklist          │   │
│  │ Evaluations│  │            │  │ Documents          │   │
│  └─────┬──────┘  └─────┬──────┘  │ Interview          │   │
│        │               │         │ Payment            │   │
│        │               │         │ LegalCase          │   │
│        │               │         │ RiskAssessment     │   │
│        │               │         │ Rehire             │   │
│        │               │         └────────┬───────────┘   │
│        │               │                  │               │
│        ▼               ▼                  ▼               │
│  ┌────────────────────────────────────────────────────┐   │
│  │              Workflow Context                      │   │
│  │  State Machine · Approvals · Status History        │   │
│  └────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐   │
│  │  Assets    │  │  Security  │  │      Legal         │   │
│  │  Context   │  │  Context   │  │     Context        │   │
│  └────────────┘  └────────────┘  └────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Relaciones entre Contextos

| Contexto Originador | Contexto Destino | Evento/Acción |
|---|---|---|
| Offboarding | Core HR | `EmployeeTerminated` — inactiva empleado |
| Offboarding | Core HR | `EmployeeRehired` — reactiva empleado |
| Offboarding | Payroll | `SettlementApproved` — crea nómina de liquidación |
| Offboarding | Payroll | `PaymentCompleted` — genera comprobante |
| Offboarding | Assets | `TerminationRequested` — inicia checklist activos |
| Offboarding | Security | `AccessRevocationRequired` — revoca accesos |
| Offboarding | Legal | `HighRiskTermination` — notifica a legal |
| Core HR | Offboarding | `EmployeeDataRequired` — consulta datos del empleado |

### 3.3 Diagrama de Arquitectura (C4 Nivel 2)

```
┌──────────────────────────────────────────────────────────┐
│                    OFFBOARDING CONTEXT                    │
│                                                          │
│  ┌──────────────────────────────────────────┐           │
│  │            TerminationRequest            │           │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │           │
│  │  │Settlement│ │Checklist │ │Interview │ │           │
│  │  └──────────┘ └──────────┘ └──────────┘ │           │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │           │
│  │  │Documents │ │Payment   │ │LegalCase │ │           │
│  │  └──────────┘ └──────────┘ └──────────┘ │           │
│  │  ┌──────────┐ ┌──────────────────────┐  │           │
│  │  │Rehire    │ │ RiskAssessment       │  │           │
│  │  └──────────┘ └──────────────────────┘  │           │
│  └──────────────────────────────────────────┘           │
│                                                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐   │
│  │ State       │ │ Domain      │ │ TerminationRule │   │
│  │ Machine     │ │ Events      │ │ Engine          │   │
│  └─────────────┘ └─────────────┘ └─────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Resumen del Modelo de Dominio

### 4.1 Entidades Principales

| Entidad | Tipo | Descripción |
|---|---|---|
| `TerminationRequest` | Aggregate Root | Solicitud de desvinculación — entidad raíz del proceso |
| `TerminationSettlement` | Entity | Cálculo de prestaciones laborales (con versionado) |
| `TerminationChecklist` | Entity | Checklist de devolución de activos y cierre |
| `TerminationInterview` | Entity | Entrevista de salida |
| `TerminationDocument` | Entity | Documento legal generado automáticamente |
| `TerminationPayment` | Entity | Pago de liquidación |
| `TerminationLegalCase` | Entity | Expediente legal |
| `TerminationRiskAssessment` | Value Object | Evaluación de riesgo legal |
| `RehireRequest` | Aggregate Root | Solicitud de recontratación |
| `TerminationRequestVersion` | Entity | Versionado histórico de cambios |
| `TerminationRule` | Entity | Regla de negocio parametrizable |

### 4.2 Value Objects

| Value Object | Propósito |
|---|---|
| `TerminationType` | Catálogo de 11 tipos de salida |
| `TerminationStatus` | Catálogo de 12 estados del proceso |
| `LegalRiskLevel` | Nivel de riesgo (LOW/MEDIUM/HIGH/CRITICAL) |
| `SettlementVersion` | Versión del cálculo de liquidación |
| `DocumentTemplate` | Plantilla para generación de documentos |
| `ApprovalDecision` | Decisión de aprobación con comentario |

### 4.3 Relaciones

```
TerminationRequest 1──1──> TerminationSettlement
TerminationRequest 1──1──> TerminationChecklist
TerminationRequest 1──0..1──> TerminationInterview
TerminationRequest 1──0..N──> TerminationDocument
TerminationRequest 1──0..N──> TerminationPayment
TerminationRequest 1──0..1──> TerminationLegalCase
TerminationRequest 1──0..1──> TerminationRiskAssessment
TerminationRequest 1──0..1──> RehireRequest
TerminationRequest 1──0..N──> TerminationRequestVersion
```

Para especificación detallada, ver: [`offboarding-domain-model.md`](offboarding-domain-model.md)

---

## 5. Resumen del Workflow

### 5.1 Estados

| # | Estado | Código | Descripción |
|---|---|---|---|
| 1 | Borrador | `draft` | Solicitud creada, no enviada a aprobación |
| 2 | Pendiente aprobación supervisor | `pending_supervisor_approval` | Esperando aprobación del supervisor directo |
| 3 | Pendiente aprobación RRHH | `pending_hr_approval` | Esperando aprobación del departamento de RRHH |
| 4 | Aprobada | `approved` | Solicitud aprobada, lista para procesar |
| 5 | Pendiente liquidación | `pending_settlement` | Esperando cálculo de prestaciones |
| 6 | Pendiente activos | `pending_assets` | Esperando devolución de activos asignados |
| 7 | Pendiente pago | `pending_payment` | Esperando registro de pago |
| 8 | Pendiente documentos | `pending_documents` | Esperando generación de documentos |
| 9 | Pendiente baja TSS | `pending_tss` | Esperando registro de baja en TSS |
| 10 | Completada | `completed` | Proceso finalizado exitosamente |
| 11 | Cancelada | `cancelled` | Proceso cancelado (ej: empleado reconsidera) |
| 12 | Rechazada | `rejected` | Solicitud rechazada en aprobación |

### 5.2 Transiciones Principales

```
draft ──enviar──> pending_supervisor_approval
pending_supervisor_approval ──aprobar──> pending_hr_approval
pending_supervisor_approval ──rechazar──> rejected
pending_hr_approval ──aprobar──> approved
pending_hr_approval ──rechazar──> rejected
approved ──iniciar──> pending_settlement
pending_settlement ──calcular──> pending_assets (o pending_payment si no hay activos)
pending_assets ──devolver_activos──> pending_payment
pending_payment ──pagar──> pending_documents
pending_documents ──generar──> pending_tss
pending_tss ──notificar──> completed
cualquiera ──cancelar──> cancelled
```

Para especificación detallada, ver: [`offboarding-state-machine.md`](offboarding-state-machine.md)

---

## 6. Resumen de Permisos y SOD

### 6.1 Roles

| Rol | Código | Descripción |
|---|---|---|
| Supervisor | `supervisor` | Jefe directo del empleado |
| RRHH | `hr` | Departamento de Recursos Humanos |
| Finanzas | `finance` | Departamento de Finanzas (aprobación de pagos) |
| TI | `it` | Tecnología (revocación de accesos) |
| Legal | `legal` | Departamento Legal (riesgo y litigios) |
| Admin | `admin` | Superadministrador del sistema |

### 6.2 Matriz Resumida

| Operación | Supervisor | RRHH | Finanzas | TI | Legal |
|---|---|---|---|---|---|
| Crear solicitud | ✅ | ✅ | ❌ | ❌ | ❌ |
| Aprobar nivel 1 | C | ✅ | ❌ | ❌ | ❌ |
| Clasificar riesgo | ❌ | ✅ | ❌ | ❌ | C |
| Calcular liquidación | ❌ | ✅ | ❌ | ❌ | ❌ |
| Aprobar pago | ❌ | ❌ | ✅ | ❌ | ❌ |
| Verificar activos | ❌ | ✅ | ❌ | ❌ | ❌ |
| Revocar accesos | ❌ | ❌ | ❌ | ✅ | ❌ |
| Cerrar expediente | ❌ | ✅ | ❌ | ❌ | C |

*C = Consultado, no ejecutor*

Para especificación detallada, ver: [`offboarding-rbac-matrix.md`](offboarding-rbac-matrix.md)

---

## 7. Eventos de Dominio

### 7.1 Catálogo de Eventos

| Evento | Disparador | Payload mínimo | Consumidores esperados |
|---|---|---|---|
| `TerminationRequested` | Creación de solicitud | `{requestId, employeeId, type, date}` | Assets, Legal |
| `TerminationApproved` | Aprobación por RRHH | `{requestId, approvedBy}` | Payroll (preparar liquidación) |
| `SettlementCalculated` | Cálculo de liquidación | `{requestId, totalAmount}` | Notification |
| `SettlementApproved` | Aprobación de finanzas | `{requestId, approvedBy}` | Payroll (crear nómina) |
| `AssetsReturned` | Checklist completado | `{requestId, completedBy}` | Security (revocar accesos) |
| `AccessRevoked` | Accesos eliminados | `{requestId, completedBy}` | Offboarding |
| `PaymentCompleted` | Pago registrado | `{requestId, paymentId, amount}` | Documents (generar), Legal (archivar) |
| `DocumentsGenerated` | Documentos creados | `{requestId, documentIds[]}` | Notification |
| `TSSNotified` | Baja TSS registrada | `{requestId, tssRecordId}` | Offboarding (cerrar) |
| `TerminationCompleted` | Proceso finalizado | `{requestId, closedAt}` | Core HR (inactivar), Dashboard |
| `EmployeeRehired` | Recontratación | `{rehireId, employeeId, newHireDate}` | Core HR (reactivar), Payroll |

### 7.2 Esquema de Evento (Ejemplo)

```json
{
  "eventId": "evt_abc123",
  "eventType": "TerminationApproved",
  "version": 1,
  "occurredAt": "2026-07-20T14:30:00Z",
  "aggregateId": "tr_def456",
  "aggregateType": "TerminationRequest",
  "data": {
    "requestId": "tr_def456",
    "employeeId": "emp_789",
    "approvedBy": "maria@empresa.com",
    "approvalLevel": "hr"
  },
  "metadata": {
    "ownerUid": "uid_123",
    "sandbox": false,
    "traceId": "trace_xyz"
  }
}
```

---

## 8. Roadmap

| Fase | Sprints | Entregables | Dependencias |
|---|---|---|---|
| **1. Gobierno y Dominio** | 3 | TerminationRequest, State Machine, Eventos, RiskAssessment | Ninguna |
| **2. Workflow y SOD** | 2 | Flujo de aprobación, Matriz de permisos, Reglas SOD | Fase 1 |
| **3. Operación y Checklist** | 2 | Checklist de activos, Integración Assets, Entrevista | Fase 2 |
| **4. Documentos y Expediente** | 2 | Generación documentos PDF, Plantillas, LegalCase | Fase 3 |
| **5. Integraciones** | 2 | Nómina liquidación, TSS, Contabilidad, Portal | Fase 4 |
| **6. Analítica** | 1 | Dashboard, KPIs, Reportes exportables | Fase 1-5 |
| **Total** | **12** | | |

Para especificación detallada, ver: [`offboarding-roadmap.md`](offboarding-roadmap.md)

---

## 9. Anexos

| Documento | Propósito | Audiencia principal |
|---|---|---|
| [`offboarding-domain-model.md`](offboarding-domain-model.md) | Modelo de dominio completo con entidades, atributos, relaciones y bounded contexts | Arquitectos, desarrolladores |
| [`offboarding-state-machine.md`](offboarding-state-machine.md) | Definición formal de 12 estados, transiciones, pre/post condiciones | Desarrolladores, QA |
| [`offboarding-rbac-matrix.md`](offboarding-rbac-matrix.md) | Matriz de permisos por rol, reglas SOD, políticas de autorización | RRHH, auditores, desarrolladores |
| [`offboarding-api-contracts.yaml`](offboarding-api-contracts.yaml) | Especificación OpenAPI 3.0 de todos los endpoints del módulo | Desarrolladores frontend y backend |
| [`offboarding-roadmap.md`](offboarding-roadmap.md) | Roadmap técnico con fases, sprints, estimaciones y dependencias | Dirección de producto, project managers |
| [`offboarding-wireframes.md`](offboarding-wireframes.md) | Mockups low-fidelity de las pantallas principales del módulo | Diseñadores, desarrolladores frontend, stakeholders |

---

*Este documento es propiedad del proyecto VykOne ERP.*  
*Versión 1.0 — Julio 2026*
