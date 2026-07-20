# Auditoría Integral del Proceso de Offboarding — VykOne ERP v2.0

**Versión del documento:** 2.0  
**Fecha:** Julio 2026  
**Versión auditada:** Código fuente en `main` (Python/Flask + Firestore)  
**Tipo:** Auditoría funcional, legal, de arquitectura y control interno  
**Auditor:** Consultor Senior RRHH / Arquitecto de Software Empresarial  
**Alcance:** Módulo de Gestión de Salida de Empleados (Offboarding)

---

## Índice

1. Resumen Ejecutivo  
2. Puntuación Global  
3. Matriz de Cumplimiento  
4. Arquitectura del Proceso Actual  
5. Hallazgos  
   5.1 Críticos  
   5.2 Alta Prioridad  
   5.3 Media Prioridad  
   5.4 Baja Prioridad  
6. Modelo de Datos Propuesto  
7. Mapa de Estados  
8. Matriz RACI  
9. Controles SOX  
10. Gestión de Riesgos Legales  
11. Roadmap de Mejoras  
12. Recomendaciones Priorizadas  
13. Conclusión  

---

## 1. Resumen Ejecutivo

### 1.1 Propósito de la Auditoría

Determinar si el proceso actual de desvinculación/offboarding de empleados en VykOne ERP cumple con:

- Legislación laboral vigente de la República Dominicana (Ley 16-92, Ley 87-01)
- Mejores prácticas internacionales de gestión humana (offboarding)
- Controles de auditoría requeridos por empresas medianas y grandes (SOX, ISO)
- Automatización esperada en un ERP de RRHH moderno
- Trazabilidad necesaria para inspecciones laborales y litigios

### 1.2 Cambios Respecto a la Versión 1.0

| Aspecto | v1.0 | v2.0 |
|---|---|---|
| Enfoque | Liquidación (prestaciones) | Offboarding integral |
| Entidad principal | `Liquidacion` | `TerminationRequest` (agregado raíz) |
| Puntuación | 62/100 | **43/100** |
| Hallazgos críticos | 4 | 7 |
| Matriz RACI | No | Sí |
| Controles SOX | No | Sí |
| Riesgos legales | No | Sí |
| Recontratación | No | Sí |
| Expediente legal | No | Sí |

### 1.3 Nivel de Madurez General

| Dimensión | Nivel (1-5) |
|---|---|
| Cálculos prestaciones (Ley 16-92) | ★★★★☆ (4.5) |
| Flujo de negocio (offboarding) | ★☆☆☆☆ (1.5) |
| Control interno / SOD | ★☆☆☆☆ (1.0) |
| Auditoría y trazabilidad | ★★☆☆☆ (2.0) |
| Automatización | ★★☆☆☆ (1.5) |
| Integración (nómina, TSS, activos) | ★☆☆☆☆ (1.0) |
| Gestión documental legal | ★☆☆☆☆ (1.0) |
| **Global** | **★☆☆☆☆ (1.7 / 5)** |

### 1.4 Riesgos Identificados

| Tipo | Cantidad | Severidad |
|---|---|---|
| Críticos | 7 | Requieren acción inmediata |
| Altos | 8 | Requieren acción en 30-60 días |
| Medios | 5 | Requieren acción en 90 días |
| Bajos | 3 | Requieren acción en 180 días |

---

## 2. Puntuación Global: 43/100

### 2.1 Desglose por Área

| Área | Peso | Nota | Ponderado | Justificación |
|---|---|---|---|---|
| Cumplimiento laboral | 10% | 85 | 8.5 | Sólido en Ley 16-92, faltan tipos de salida y documentos |
| Cálculos de prestaciones | 15% | 90 | 13.5 | Excelente motor, error en exención TSS de vacaciones |
| Flujo de negocio (offboarding) | 20% | 35 | 7.0 | No existe como proceso; liquidación = desvinculación |
| Control interno / SOD | 15% | 20 | 3.0 | Sin aprobaciones, sin segregación, sin estados intermedios |
| Offboarding (activos, accesos, docs) | 15% | 20 | 3.0 | Checklist offline, sin integración |
| Auditoría y trazabilidad | 10% | 40 | 4.0 | Bitácora presente pero incompleta, sin versionado |
| Automatización | 10% | 30 | 3.0 | Proceso mayormente manual |
| Integración (nómina, contab., TSS) | 5% | 25 | 1.25 | Nómina de liquidación no existe, asientos contables no existen |

**Total ponderado: 43.25 → 43/100**

### 2.2 Comparativo Contra Referencias del Mercado

| Producto | Puntaje estimado | Dif con VykOne |
|---|---|---|
| Factorial HR | 82/100 | +39 |
| Buk | 80/100 | +37 |
| SAP SuccessFactors | 88/100 | +45 |
| BambooHR | 78/100 | +35 |
| ADP Workforce Now | 85/100 | +42 |
| Workday HCM | 90/100 | +47 |
| **VykOne (actual)** | **43/100** | — |
| **VykOne v2 propuesto** | **85-90/100** | **+42 a +47** |

