# Offboarding Wireframes v1.0

**Anexo técnico al Blueprint de Offboarding**  
**Audiencia:** Diseñadores, desarrolladores frontend, stakeholders  
**Propósito:** Mockups low-fidelity de las pantallas principales del módulo de Offboarding

---

## 1. Convenciones

```
[Logo]           → Logo de VykOne
[Btn Acción]     → Botón
[Input Texto]    → Campo de texto
[Select]         → Selector desplegable
[Date]           → Selector de fecha
[Checkbox]       → Casilla de verificación
[Badge]          → Etiqueta de estado
[Tab: X]         → Pestaña de navegación
[─── Línea ───]  → Separador visual
[↑↓]             → Ordenable

Iconos usados:
📋 = Solicitud       💰 = Pago         📄 = Documento
✅ = Aprobado        ❌ = Rechazado     ⏳ = Pendiente
🔴 = Crítico         🟡 = Alto          🟢 = Bajo
📊 = Dashboard       👤 = Empleado      ⚙ = Configuración
```

---

## 2. Pantalla: Lista de Offboarding

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Logo]  VykOne  │  RRHH  │  Nómina  │  Offboarding  │  [👤 Admin]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  📋 Gestión de Offboarding                           [Btn + Nuevo]  │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ [Buscar empleado...]    [Select: Todos los estados]    [Buscar] │ │
│  │ [Date: Desde]  [Date: Hasta]  [Select: Tipo de salida]         │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌────────┬────────────┬──────────────┬────────┬────────┬──────────┐ │
│  │ # Sol  │ Empleado   │ Tipo         │ Estado │ Riesgo │ Fecha    │ │
│  ├────────┼────────────┼──────────────┼────────┼────────┼──────────┤ │
│  │OFF-001 │ Juan Pérez │ Desahucio    │ ⏳ Pen. │ 🟡 Alto│ 20/07/26│ │
│  │        │            │ empleador    │ aprob. │        │          │ │
│  ├────────┼────────────┼──────────────┼────────┼────────┼──────────┤ │
│  │OFF-002 │ María Gómez│ Renuncia     │ ✅     │ 🟢 Bajo│ 18/07/26│ │
│  │        │            │ voluntaria   │ Comp.  │        │          │ │
│  ├────────┼────────────┼──────────────┼────────┼────────┼──────────┤ │
│  │OFF-003 │ Pedro Díaz │ Despido      │ 💰 Pen.│ 🔴     │ 15/07/26│ │
│  │        │            │ justificado  │ pago   │ Crítico│          │ │
│  ├────────┼────────────┼──────────────┼────────┼────────┼──────────┤ │
│  │OFF-004 │ Ana Reyes  │ Mutuo        │ 📄 Pen.│ 🟡 Alto│ 14/07/26│ │
│  │        │            │ acuerdo      │ docs   │        │          │ │
│  └────────┴────────────┴──────────────┴────────┴────────┴──────────┘ │
│                                                                      │
│  Mostrando 4 de 12 solicitudes                    [< 1 2 3 >]        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Pantalla: Crear Solicitud

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Logo]  VykOne  │  RRHH  │  Nómina  │  Offboarding  │  [👤 Admin]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  📋 Nueva Solicitud de Offboarding          [← Volver a lista]      │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Datos del Empleado                                             │ │
│  │                                                                  │ │
│  │  [Input: Buscar empleado por nombre, cédula o ID...]  [🔍]     │ │
│  │                                                                  │ │
│  │  ┌──────────┬──────────────────────────────────────────────────┐ │ │
│  │  │ Nombre:  │ Juan Pérez Martinez                              │ │ │
│  │  │ Cédula:  │ 001-1234567-8                                    │ │ │
│  │  │ Cargo:   │ Analista de Sistemas                             │ │ │
│  │  │ Depto:   │ Tecnología                                       │ │ │
│  │  │ Ingreso: │ 15/03/2020 (6 años, 4 meses)                    │ │ │
│  │  │ Salario: │ RD$ 65,000.00                                    │ │ │
│  │  └──────────┴──────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Datos de la Desvinculación                                     │ │
│  │                                                                  │ │
│  │  Tipo de salida: [Select ▼]                                     │ │
│  │                   ├─ Renuncia voluntaria                        │ │
│  │                   ├─ Desahucio por el empleador                 │ │
│  │                   ├─ Dimisión justificada                       │ │
│  │                   ├─ Despido justificado                        │ │
│  │                   ├─ Despido injustificado                      │ │
│  │                   ├─ Mutuo acuerdo                              │ │
│  │                   ├─ Jubilación                                 │ │
│  │                   ├─ Fallecimiento                              │ │
│  │                   ├─ Fin de contrato temporal                   │ │
│  │                   ├─ Abandono                                   │ │
│  │                   └─ Otro                                       │ │
│  │                                                                  │ │
│  │  Fecha efectiva de salida:  [Date: ██/██/████]                  │ │
│  │  Último día trabajado:      [Date: ██/██/████]                  │ │
│  │                                                                  │ │
│  │  Motivo:                                                        │ │
│  │  [Textarea━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━]  │ │
│  │  [━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━]  │ │
│  │                                                                  │ │
│  │  Detalle adicional:                                             │ │
│  │  [Textarea━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━]  │ │
│  │                                                                  │ │
│  │  [Checkbox] Notificar al supervisor para aprobación             │ │
│  │                                                                  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Evaluación de Riesgo Legal (preliminar)                             │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Tipo: Despido justificado                                      │ │
│  │  Antigüedad: 6 años (+15 pts)                                   │ │
│  │  Sin amonestaciones registradas (+10 pts)                       │ │
│  │  ─────────────────────────────────────                          │ │
│  │  Puntaje: 25 / 100  →  [🟡 RIESGO ALTO]                        │ │
│  │                                                                  │ │
│  │  Acciones recomendadas:                                         │ │
│  │  • Revisión del departamento legal requerida                    │ │
│  │  • Documentar evidencias de la falta                            │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│                           [Btn: Guardar borrador]  [Btn: Enviar a   │
│                                                     aprobación →]   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Pantalla: Detalle de Solicitud (Con Pestañas)

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Logo]  VykOne  │  RRHH  │  Nómina  │  Offboarding  │  [👤 Admin]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  📋 OFF-001 · Juan Pérez · Desahucio empleador                      │
│                                                                      │
│  [Badge: ⏳ Pendiente aprobación RRHH]        [🟡 Riesgo Alto]      │
│                                                                      │
│  [Tab: Solicitud] [Tab: Liquidación] [Tab: Activos] [Tab: Docs]     │
│  [Tab: Entrevista] [Tab: Pagos] [Tab: Legal] [Tab: Auditoría]       │
│                                                                      │
│  ═══════════════════════════════════════════════════════════════════  │
│                                                                      │
│  │ TAB: SOLICITUD (activo)                                          │
│  │                                                                  │
│  │  ┌──────────────┬─────────────────────────────────────────────┐  │
│  │  │ Empleado     │ Juan Pérez Martínez                         │  │
│  │  │ Cédula       │ 001-1234567-8                               │  │
│  │  │ Tipo         │ Desahucio por el empleador                  │  │
│  │  │ Fecha efect. │ 31/07/2026                                  │  │
│  │  │ Motivo       │ Reestructuración del departamento de TI     │  │
│  │  │ Creado por   │ María Rodríguez (RRHH) · 20/07/2026         │  │
│  │  └──────────────┴─────────────────────────────────────────────┘  │
│  │                                                                  │
│  │  ┌──────────────────────────────────────────────────────────┐    │
│  │  │  Aprobaciones                                           │    │
│  │  │                                                          │    │
│  │  │  ✅ Supervisor: Carlos Jiménez · 21/07/2026 09:30       │    │
│  │  │     "De acuerdo con la salida. El área será reestructurada."│  │
│  │  │                                                          │    │
│  │  │  ⏳ RRHH: Pendiente                                      │    │
│  │  │     [Select: Aprobar] [Btn: Confirmar]                   │    │
│  │  └──────────────────────────────────────────────────────────┘    │
│  │                                                                  │
│  │  ┌──────────────────────────────────────────────────────────┐    │
│  │  │  Información del proceso                                │    │
│  │  │  ● Borrador          → 20/07/2026 14:30 por María R.    │    │
│  │  │  ● Pend. aprob. sup. → 20/07/2026 14:31                 │    │
│  │  │  ✅ Aprobado supervisor → 21/07/2026 09:30 por Carlos J.│    │
│  │  │  ⏳ Pend. aprob. RRHH → Actual                          │    │
│  │  └──────────────────────────────────────────────────────────┘    │
│  │                                                                  │
│  │  Acciones disponibles: [Btn: Aprobar] [Btn: Rechazar]           │
│  │                          [Btn: Cancelar proceso]                 │
│  └──────────────────────────────────────────────────────────────────┘
```

---

## 5. Pantalla: Tab Liquidación

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Tab: Solicitud] [Tab: Liquidación] [Tab: Activos] [Tab: Docs]      │
│ [Tab: Entrevista] [Tab: Pagos] [Tab: Legal] [Tab: Auditoría]        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  │ TAB: LIQUIDACIÓN                                                  │
│  │                                                                   │
│  │  ┌──────────────────────────────────────────────────────────┐     │
│  │  │  Cálculo de Prestaciones Laborales   Versión: v2         │     │
│  │  │                                        [⟳ Recalcular]    │     │
│  │  ├──────────────────────────────────────────────────────────┤     │
│  │  │  Antigüedad: 6 años, 4 meses, 15 días                    │     │
│  │  │  SDP: RD$ 2,727.65 (Salario Diario Promedio)             │     │
│  │  ├──────────────────────────────────────────────────────────┤     │
│  │  │  Concepto                        Días       Monto        │     │
│  │  │  ──────────────────────────────────────────────────────  │     │
│  │  │  Preaviso (Art. 76)              28     RD$ 76,374.20    │     │
│  │  │  Cesantía (Art. 80)              129    RD$ 351,866.85   │     │
│  │  │  Vacaciones (Art. 177/182)       14     RD$ 38,187.10    │     │
│  │  │  Salario de Navidad (Art. 219)   1/12   RD$ 5,416.67    │     │
│  │  │  Salario pendiente               15     RD$ 40,914.75    │     │
│  │  ├──────────────────────────────────────────────────────────┤     │
│  │  │  Subtotal prestaciones:               RD$ 428,241.05     │     │
│  │  │  Subtotal derechos adquiridos:        RD$ 84,518.52      │     │
│  │  │  ──────────────────────────────────────────────────────  │     │
│  │  │  Total Bruto:                          RD$ 512,759.57    │     │
│  │  │  Descuentos (préstamos):               RD$ (25,000.00)   │     │
│  │  │  ──────────────────────────────────────────────────────  │     │
│  │  │  Total Neto a Pagar:                   RD$ 487,759.57    │     │
│  │  ├──────────────────────────────────────────────────────────┤     │
│  │  │  Resumen Fiscal                                         │     │
│  │  │  Exento TSS:       RD$ 428,241.05 (Preaviso + Cesantía) │     │
│  │  │  Gravable TSS:     RD$ 84,518.52  (Vacaciones + Salario)│     │
│  │  │  Exento ISR:       RD$ 433,657.72                       │     │
│  │  │  Gravable ISR:     RD$ 79,101.88                        │     │
│  │  └──────────────────────────────────────────────────────────┘     │
│  │                                                                   │
│  │  Historial de versiones:                                          │
│  │  [v1 · 22/07/2026 · Calculado por Ana P.]                        │
│  │  [v2 · 23/07/2026 · Recalculado por Ana P. ← actual]            │
│  │                                                                   │
│  │  [Btn: Calcular]       [Btn: Aprobar liquidación]                │
│  │                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. Pantalla: Tab Activos (Checklist)

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Tab: Solicitud] [Tab: Liquidación] [Tab: Activos] [Tab: Docs]      │
│ [Tab: Entrevista] [Tab: Pagos] [Tab: Legal] [Tab: Auditoría]        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  │ TAB: ACTIVOS                                                      │
│  │                                                                   │
│  │  Checklist de Devolución de Activos                               │
│  │                                                                   │
│  │  Progreso: ████████░░░░░░░░ 8/12  (66%)                          │
│  │                                                                   │
│  │  ┌──────┬────────────────────────────────┬────────┬───────────┐  │
│  │  │ Estado│ Tarea                         │ Categor│ Incide     │  │
│  │  ├──────┼────────────────────────────────┼────────┼───────────┤  │
│  │  │ ✅   │ Devolver laptop (HP ProBook)   │ Activos│ —         │  │
│  │  │ ✅   │ Devolver teléfono (iPhone 14)  │ Activos│ —         │  │
│  │  │ ⬜   │ Devolver herramientas eléctricas│ Activos│ Pendiente │  │
│  │  │ ✅   │ Devolver carnet                │ RRHH   │ —         │  │
│  │  │ ✅   │ Devolver llaves ofi.          │ Acceso │ —         │  │
│  │  │ ⬜   │ Entregar credenciales sist.    │ Acceso│ Pendiente  │  │
│  │  │ 🔴   │ Uniformes (pérdida)            │ Uniform│ RD$3,500  │  │
│  │  │ ⬜   │ Firmar acta devolución         │ Docs   │ Pendiente  │  │
│  │  └──────┴────────────────────────────────┴────────┴───────────┘  │
│  │                                                                   │
│  │  [Btn: Marcar como devuelto]  [Btn: Reportar incidente]           │
│  │                                                                   │
│  │  ─────────────────────────────────────────────────────────────    │
│  │                                                                   │
│  │  Incidentes registrados:                                          │
│  │  ┌──────────────────────────────────────────────────────────┐    │
│  │  │ 🔴 Uniformes · Pérdida · RD$ 3,500                      │    │
│  │  │   [Btn: Generar cargo en liquidación]                    │    │
│  │  └──────────────────────────────────────────────────────────┘    │
│  │                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 7. Pantalla: Tab Documentos

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Tab: Solicitud] [Tab: Liquidación] [Tab: Activos] [Tab: Docs]      │
│ [Tab: Entrevista] [Tab: Pagos] [Tab: Legal] [Tab: Auditoría]        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  │ TAB: DOCUMENTOS                                                   │
│  │                                                                   │
│  │  [Btn: Generar todos los documentos pendientes]                   │
│  │                                                                   │
│  │  Documentos obligatorios para: Desahucio por el empleador         │
│  │                                                                   │
│  │  ┌──────┬──────────────────────────┬─────────┬────────┬───────┐  │
│  │  │ Estado│ Documento               │ Número  │ Generado│ Verif │  │
│  │  ├──────┼──────────────────────────┼─────────┼────────┼───────┤  │
│  │  │ ✅   │ Carta de desahucio       │ DES-0001│ 23/07   │ [🔍]  │  │
│  │  │ ✅   │ Acta de liquidación      │ LIQ-0001│ 23/07   │ [🔍]  │  │
│  │  │ ✅   │ Certificación laboral    │ CER-0001│ 23/07   │ [🔍]  │  │
│  │  │ ⬜   │ Recibo de pago           │ —       │ Pend.   │ —     │  │
│  │  │ ⬜   │ Acta devolución activos  │ —       │ Pend.   │ —     │  │
│  │  └──────┴──────────────────────────┴─────────┴────────┴───────┘  │
│  │                                                                   │
│  │  Vista previa del documento:                                      │
│  │  ┌──────────────────────────────────────────────────────────┐    │
│  │  │                                                        │    │
│  │  │  ╔══════════════════════════════════════════════════╗   │    │
│  │  │  ║       CARTA DE DESAHUCIO                        ║   │    │
│  │  │  ║       Código: DES-2026-00001                    ║   │    │
│  │  │  ║       Verificar en: verify.vykone.com/ABC123    ║   │    │
│  │  │  ╠══════════════════════════════════════════════════╣   │    │
│  │  │  ║  Por medio de la presente, notificamos...       ║   │    │
│  │  │  ║                                                  ║   │    │
│  │  │  ║  [QR CODE]                                      ║   │    │
│  │  │  ╚══════════════════════════════════════════════════╝   │    │
│  │  └──────────────────────────────────────────────────────────┘    │
│  │                                                                   │
│  │  [Btn: Descargar PDF]  [Btn: Firmar digitalmente]  [Btn: Enviar] │
│  │                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. Pantalla: Tab Entrevista de Salida

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Tab: Solicitud] [Tab: Liquidación] [Tab: Activos] [Tab: Docs]      │
│ [Tab: Entrevista] [Tab: Pagos] [Tab: Legal] [Tab: Auditoría]        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  │ TAB: ENTREVISTA DE SALIDA                                         │
│  │                                                                   │
│  │  ┌──────────────────────────────────────────────────────────┐    │
│  │  │  Entrevistador: Ana P. (RRHH)                            │    │
│  │  │  Fecha: 24/07/2026                                       │    │
│  │  ├──────────────────────────────────────────────────────────┤    │
│  │  │  Razón principal declarada:                              │    │
│  │  │  "Oportunidad laboral en otra empresa"                   │    │
│  │  │                                                          │    │
│  │  │  Razones secundarias:                                    │    │
│  │  │  • Mejor salario                                         │    │
│  │  │  • Crecimiento profesional                               │    │
│  │  │  • Horario flexible                                      │    │
│  │  ├──────────────────────────────────────────────────────────┤    │
│  │  │  Satisfacción (1-5):                                     │    │
│  │  │  Ambiente laboral:     ★★★★☆  4/5                       │    │
│  │  │  Compensación:         ★★★☆☆  3/5                       │    │
│  │  │  Gestión:              ★★★★☆  4/5                       │    │
│  │  │  Crecimiento:          ★★★☆☆  3/5                       │    │
│  │  │  Balance vida/trabajo: ★★★★★  5/5                       │    │
│  │  ├──────────────────────────────────────────────────────────┤    │
│  │  │  ¿Recomendaría la empresa?  ✅ Sí                        │    │
│  │  │  ¿Regresaría?              ✅ Sí, en el futuro          │    │
│  │  ├──────────────────────────────────────────────────────────┤    │
│  │  │  ¿Qué mejorar?                                           │    │
│  │  │  "Los salarios están por debajo del mercado para perfiles│    │
│  │  │   técnicos. Sugiero revisar la escala salarial."         │    │
│  │  └──────────────────────────────────────────────────────────┘    │
│  │                                                                   │
│  │  [Btn: Editar entrevista]   [Btn: Descargar resumen PDF]         │
│  │                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 9. Pantalla: Tab Pagos

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Tab: Solicitud] [Tab: Liquidación] [Tab: Activos] [Tab: Docs]      │
│ [Tab: Entrevista] [Tab: Pagos] [Tab: Legal] [Tab: Auditoría]        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  │ TAB: PAGOS                                                        │
│  │                                                                   │
│  │  Total liquidación: RD$ 487,759.57 (neto)                        │
│  │  Estado: [Badge: 💰 Pendiente de pago]                           │
│  │                                                                   │
│  │  ┌──────────────────────────────────────────────────────────┐    │
│  │  │  Registrar Pago                                           │    │
│  │  │                                                          │    │
│  │  │  Método de pago: [Select: Nómina de liquidación ▼]      │    │
│  │  │                            ├─ Nómina de liquidación      │    │
│  │  │                            ├─ Transferencia bancaria     │    │
│  │  │                            ├─ Cheque                     │    │
│  │  │                            ├─ Efectivo                   │    │
│  │  │                            └─ Mixto                      │    │
│  │  │                                                          │    │
│  │  │  Período de nómina: [Select: Jul 2026-2 ▼]              │    │
│  │  │  Fecha de pago:     [Date: ██/██/████]                  │    │
│  │  │  Referencia:        [Input: Número de referencia...]    │    │
│  │  │                                                          │    │
│  │  │  [Btn: Registrar pago]                                   │    │
│  │  └──────────────────────────────────────────────────────────┘    │
│  │                                                                   │
│  │  Historial de pagos:                                              │
│  │  (Sin pagos registrados)                                          │
│  │                                                                   │
│  │  Conciliación:                                                    │
│  │  Monto aprobado: RD$ 487,759.57                                   │
│  │  Monto pagado:   RD$ 0.00                                        │
│  │  Diferencia:     RD$ 487,759.57                                   │
│  │                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 10. Pantalla: Tab Legal / Riesgo

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Tab: Solicitud] [Tab: Liquidación] [Tab: Activos] [Tab: Docs]      │
│ [Tab: Entrevista] [Tab: Pagos] [Tab: Legal] [Tab: Auditoría]        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  │ TAB: LEGAL                                                        │
│  │                                                                   │
│  │  ┌──────────────────────────────────────────────────────────┐    │
│  │  │  Evaluación de Riesgo Legal                               │    │
│  │  │                                                          │    │
│  │  │  [🟡 RIESGO ALTO · 55/100]                               │    │
│  │  │                                                          │    │
│  │  │  Factores detectados:                                    │    │
│  │  │  +15 Antigüedad > 5 años (6 años, 4 meses)              │    │
│  │  │  +10 Sin amonestaciones registradas                      │    │
│  │  │  +20 Despido sin pruebas documentadas                    │    │
│  │  │  +10 Salario > 2× salario mínimo                        │    │
│  │  │  ─────────────────────────────────────                   │    │
│  │  │  Total: 55 pts                                          │    │
│  │  │                                                          │    │
│  │  │  Acciones recomendadas:                                  │    │
│  │  │  ✅ Revisión legal completada por Dr. Héctor M.         │    │
│  │  │  ⬜ Documentar evidencias de la falta                    │    │
│  │  │  ⬜ Obtener carta firmada                                │    │
│  │  └──────────────────────────────────────────────────────────┘    │
│  │                                                                   │
│  │  ┌──────────────────────────────────────────────────────────┐    │
│  │  │  Expediente Legal                                         │    │
│  │  │                                                          │    │
│  │  │  ¿Hay litigio o demanda?  [Select: No ▼]                │    │
│  │  │                                                          │    │
│  │  │  Acciones disciplinarias asociadas:                     │    │
│  │  │  (No hay acciones disciplinarias registradas)            │    │
│  │  │                                                          │    │
│  │  │  Evidencias cargadas:                                   │    │
│  │  │  📄 acta_reunion_departamento.pdf  · 23/07 · Admin      │    │
│  │  │  📄 correo_notificacion_cambio.pdf · 20/07 · RRHH       │    │
│  │  │                                                          │    │
│  │  │  [Btn: Subir evidencia]                                  │    │
│  │  └──────────────────────────────────────────────────────────┘    │
│  │                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 11. Pantalla: Tab Auditoría

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Tab: Solicitud] [Tab: Liquidación] [Tab: Activos] [Tab: Docs]      │
│ [Tab: Entrevista] [Tab: Pagos] [Tab: Legal] [Tab: Auditoría]        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  │ TAB: AUDITORÍA                                                    │
│  │                                                                   │
│  │  [Btn: Exportar expediente completo (PDF)]                        │
│  │  [Btn: Exportar bitácora (CSV)]                                   │
│  │                                                                   │
│  │  ┌──────────────────────────────────────────────────────────┐    │
│  │  │  Bitácora de Cambios (29 registros)                       │    │
│  │  │                                                          │    │
│  │  │  Fecha           Usuario       Acción              Detalle│    │
│  │  │  ───────────────────────────────────────────────────────  │    │
│  │  │  20/07 14:30   María R.      Solicitud creada     Draft  │    │
│  │  │  20/07 14:31   Sistema       Transición           → Pending Sup.│
│  │  │  21/07 09:30   Carlos J.     Aprobación nivel 1   ✅     │    │
│  │  │  21/07 09:30   Sistema       Transición           → Pending HR │
│  │  │  22/07 10:00   Ana P.        Cálculo liquidación  v1    │    │
│  │  │  22/07 10:15   Ana P.        Modificación         v2    │    │
│  │  │  22/07 10:30   Sistema       Transición           → Assets│    │
│  │  │  23/07 09:00   Luis M.       Devolución activos   Laptop│    │
│  │  │  23/07 09:30   Luis M.       Reporte incidente    Unif. │    │
│  │  └──────────────────────────────────────────────────────────┘    │
│  │                                                                   │
│  │  ┌──────────────────────────────────────────────────────────┐    │
│  │  │  Versionado de Liquidación (2 versiones)                  │    │
│  │  │                                                          │    │
│  │  │  [v1] 22/07 10:00 · Calculado por Ana P.                │    │
│  │  │        Total: RD$ 495,000.00                              │    │
│  │  │  [v2] 22/07 10:15 · Recalculado por Ana P. ← actual     │    │
│  │  │        Total: RD$ 487,759.57 ← Cambio: -RD$ 7,240.43    │    │
│  │  │        Motivo: Corrección en cálculo de vacaciones       │    │
│  │  │                                                          │    │
│  │  │  [Btn: Ver diff entre v1 y v2]                           │    │
│  │  └──────────────────────────────────────────────────────────┘    │
│  │                                                                   │
│  │  Cumplimiento SOX:                                                │
│  │  ✅ Segregación de funciones (SOD)                               │
│  │  ✅ Doble aprobación                                             │
│  │  ✅ Bitácora completa                                            │
│  │  ✅ Versionado                                                   │
│  │  ❌ Firma electrónica (pendiente)                                │
│  │                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 12. Pantalla: Dashboard de Offboarding

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Logo]  VykOne  │  RRHH  │  Nómina  │  Offboarding  │  [👤 Admin]  │
├─────────────────────────────────────────────────────────────────────┤
│  📊 Dashboard de Offboarding                                        │
│                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ 📋       │ │ ⏳       │ │ ✅       │ │ 💰       │               │
│  │ Activas  │ │ Pend.    │ │ Complet. │ │ Monto    │               │
│  │    12    │ │ Aprob. 5 │ │    156   │ │ $2.3M    │               │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘               │
│                                                                      │
│  Rotación de Personal (últimos 12 meses)                             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  📊 [Gráfico de barras: ingresos vs salidas por mes]        │   │
│  │                                                              │   │
│  │  En  | Feb | Mar | Abr | May | Jun | Jul | Ago | Sep |...   │   │
│  │  ██  ██   ███  ██   ███  ██   ███  ██   ██   ██             │   │
│  │  ██  ██   ██   ██   ██   ██   ██   ██   ██   ██             │   │
│  │  ──  ──   ──   ──   ──   ──   ──   ──   ──   ──             │   │
│  │  ██  ██   ██   ██   ██   ██   ██   ██   ██   ██             │   │
│  │  ██  ██   ██   ██   ██   ██   ██   ██   ██   ██             │   │
│  │  ↑ Ingresos  ↓ Salidas                                       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────┐ ┌──────────────────────────┐          │
│  │  Por Tipo de Salida      │ │  Por Riesgo Legal        │          │
│  │                          │ │                          │          │
│  │  Renuncia:       45%     │ │  🟢 Bajo:    60%        │          │
│  │  Desahucio:      20%     │ │  🟡 Medio:   25%        │          │
│  │  Despido:        15%     │ │  🟠 Alto:    10%        │          │
│  │  Mutuo acuerdo:  10%     │ │  🔴 Crítico:  5%        │          │
│  │  Otros:          10%     │ │                          │          │
│  └──────────────────────────┘ └──────────────────────────┘          │
│                                                                      │
│  Últimas Solicitudes Pendientes                                     │
│  ┌────────┬────────────┬──────────────┬──────────┬──────────┐       │
│  │ #      │ Empleado   │ Tipo         │ Estado   │ Tiempo   │       │
│  ├────────┼────────────┼──────────────┼──────────┼──────────┤       │
│  │OFF-005 │ Luis Pérez │ Despido just.│ ⏳ Pen.  │ 3 días   │       │
│  │OFF-006 │ Ana Gómez  │ Renuncia     │ 💰 Pen.  │ 5 días   │       │
│  │OFF-007 │ Carlos Ruiz│ Mutuo acuer. │ 📄 Pen.  │ 2 días   │       │
│  └────────┴────────────┴──────────────┴──────────┴──────────┘       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 13. Pantalla: Recontratación

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Logo]  VykOne  │  RRHH  │  Nómina  │  Offboarding  │  [👤 Admin]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  🔄 Recontratación de Empleado                                      │
│                                                                      │
│  Empleado a recontratar: [Input: Buscar por nombre o cédula...]     │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Empleado encontrado                                            │ │
│  │                                                                  │ │
│  │  Nombre:       Juan Pérez Martínez                              │ │
│  │  Cédula:       001-1234567-8                                    │ │
│  │  Último cargo: Analista de Sistemas                             │ │
│  │  Salida:       OFF-001 · 31/07/2026 · Desahucio empleador      │ │
│  │                                                                  │ │
│  │  ⚠️ Este empleado fue desvinculado hace 15 días.               │ │
│  │  ─────────────────────────────────────                           │ │
│  │  Historial preservado:                                          │ │
│  │  ✅ Evaluaciones: 3                                             │ │
│  │  ✅ Entrenamientos: 5                                           │ │
│  │  ✅ Historial salarial: 4 cambios                               │ │
│  │  ✅ Vacaciones previas: 15 días tomados                         │ │
│  │  ❌ Antigüedad previa: 6 años → Se reinicia?                   │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Nueva Contratación                                             │ │
│  │                                                                  │ │
│  │  Nuevo cargo:       [Input: Analista de Sistemas Senior]        │ │
│  │  Nuevo departamento:[Select: Tecnología ▼]                      │ │
│  │  Nuevo salario:     [Input: 85,000.00]                          │ │
│  │  Tipo de contrato:  [Select: Tiempo indefinido ▼]               │ │
│  │  Fecha de reingreso: [Date: 15/08/2026]                         │ │
│  │                                                                  │ │
│  │  [Checkbox] Preservar antigüedad (continúa desde 2020)          │ │
│  │  [Checkbox] Reiniciar beneficios (vacaciones desde cero)        │ │
│  │                                                                  │ │
│  │  ┌──────────────────────────────────────────────────────────┐   │ │
│  │  │  📋 Resumen                                              │   │ │
│  │  │  Antigüedad: 6 años (preservada) o 0 años (reiniciada)   │   │ │
│  │  │  Beneficios: Vacaciones reiniciadas                       │   │ │
│  │  │  Nuevo contrato: Tiempo indefinido · RD$ 85,000.00       │   │ │
│  │  └──────────────────────────────────────────────────────────┘   │ │
│  │                                                                  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  [Btn: Crear solicitud de recontratación]                            │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 14. Pantalla: Reporte Exportable

```
┌─────────────────────────────────────────────────────────────────────┐
│ [Logo]  VykOne  │  RRHH  │  Nómina  │  Offboarding  │  [👤 Admin]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  📄 Reporte de Offboarding                                           │
│                                                                      │
│  Período:  [Date: 01/01/2026]  →  [Date: 31/07/2026]                │
│                                                                      │
│  [Checkbox] Incluir todos los estados                               │
│  [Checkbox] Solo completados                                        │
│  [Checkbox] Solo con riesgo alto/crítico                            │
│                                                                      │
│  [Btn: Exportar a Excel]  [Btn: Exportar a CSV]  [Btn: Exportar     │
│                                                       PDF auditoría]│
│                                                                      │
│  ──────────────────────────────────────────────────────────────────  │
│                                                                      │
│  Vista previa del reporte (últimos 10):                              │
│                                                                      │
│  │ No. Solicitud │ Empleado    │ Tipo     │ Fecha    │ Monto       │ │
│  │ OFF-2026-001  │ Juan Pérez  │ Desahucio│ 20/07/26│ RD$487,759  │ │
│  │ OFF-2026-002  │ María Gómez │ Renuncia │ 18/07/26│ RD$124,500  │ │
│  │ OFF-2026-003  │ Pedro Díaz  │ Despido  │ 15/07/26│ RD$0 (sin)  │ │
│  │ OFF-2026-004  │ Ana Reyes   │ Mutuo    │ 14/07/26│ RD$98,200   │ │
│  │ OFF-2026-005  │ Luis Pérez  │ Despido  │ 10/07/26│ RD$312,800  │ │
│  │ ...           │ ...         │ ...      │ ...     │ ...         │ │
│                                                                      │
│  Total empleados desvinculados: 156                                 │
│  Total pagado en liquidaciones: RD$ 2,345,678.00                     │
│  Promedio por liquidación: RD$ 15,036.00                             │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 15. Flujo de Pantallas (User Journey)