---

## 3. Matriz de Cumplimiento

| Requisito | Estado | Observación |
|---|---|---|
| Cálculo Preaviso Art. 76 | ✅ Cumple | Correcto |
| Cálculo Cesantía Art. 80 | ✅ Cumple | Correcto (full scale 6-13-21-23) |
| Cálculo Vacaciones Art. 177/180/182 | ✅ Cumple | Correcto con tabla proporcional |
| Cálculo Regalía Pascual Art. 219 | ✅ Cumple | Correcto (1/12 YTD) |
| Exenciones fiscales correctas | ❌ No cumple | Vacaciones marcadas exentas TSS (deben ser gravables) |
| Salario pendiente incluido | ❌ No cumple | No se calcula |
| Tipos de terminación completos | ❌ No cumple | Solo 4/10+ |
| Entidad TerminationRequest | ❌ No cumple | No existe como agregado raíz |
| Flujo de aprobación | ❌ No cumple | No existe |
| Estados intermedios del proceso | ❌ No cumple | Solo activo → inactivo |
| Segregación de funciones (SOD) | ❌ No cumple | Una persona puede hacer todo |
| Validaciones previas bloqueantes | ❌ No cumple | No existen |
| Gestión de activos integrada | ❌ No cumple | Checklist sin integración |
| Generación documentos legales | ❌ No cumple | Sin cartas, actas, liquidación PDF |
| Entrevista de salida | ❌ No cumple | No integrada al flujo |
| Nómina de liquidación | ❌ No cumple | No existe |
| Asientos contables automáticos | ❌ No cumple | No existen |
| Notificación/baja TSS | ❌ No cumple | No implementada |
| Versionado de cálculos | ❌ No cumple | No existe |
| Recontratación / RehireRequest | ❌ No cumple | No implementada |
| Expediente legal | ❌ No cumple | No implementado |
| Riesgo legal por tipo de salida | ❌ No cumple | No clasificado |
| Bitácora de auditoría | ✅ Parcial | Eventos registrados, faltan inmutabilidad y detalle |
| Reportes exportables | ❌ No cumple | No existen |
| API REST | ✅ Cumple | Endpoints POST/GET/DELETE |
| Pruebas unitarias | ✅ Cumple | 596 líneas en test_liquidacion.py |

---

## 4. Arquitectura del Proceso Actual

### 4.1 Diagrama de Flujo Actual (Estado: Julio 2026)

```
┌──────────┐
│  ACTIVO  │
└────┬─────┘
     │
     ├──────────────────────────────────────────────┐
     │                                              │
     ▼                                              ▼
┌──────────────────────┐              ┌──────────────────────────┐
│ Liquidacion (formal) │              │ /terminate (rápida)      │
│ /rrhh/employees/     │              │ POST /rrhh/employees/    │
│   <id>/liquidacion   │              │   <id>/terminate         │
├──────────────────────┤              ├──────────────────────────┤
│ 1. Formulario POST   │              │ 1. POST directo          │
│ 2. Calcular           │              │ 2. Sin cálculo           │
│ 3. Guardar y          │              │ 3. Sin validaciones      │
│    desvincular (1 clic)│             │ 4. Sin documentos        │
│ 4. status = inactivo  │              │ 5. status = inactivo     │
└──────────┬───────────┘              └──────────┬───────────────┘
           │                                      │
           └──────────────┬───────────────────────┘
                          ▼
                 ┌────────────────┐
                 │   INACTIVO     │
                 │ status cerrado │
                 └────────────────┘
```

**Problemas de arquitectura identificados:**

1. **No hay entidad raíz** — el proceso está disperso entre `liquidaciones`, `mass_actions`, `employees`
2. **Transición de 1 paso** — `activo → inactivo` sin estados intermedios
3. **Cálculo = ejecución** — no hay separación entre simular, aprobar y ejecutar
4. **Dos caminos inconsistentes** — la ruta formal y la ruta rápida producen el mismo resultado con diferentes controles
5. **Sin expediente legible** — no hay un único lugar donde consultar todo el historial de la desvinculación

### 4.2 Diagrama de Arquitectura Propuesto (VykOne v2)

```
┌─────────────────────────────────────────────────────────────────┐
│                    TERMINATION REQUEST                          │
│                    (Agregado Raíz)                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────┐     ┌──────────────────────────────┐   │
│  │ TerminationChecklist│     │    TerminationSettlement     │   │
│  │ ─ Activos           │     │    ─ Preaviso               │   │
│  │ ─ Accesos           │◄────│    ─ Cesantía               │   │
│  │ ─ Documentos        │     │    ─ Vacaciones             │   │
│  │ ─ Uniformes         │     │    ─ Regalía                │   │
│  └─────────────────────┘     │    ─ Salario pendiente      │   │
│                              │    ─ Comisiones pendientes  │   │
│  ┌─────────────────────┐     │    ─ Bonificaciones         │   │
│  │ TerminationDocument │     │    ─ Descuentos             │   │
│  │ ─ Carta desahucio   │     └──────────────────────────────┘   │
│  │ ─ Carta despido     │                                        │
│  │ ─ Acta liquidación  │     ┌──────────────────────────────┐   │
│  │ ─ Certificación     │     │    TerminationInterview      │   │
│  └─────────────────────┘     │    ─ Fecha                   │   │
│                              │    ─ Entrevistador           │   │
│  ┌─────────────────────┐     │    ─ Resultados              │   │
│  │ TerminationPayment  │     │    ─ Documento               │   │
│  │ ─ Método de pago    │     └──────────────────────────────┘   │
│  │ ─ Fecha de pago     │                                        │
│  │ ─ Comprobante       │     ┌──────────────────────────────┐   │
│  │ ─ Período nómina    │     │    TerminationLegalCase      │   │
│  └─────────────────────┘     │    ─ Riesgo legal            │   │
│                              │    ─ Acciones disciplinarias │   │
│  ┌─────────────────────┐     │    ─ Demandas                │   │
│  │   TerminationAudit  │     │    ─ Acuerdos                │   │
│  │   ─ Historial       │     └──────────────────────────────┘   │
│  │   ─ Cambios         │                                        │
│  │   ─ Aprobaciones    │     ┌──────────────────────────────┐   │
│  │   ─ Versionado      │     │    RehireRequest             │   │
│  └─────────────────────┘     │    (posterior reactivación)  │   │
│                              └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Hallazgos

### 5.1 Críticos (7)

| ID | Hallazgo | Impacto | Código asociado |
|---|---|---|---|
| **C-01** | **No existe expediente de desvinculación (TerminationRequest)** — la liquidación se usa como mecanismo de desvinculación, lo cual es conceptualmente incorrecto. No hay un agregado raíz que agrupe solicitud, aprobaciones, activos, documentos, pago y auditoría | El proceso no es auditable como unidad. Cada aspecto está disperso en colecciones inconexas. Imposible tener una vista 360° del proceso | `liquidacion.py:141-184`, `termination.py:25-28` |
| **C-02** | **Ausencia total de flujo de aprobación** — cualquier usuario con rol HR puede desvincular en un solo clic sin que nadie más revise o autorice | Riesgo de fraude, error humano, demandas laborales. Incumplimiento SOX severo | `liquidacion.py:130-184` |
| **C-03** | **No existe segregación de funciones (SOD)** — la misma persona puede solicitar, aprobar, calcular liquidación, ejecutar pago y cerrar el proceso | Sin controles internos. Auditoría financiera detectaría esto como hallazgo mayor inmediatamente | `liquidacion.py:21-27` (sin roles) |
| **C-04** | **Cero validaciones previas bloqueantes** — no se verifica existencia de activos asignados, préstamos activos, nóminas pendientes, licencias activas, procesos disciplinarios abiertos | Riesgo de pérdida de activos, doble pago, litigios laborales | `liquidacion.py` y `termination.py` no invocan ninguna validación |
| **C-05** | **Ruta directa POST /terminate permite desvincular sin liquidación ni controles** — endpoint de 36 líneas que cambia status sin calcular prestaciones, sin validaciones, sin documentos | Un empleado puede ser desvinculado sin recibir lo que legalmente le corresponde. Exposición legal máxima | `termination.py:13-35` |
| **C-06** | **Transición directa activo → inactivo sin estados intermedios** — no hay estado "en proceso de desvinculación", "pendiente de aprobación", "pendiente de pago" | Imposible auditar en qué etapa está cada caso. No soporta procesos batch ni workflow. Cualquier interrupción (activos no devueltos) no puede pausar el flujo | `liquidacion.py:143` `employee["status"] = "inactivo"` |
| **C-07** | **No se genera documentación legal automática** — no hay cartas de desahucio, despido, aceptación de renuncia, acta de liquidación, recibo de pago | Sin respaldo documental, la empresa queda indefensa ante litigios laborales. El Ministerio de Trabajo exige esta documentación | No hay módulo de generación de documentos de offboarding |

### 5.2 Alta Prioridad (8)

| ID | Hallazgo | Impacto |
|---|---|---|
| A-01 | Tipos de terminación incompletos (faltan: jubilación, fallecimiento, despido injustificado, mutuo acuerdo, fin contrato, otros configurables) | Clasificación legal inadecuada. Datos erróneos en reportes TSS y DGT |
| A-02 | El cálculo de liquidación omite conceptos obligatorios: salario pendiente, comisiones, bonificaciones, horas extras | La liquidación puede ser menor a lo legalmente debido, generando reclamaciones |
| A-03 | No existe nómina especial de liquidación para pagar prestaciones | Mezcla conceptos de liquidación con nómina regular, complicando contabilidad y reportes TSS |
| A-04 | No existe integración con gestión de activos — el offboarding checklist está definido pero no bloquea ni se integra al flujo | Activos pueden perderse, no hay registro de devolución, no se generan cargos por daños |
| A-05 | No existe entrevista de salida como paso del proceso | Se pierde información valiosa sobre clima laboral, motivos de rotación, riesgos legales |
| A-06 | Los documentos existentes (certificación laboral) no se generan automáticamente al desvincular | Proceso manual, riesgo de error, demora en entrega al empleado |
| A-07 | No hay versionado de liquidaciones — cada nuevo cálculo sobrescribe el anterior | Imposible auditar cambios, corregir errores, o mantener histórico |
| A-08 | Los tipos de terminación son inconsistentes entre modelos (`LiquidacionInput.terminationType` tiene 4 opciones, `Employee.terminationType` tiene 5, `Contract.terminationType` tiene 5) | Datos corruptos, reportes inconsistentes, imposible hacer reporting confiable |

### 5.3 Media Prioridad (5)

| ID | Hallazgo |
|---|---|
| M-01 | No se marca al empleado como "pendiente de baja TSS" ni se generan datos para novedades |
| M-02 | No existe clasificación de riesgo legal por tipo de terminación |
| M-03 | No hay dashboard de offboarding (casos activos, pendientes por etapa, indicadores de rotación) |
| M-04 | No se revocan accesos a sistemas, API keys ni sesiones al desvincular |
| M-05 | No hay manejo de reingreso/recontratación (RehireRequest) — el historial previo se pierde |

### 5.4 Baja Prioridad (3)

| ID | Hallazgo |
|---|---|
| B-01 | Mensajes de confirmación genéricos ("Empleado desvinculado") sin detalle del proceso completado |
| B-02 | No hay exportación a PDF de la liquidación — solo vista HTML |
| B-03 | No hay wizard de offboarding paso a paso — todo en una sola pantalla |

---

## 6. Modelo de Datos Propuesto

### 6.1 Entidad Raíz: TerminationRequest

```python
class TerminationRequest(BaseModel):
    """Solicitud de desvinculación — agregado raíz del proceso de offboarding."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    requestNumber: str = ""  # Formato: OFF-YYYY-NNNNN
    employeeId: str = ""
    employeeName: str = ""
    cedula: str = ""

    # Datos de la solicitud
    requestDate: str = ""  # Fecha de creación de la solicitud
    effectiveDate: str = ""  # Fecha efectiva de salida
    lastWorkDate: str = ""  # Último día trabajado
    terminationType: str = ""  # Catálogo completo
    terminationReason: str = ""
    detailedReason: str = ""  # Observaciones detalladas
    initiatedBy: str = ""  # Email de quien inicia
    initiatedByRole: str = ""  # supervisor | hr | employee

    # Estado del proceso
    status: TerminationStatus = TerminationStatus.DRAFT

    # Clasificación de riesgo
    legalRisk: LegalRiskLevel = LegalRiskLevel.LOW
    legalRiskNotes: str = ""

    # Fechas clave del proceso
    submittedAt: str = ""
    approvedAt: str = ""
    settlementCalculatedAt: str = ""
    settlementApprovedAt: str = ""
    assetsReturnedAt: str = ""
    accessRevokedAt: str = ""
    paidAt: str = ""
    closedAt: str = ""

    # Aprobaciones
    approvalHistory: list[TerminationApproval] = []

    # Relaciones (IDs)
    settlementId: str = ""  # TerminationSettlement.id
    checklistId: str = ""  # TerminationChecklist.id
    interviewId: str = ""  # TerminationInterview.id
    paymentId: str = ""  # TerminationPayment.id
    legalCaseId: str = ""  # TerminationLegalCase.id
    rehireId: str = ""  # RehireRequest.id (si aplica)

    # Auditoría
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""
    statusHistory: list[StatusChange] = []
    version: int = 1
```

### 6.2 Entidades Relacionadas

```python
class TerminationApproval(BaseModel):
    """Registro de aprobación individual."""
    approverEmail: str = ""
    approverName: str = ""
    role: str = ""  # supervisor | hr_manager | finance | treasury
    decision: str = ""  # approved | rejected
    comment: str = ""
    decidedAt: str = ""


class TerminationChecklist(BaseModel):
    """Checklist de offboarding."""
    id: str = ""
    requestId: str = ""
    items: list[ChecklistItem] = []
    completedAt: str = ""
    completedBy: str = ""


class ChecklistItem(BaseModel):
    taskId: str = ""
    task: str = ""  # "Devolver laptop", "Entregar carnet", etc.
    category: str = ""  # assets | systems | legal | hr
    completed: bool = False
    completedBy: str = ""
    completedAt: str = ""
    notes: str = ""
    requiresSignature: bool = False


class TerminationInterview(BaseModel):
    """Entrevista de salida."""
    id: str = ""
    requestId: str = ""
    interviewDate: str = ""
    interviewerName: str = ""
    intervieweeName: str = ""
    reasonForLeaving: str = ""
    feedback: str = ""
    wouldReturn: bool = True
    recommendations: str = ""
    documentFile: str = ""  # URL al documento firmado


class TerminationDocument(BaseModel):
    """Documento generado automáticamente."""
    id: str = ""
    requestId: str = ""
    documentType: str = ""  # termination_letter | settlement | certificate | receipt
    documentNumber: str = ""
    generatedAt: str = ""
    generatedBy: str = ""
    fileUrl: str = ""
    signedByEmployer: bool = False
    signedByEmployee: bool = False
    qrCode: str = ""
    verificationUrl: str = ""


class TerminationPayment(BaseModel):
    """Pago de la liquidación."""
    id: str = ""
    requestId: str = ""
    paymentMethod: str = ""  # payroll | transfer | check | cash
    payrollPeriodId: str = ""  # Si se paga vía nómina de liquidación
    totalAmount: float = 0.0
    conceptBreakdown: dict = {}
    paidAt: str = ""
    paidBy: str = ""
    receiptUrl: str = ""  # Comprobante de pago
    accountingEntryId: str = ""  # Asiento contable generado


class TerminationLegalCase(BaseModel):
    """Expediente legal asociado a la desvinculación."""
    id: str = ""
    requestId: str = ""
    riskLevel: LegalRiskLevel = LegalRiskLevel.LOW
    hasLawsuit: bool = False
    lawsuitDetails: str = ""
    disciplinaryActions: list[str] = []  # IDs de acciones disciplinarias
    agreements: list[str] = []  # IDs de acuerdos firmados
    evidenceFiles: list[str] = []  # URLs a evidencias
    legalCounsel: str = ""
    notes: str = ""


class RehireRequest(BaseModel):
    """Solicitud de recontratación de un empleado previamente desvinculado."""
    id: str = ""
    originalRequestId: str = ""  # TerminationRequest original
    employeeId: str = ""
    employeeName: str = ""
    newHireDate: str = ""
    newPosition: str = ""
    newSalary: float = 0.0
    preservesSeniority: bool = False  # ¿La antigüedad es continua?
    previousSeniorityDays: int = 0
    resetBenefits: bool = True  # ¿Reiniciar vacaciones y prestaciones?
    status: str = "draft"  # draft | approved | executed | cancelled
    createdBy: str = ""
    createdAt: str = ""
```

### 6.3 Catálogo de Tipos de Terminación

```python
class TerminationType(str, Enum):
    RENUNCIA_VOLUNTARIA = "renuncia_voluntaria"
    DESAHUCIO_EMPLEADOR = "desahucio_empleador"
    DIMISION_JUSTIFICADA = "dimision_justificada"
    DESPIDO_JUSTIFICADO = "despido_justificado"
    DESPIDO_INJUSTIFICADO = "despido_injustificado"
    MUTUO_ACUERDO = "mutuo_acuerdo"
    JUBILACION = "jubilacion"
    FALLECIMIENTO = "fallecimiento"
    FIN_CONTRATO_TEMPORAL = "fin_contrato_temporal"
    ABANDONO = "abandono"
    OTRO = "otro"
```

### 6.4 Catálogo de Estados

```python
class TerminationStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PENDING_SETTLEMENT = "pending_settlement"
    SETTLEMENT_CALCULATED = "settlement_calculated"
    SETTLEMENT_APPROVED = "settlement_approved"
    PENDING_ASSETS = "pending_assets"
    PENDING_ACCESS_REVOCATION = "pending_access_revocation"
    PENDING_PAYMENT = "pending_payment"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
```

### 6.5 Clasificación de Riesgo Legal

```python
class LegalRiskLevel(str, Enum):
    LOW = "low"          # Renuncia voluntaria, jubilación
    MEDIUM = "medium"    # Desahucio empleador, fin contrato
    HIGH = "high"        # Despido justificado, abandono
    CRITICAL = "critical"  # Despido injustificado, litigio abierto
```

---

## 7. Mapa de Estados

### 7.1 Diagrama de Estados (State Machine)

```
                    ┌──────────┐
                    │  DRAFT   │
                    └────┬─────┘
                         │ submit
                         ▼
              ┌───────────────────┐
              │ PENDING_APPROVAL  │◄────────────┐
              └────────┬──────────┘              │
                       │ approve                 │ reject
                       ▼                         │
              ┌───────────────────┐              │
              │     APPROVED      │──────────────┘
              └────────┬──────────┘
                       │ calculate settlement
                       ▼
        ┌─────────────────────────┐
        │ PENDING_SETTLEMENT      │
        └────────┬────────────────┘
                 │ calculate
                 ▼
        ┌─────────────────────────┐
        │ SETTLEMENT_CALCULATED   │
        └────────┬────────────────┘
                 │ approve settlement
                 ▼
        ┌─────────────────────────┐
        │ SETTLEMENT_APPROVED     │
        └────────┬────────────────┘
                 │ (paralelo)
        ┌────────┴────────┐
        ▼                 ▼
┌──────────────┐  ┌──────────────┐
│PENDING_ASSETS│  │PENDING_ACCESS│
│              │  │_REVOCATION   │
└──────────┬───┘  └──────┬───────┘
           │             │
           └──────┬──────┘
                  ▼
        ┌────────────────────────┐
        │    PENDING_PAYMENT     │
        └─────────┬──────────────┘
                  │ pay
                  ▼
        ┌────────────────────────┐
        │       COMPLETED        │
        └────────────────────────┘

    Cualquier estado puede ir a CANCELLED o REJECTED.
    COMPLETADO puede derivar en RehireRequest.
```

### 7.2 Transiciones Permitidas

| Desde | Hacia | Condición |
|---|---|---|
| DRAFT | PENDING_APPROVAL | Enviado por creador |
| PENDING_APPROVAL | APPROVED | Aprobado por RRHH (≠ creador) |
| PENDING_APPROVAL | REJECTED | Rechazado con motivo |
| APPROVED | PENDING_SETTLEMENT | Asignado para cálculo |
| PENDING_SETTLEMENT | SETTLEMENT_CALCULATED | Liquidación calculada |
| SETTLEMENT_CALCULATED | SETTLEMENT_APPROVED | Aprobado por Finanzas (≠ calculador) |
| SETTLEMENT_APPROVED | PENDING_ASSETS | Pendiente devolución activos |
| SETTLEMENT_APPROVED | PENDING_ACCESS_REVOCATION | Pendiente revocación accesos |
| PENDING_ASSETS | PENDING_PAYMENT | Todos los activos devueltos |
| PENDING_ACCESS_REVOCATION | PENDING_PAYMENT | Accesos revocados |
| PENDING_PAYMENT | COMPLETED | Pago registrado |
| Cualquiera | CANCELLED | Decisión de RRHH |
| Cualquiera | REJECTED | Decisión de aprobador |

---

## 8. Matriz RACI

### 8.1 Matriz de Responsabilidades por Actividad

| Actividad | Supervisor | RH | Finanzas | TI | Legal | Empleado |
|---|---|---|---|---|---|---|
| Solicitar desvinculación | **R** | A | — | — | — | C |
| Aprobar desvinculación | C | **R** | — | — | I | — |
| Clasificar riesgo legal | I | **R** | — | — | C | — |
| Calcular liquidación | — | **R** | A | — | — | — |
| Aprobar liquidación | — | C | **R** | — | — | — |
| Ejecutar checklist activos | — | C | — | — | — | **R** |
| Verificar devolución activos | — | **R** | — | I | — | — |
| Revocar accesos sistemas | — | C | — | **R** | — | — |
| Revocar correo y API keys | — | C | — | **R** | — | — |
| Generar documentos legales | — | **R** | — | — | C | — |
| Realizar entrevista salida | I | **R** | — | — | — | C |
| Registrar pago liquidación | — | I | **R** | — | — | — |
| Notificar baja TSS | — | **R** | I | — | — | — |
| Cerrar expediente offboarding | I | **R** | — | — | I | — |
| Archivar expediente legal | — | C | — | — | **R** | — |
| Gestionar recontratación | C | **R** | A | — | — | — |

**Leyenda:** R = Responsable, A = Aprueba, C = Consultado, I = Informado

### 8.2 Reglas de Segregación de Funciones (SOD)

| Combinación prohibida | Riesgo |
|---|---|
| Quien solicita ≠ quien aprueba | Fraude, colusión |
| Quien calcula liquidación ≠ quien la aprueba | Error no detectado, manipulación |
| Quien aprueba liquidación ≠ quien ejecuta pago | Aprobar y pagar a sí mismo |
| Quien verifica activos ≠ quien devuelve activos | Colusión en pérdida de activos |
| Quien ejecuta pago ≠ quien concilia contabilidad | Omisión de registro contable |

**Validación actual en VykOne:** Solo existe en `mass_actions.py:308-310` para acciones masivas. No aplica a desvinculaciones.

---

## 9. Controles SOX

### 9.1 Evaluación de Controles Actuales

| Control SOX | Requerido | Estado en VykOne |
|---|---|---|
| Segregación de funciones | ✅ | ❌ No implementado |
| Doble aprobación en transacciones críticas | ✅ | ❌ No implementado |
| Registro de cambios inmutable | ✅ | ❌ Sobrescribe datos |
| Evidencia documental de cada transacción | ✅ | ❌ No genera documentos |
| Pistas de auditoría completas | ✅ | ✅ Parcial |
| Controles de acceso basados en roles | ✅ | ❌ Solo rol HR genérico |
| Conciliación periódica | ✅ | ❌ No implementada |
| Políticas y procedimientos documentados | ✅ | ❌ No documentados |
| Revisión independiente de transacciones | ✅ | ❌ No implementada |
| Autorización explícita de montos | ✅ | ❌ No implementada |

### 9.2 Controles Propuestos

| # | Control | Cómo implementarlo |
|---|---|---|
| SOX-01 | Matriz SOD configurable por empresa | Tabla de reglas SOD en Firestore, validación antes de cada transición |
| SOX-02 | Doble aprobación para liquidaciones > umbral | Si monto total > X salarios mínimos, requiere 2 aprobadores |
| SOX-03 | Bitácora de cambios con diff | Almacenar `before/after` en cada modificación de TerminationRequest |
| SOX-04 | Versionado completo | Cada cambio incrementa `version` en el documento, no se sobrescribe |
| SOX-05 | Evidencia documental obligatoria | No permitir COMPLETED si faltan documentos obligatorios |
| SOX-06 | Roles granulares (RBAC) | `offboarding_initiator`, `offboarding_approver`, `settlement_calculator`, `settlement_approver`, `payment_executor` |
| SOX-07 | Límites de autorización por rol | Monto máximo que cada rol puede aprobar sin escalar |

---

## 10. Gestión de Riesgos Legales

### 10.1 Clasificación por Tipo de Terminación

| Tipo | Riesgo Legal | Fundamento |
|---|---|---|
| Renuncia voluntaria | LOW | Bajo riesgo si hay carta firmada |
| Jubilación | LOW | Proceso normado por ley de seguridad social |
| Fallecimiento | LOW | Causa de fuerza mayor |
| Fin contrato temporal | LOW | Fecha pactada |
| Mutuo acuerdo | MEDIUM | Requiere acuerdo firmado por ambas partes |
| Desahucio empleador | MEDIUM | Pago de prestaciones reduce riesgo |
| Dimisión justificada | MEDIUM | Empleado debe probar justa causa |
| Abandono | HIGH | Requiere procedimiento de notificación |
| Despido justificado | HIGH | Debe probarse falta grave, riesgo de litigio |
| Despido injustificado | HIGH | Indemnización adicional, probable litigio |
| Despido + litigio abierto | CRITICAL | Exposición legal máxima |

### 10.2 Acciones por Nivel de Riesgo

| Riesgo | Acciones requeridas |
|---|---|
| LOW | Proceso estándar, documentos básicos |
| MEDIUM | Revisión legal, carta notariada, testigos |
| HIGH | Aprobación de gerencia, revisión legal obligatoria, expediente completo |
| CRITICAL | Aprobación de dirección, representación legal, seguro de litigio |

---

## 11. Roadmap de Mejoras

### 11.1 Corto Plazo (30 días) — Controles Mínimos

| # | Tarea | Hallazgo |
|---|---|---|
| 1 | Crear entidad `TerminationRequest` como agregado raíz | C-01 |
| 2 | Separar simulación de ejecución (borrador vs. confirmar) | C-02, C-06 |
| 3 | Implementar flujo de aprobación obligatorio de 1 nivel | C-02 |
| 4 | Agregar validación de activos asignados bloqueante | C-04 |
| 5 | Deshabilitar ruta POST /terminate | C-05 |
| 6 | Agregar estado "en_proceso" antes de "inactivo" | C-06 |
| 7 | Corregir `exentoTSS` en vacaciones (cambiar a False) | A-02 |
| 8 | Agregar clasificación de riesgo legal por tipo | A-01, M-02 |

### 11.2 Mediano Plazo (90 días) — Proceso Integral

| # | Tarea | Hallazgo |
|---|---|---|
| 9 | Completar los 11 tipos de terminación con catálogo unificado | A-01, A-08 |
| 10 | Implementar estados del proceso según state machine propuesta | C-06 |
| 11 | Implementar segregación de funciones (SOD) con matriz RACI | C-03 |
| 12 | Agregar nómina especial de liquidación (`periodSubType: liquidation`) | A-03 |
| 13 | Integrar checklist de offboarding con devolución de activos | A-04 |
| 14 | Automatizar generación de documentos (cartas, actas, liquidación PDF) | C-07 |
| 15 | Agregar cálculo de salario pendiente, comisiones, bonificaciones | A-02 |
| 16 | Implementar versionado de liquidaciones | A-07 |
| 17 | Agregar reportes exportables para inspecciones laborales | M-03 |
| 18 | Generar datos para novedades TSS (marcar pendiente de baja) | M-01 |

### 11.3 Largo Plazo (180 días) — Madurez Empresarial

| # | Tarea | Hallazgo |
|---|---|---|
| 19 | Implementar entrevista de salida como paso obligatorio | A-05 |
| 20 | Crear expediente legal (`TerminationLegalCase`) con evidencias | M-05 |
| 21 | Implementar recontratación (`RehireRequest`) con preservación de historial | M-05 |
| 22 | Automatizar revocación de accesos y API keys | M-04 |
| 23 | Implementar dashboard de offboarding y rotación | M-03 |
| 24 | Agregar asientos contables automáticos para liquidación | A-03 |
| 25 | Implementar controles SOX completos (bitácora inmutable, diffs, roles granulares) | SOX-01 a SOX-07 |
| 26 | Implementar firma electrónica / QR en documentos | C-07 |
| 27 | Integrar con Ministerio de Trabajo (generación de formularios) | C-07 |

---

## 12. Recomendaciones Priorizadas

### 12.1 Críticas (Implementación Inmediata)

| # | Recomendación | Esfuerzo | Dependencias |
|---|---|---|---|
| R-01 | Crear entidad TerminationRequest como agregado raíz del proceso | 5 días | Ninguna |
| R-02 | Implementar flujo de aprobación obligatorio (reutilizar mass_actions) | 3 días | R-01 |
| R-03 | Agregar validaciones previas bloqueantes: activos, préstamos, nóminas | 4 días | R-01 |
| R-04 | Separar cálculo de ejecución (simular ≠ guardar) | 2 días | R-01 |
| R-05 | Deshabilitar ruta /terminate directa | 0.5 días | Ninguna |
| R-06 | Implementar estados intermedios (state machine) en TerminationRequest | 3 días | R-01 |
| R-07 | Implementar segregación de funciones (quien crea ≠ quien aprueba ≠ quien paga) | 3 días | R-02, R-06 |

### 12.2 Alta Prioridad (30-60 días)

| # | Recomendación | Esfuerzo |
|---|---|---|
| R-08 | Completar catálogo de tipos de terminación (11 tipos) | 2 días |
| R-09 | Agregar conceptos faltantes a liquidación (salario pendiente, comisiones, bonos) | 3 días |
| R-10 | Crear nómina especial de liquidación con `periodSubType: liquidation` | 5 días |
| R-11 | Integrar checklist de activos bloqueante (no permitir completar sin devolución) | 3 días |
| R-12 | Automatizar generación de cartas y actas con plantillas + QR | 5 días |
| R-13 | Agregar versionado de liquidaciones | 2 días |
| R-14 | Corregir exención TSS en vacaciones | 0.5 días |

### 12.3 Media Prioridad (90 días)

| # | Recomendación | Esfuerzo |
|---|---|---|
| R-15 | Implementar clasificación de riesgo legal por tipo de salida | 2 días |
| R-16 | Agregar dashboard de offboarding con indicadores | 4 días |
| R-17 | Generar datos para novedades TSS (pendiente de baja) | 3 días |
| R-18 | Implementar entrevista de salida como paso configurable | 3 días |
| R-19 | Implementar revocación de accesos automática (portal, API keys) | 5 días |

### 12.4 Baja Prioridad (180 días)

| # | Recomendación | Esfuerzo |
|---|---|---|
| R-20 | Implementar RehireRequest para recontrataciones | 4 días |
| R-21 | Crear expediente legal (TerminationLegalCase) | 3 días |
| R-22 | Agregar asientos contables automáticos para liquidaciones | 5 días |
| R-23 | Implementar firma electrónica en documentos de offboarding | 5 días |
| R-24 | Integrar formularios del Ministerio de Trabajo | 5 días |

---

## 13. Conclusión

### 13.1 Estado Actual

VykOne ERP tiene un **sólido motor de cálculo de prestaciones laborales** según la Ley 16-92, con una implementación matemática correcta y bien documentada. Sin embargo, el **proceso de offboarding como flujo empresarial integral está incompleto**.

Las principales debilidades son:

1. **No hay un proceso de offboarding** — hay un cálculo de liquidación que, al guardarse, desvincula al empleado
2. **No hay controles** — sin aprobaciones, sin validaciones, sin segregación de funciones
3. **No hay trazabilidad empresarial** — estados intermedios, versionado, expediente legal
4. **No hay automatización** — documentos, pago, activos, accesos, TSS

### 13.2 Estado Objetivo (VykOne v2)

Con la implementación del modelo propuesto:

- **TerminationRequest** como agregado raíz con 11 tipos de terminación y 12 estados
- **Matriz RACI** con segregación de funciones
- **Controles SOX** con doble aprobación, bitácora inmutable, versionado
- **Gestión de riesgos legales** clasificada por tipo de salida
- **Offboarding completo**: activos, accesos, documentos, entrevista, pago
- **Expediente legal** integrado con evidencias
- **Recontratación** con preservación de historial

### 13.3 Puntuación Final

| Escenario | Puntuación |
|---|---|
| VykOne actual | **43/100** |
| VykOne + corto plazo (30d) | **60/100** |
| VykOne + mediano plazo (90d) | **75/100** |
| VykOne + largo plazo (180d) | **85-90/100** |

---

*Documento generado como parte de la Auditoría Integral de Procesos de RRHH de VykOne ERP.*  
*Versión 2.0 — Julio 2026*