```
                      ┌──────────────┐
                      │  Dashboard   │
                      │  Offboarding │
                      └──────┬───────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
     ┌────────────────┐          ┌──────────────────┐
     │ Lista de       │          │ Crear Solicitud   │
     │ Solicitudes    │          │ (Formulario)      │
     └────────┬───────┘          └────────┬─────────┘
              │                           │
              │                           ▼
              │                  ┌──────────────────┐
              │                  │ Detalle          │
              ├─────────────────►│ Solicitud        │
              │                  │ (Pestañas)       │
              │                  └────────┬─────────┘
              │                           │
              │              ┌────────────┼────────────┐
              │              │            │            │
              ▼              ▼            ▼            ▼
     ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
     │ Aprobación   │ │Liquidac.│ │ Activos  │ │Entrevista│
     │ (2 niveles)  │ │Cálculo  │ │Checklist │ │Formulario│
     └──────────────┘ └──────────┘ └──────────┘ └──────────┘
                                    │
                                    ▼
                             ┌──────────┐ ┌──────────┐ ┌──────────┐
                             │ Document.│ │  Pagos   │ │  Legal   │
                             │ Generación│ │ Registro │ │Expediente│
                             └──────────┘ └──────────┘ └──────────┘
                                    │
                                    ▼
                             ┌──────────────┐
                             │  Cerrado /   │
                             │  Completed   │
                             └──────────────┘
                                    │
                                    ▼
                             ┌──────────────┐
                             │ Recontratac. │
                             │ (posterior)  │
                             └──────────────┘
```

---

*Fin del documento de wireframes.*  
*Versión 1.0 — Julio 2026*
