# Informe de Auditoría TSS — SUIRPLUS v6.0

**Objetivo**: Archivo de Autodeterminación (AM/AR)
**Instructivo**: "Instructivo para Construcción de Archivos de Autodeterminación y Novedades – Versión 6.0 (25/06/2025)"
**Fecha del informe**: 21/07/2026
**Auditado**: `app/services/payroll_service.py` — `generate_tss_autodeterminacion()` y dependencias

---

## Clasificación de Hallazgos

| Clave | Descripción |
|-------|-------------|
| ❌ | No cumple |
| ⚠️ | Cumple parcialmente / requiere validación funcional |
| ✅ | Cumple |
| 🔍 | No auditado (requiere análisis adicional) |

---

## 1. Estructura Física del Archivo

### 1.1 Encabezado (Registro E)

| # | Regla | Estado | Evidencia | Nota |
|---|-------|--------|-----------|------|
| 1.1 | Tipo registro = E (pos 1) | ✅ | `payroll_service.py:1736` | |
| 1.2 | Proceso AM/AR (pos 2-3) | ❌ | `payroll_service.py:1736` | Hardcodeado "AM". No hay parámetro `tipo_archivo` en TXT. La versión XLS sí lo soporta. |
| 1.3 | RNC 11 chars (pos 4-14) | ✅ | `payroll_service.py:1726-1728, 1736` | Rjust con espacios para RNC < 11 dígitos |
| 1.4 | Período MMAAAA (pos 15-20) | ✅ | `payroll_service.py:1719` | |
| 1.5 | Longitud = 20 | ✅ | `payroll_service.py:1737` | Assert verificado |

### 1.2 Detalle (Registro D) — Posiciones y Longitudes

| # | Campo | Posición | Longitud | Estado | Código |
|---|-------|----------|----------|--------|--------|
| 2.1 | Tipo registro | 1 | 1 | ✅ `payroll_service.py:1844` |
| 2.2 | Clave nómina | 2-4 | 3 | ✅ `payroll_service.py:1752-1753` |
| 2.3 | Tipo documento | 5 | 1 | ✅ `payroll_service.py:1756-1757` | C/P/N |
| 2.4 | Documento | 6-30 | 25 | ✅ `payroll_service.py:1760-1761` | `isalnum()`, sin guiones |
| 2.5 | Nombres | 31-80 | 50 | ✅ `payroll_service.py:1764-1765` | ASCII upper |
| 2.6 | 1er apellido | 81-120 | 40 | ✅ `payroll_service.py:1768-1769` |
| 2.7 | 2do apellido | 121-160 | 40 | ✅ `payroll_service.py:1772-1773` |
| 2.8 | Sexo | 161 | 1 | ⚠️ `payroll_service.py:1777` | Default "F" si vacío. No valida. |
| 2.9 | Fecha nacimiento | 162-169 | 8 | ✅ `payroll_service.py:1780-1788` | Formato DDMMAAAA |
| 2.10 | Salario_SS | 170-185 | 16 | ✅ `payroll_service.py:1798` | Con tope AFP |
| 2.11 | Aporte voluntario | 186-201 | 16 | ✅ `payroll_service.py:1801` | Siempre 0 |
| 2.12 | Salario_ISR | 202-217 | 16 | ⚠️ `payroll_service.py:1804` | Ver sección 4 |
| 2.13 | Otras rem. ISR | 218-233 | 16 | ✅ `payroll_service.py:1807` | |
| 2.14 | Agente retención | 234-244 | 11 | ✅ `payroll_service.py:1810` | |
| 2.15 | Otros empleadores | 245-260 | 16 | ⚠️ `payroll_service.py:1813` | Siempre 0 — no hay integración multi-empleador |
| 2.16 | Ingresos exentos ISR | 261-276 | 16 | ✅ `payroll_service.py:1816` | Envía 0000000000000.00 |
| 2.17 | Saldo a favor | 277-292 | 16 | ✅ `payroll_service.py:1819` | |
| 2.18 | Salario INFOTEP | 293-308 | 16 | ⚠️ `payroll_service.py:1822` | Ver sección 4 |
| 2.19 | Tipo ingreso | 309-312 | 4 | ❌ `payroll_service.py:1825` | **Siempre 0001** |
| 2.20 | Regalía Pascual | 313-330 | 18 | ✅ `payroll_service.py:1829-1830` | Formato 01+monto |
| 2.21 | Preaviso/Cesantía | 331-348 | 18 | ⚠️ `payroll_service.py:1833-1834` | Formato OK, pero siempre 0 |
| 2.22 | Pensión alimenticia | 349-366 | 18 | ⚠️ `payroll_service.py:1837-1838` | Formato OK, pero `pensionAlimenticia` no existe en PayrollLine → siempre 0 |

### 1.3 Sumario (Registro S)

| # | Regla | Estado | Evidencia |
|---|-------|--------|-----------|
| 3.1 | Tipo = S (pos 1) | ✅ | `payroll_service.py:1858` |
| 3.2 | Total registros (pos 2-7) | ✅ | `payroll_service.py:1857` | E + D's + S |
| 3.3 | Longitud = 7 | ✅ | `payroll_service.py:1858` | `S{total:06d}` |

### 1.4 Formato de Montos

| # | Regla | Estado | Evidencia |
|---|-------|--------|-----------|
| 4.1 | 16 posiciones | ✅ | `f"{value:016.2f}"[:16]` |
| 4.2 | 2 decimales | ✅ | |
| 4.3 | Ceros izquierda | ✅ | |
| 4.4 | Sin separadores | ✅ | |
| 4.5 | Sin espacios | ✅ | |

---

## 2. Hallazgos

### ❌ HC-01: Tipo Ingreso hardcodeado en 0001

**Archivo**: `payroll_service.py:1825`
**Código**: `tipo_ingreso = "0001"`

El instructivo define 8 valores (0001–0008):
| 0001 | Normal |
| 0002 | Ocasional |
| 0003 | Tiempo parcial |
| 0004 | No laboró mes completo |
| 0005 | Salario prorrateado |
| 0006 | Pensionado antes Ley 87-01 |
| 0007 | Exento SDSS |
| 0008 | Salario sectorizado |

**Riesgo**: Empleados de medio tiempo (0003), con prórrata (0005), pensionados (0006) son reportados como "Normal" (0001). Posible rechazo por validación SUIRPLUS.

**Evidencia directa**: El layout v6.0 especifica estos 8 códigos. El sistema no implementa lógica de selección.

---

### ❌ HC-02: Sin soporte AR (Autodeterminación Retroactiva) en TXT

**Archivo**: `payroll_service.py:1736`
**Código**: `header = f"EAM{...}"`

El instructivo define dos procesos:
- **AM** = Autodeterminación Mensual
- **AR** = Autodeterminación Retroactiva

La versión TXT siempre genera "AM". La versión XLS acepta `tipo_archivo` pero la TXT no. La ruta web no expone el parámetro.

**Riesgo**: Imposibilidad de reportar retroactivos en formato TXT oficial.

---

### ❌ HC-03: Proporcionalidad salarial no aplicada en TSS

**Archivo**: `concept_engine.py:298-300` → `payroll_service.py:1793`

**Problema crítico**: El instructivo establece que *"Los salarios reportados deben corresponder exactamente a lo devengado en el período reportado"*, especificando que ingresos y salidas a mitad de mes deben usar salario proporcional.

**Flujo actual**:

1. `payroll_process.py:291` llama `prorate_salary()` y calcula el salario prorrateado correctamente
2. `payroll_process.py:304` pasa `"proratedSalary": prorated` al `ConceptEngine.evaluate()`
3. `concept_engine.py:298-300` **ignora `proratedSalary`** y usa `baseSalary` para la transacción `SALARIO_BASE`:
   ```python
   amount = context.get("baseSalary", 0)  # ← usa base, no proratedSalary
   ```
4. El `totalIncome` de la línea de nómina es la suma de transacciones tipo earning, que incluye el salario base **sin prorratear**
5. `generate_tss_autodeterminacion()` usa ese `totalIncome` sin prorratear como `Salario_SS`

**Consecuencia**: Un empleado que entra el 15 del mes reporta el salario mensual completo en TSS, cuando debería reportar solo la mitad proporcional.

**Riesgo**: Rechazo por validación SUIRPLUS. Inconsistencia con lo reportado vs. lo realmente devengado.

---

### ⚠️ HF-01: Preaviso/Cesantía siempre en cero

**Archivo**: `payroll_service.py:1833-1834`

El layout contempla el campo 02 para Preaviso, Cesantía, Viáticos e Indemnizaciones. Si el ERP procesa liquidaciones laborales, estos montos deberían reflejarse aquí. Actualmente se envía `0200000000000000.00` siempre.

**Riesgo**: Omisión de ingresos exentos en el archivo TSS.

---

### ⚠️ HF-02: Pensión alimenticia siempre en cero

**Archivo**: `payroll_service.py:1837`

El layout contempla el campo 03 para Retención de Pensión Alimenticia. El sistema maneja embargos por pensión (`Garnishment.garnishmentType == "pension_alimenticia"`) pero el TSS busca `pl.get("pensionAlimenticia", 0)`, campo que no existe en `PayrollLine`.

**Riesgo**: Las retenciones por pensión alimenticia nunca se reportan a TSS.

---

### ⚠️ HF-03: Salario_ISR — posible incumplimiento normativo (requiere validación funcional)

**Archivo**: `payroll_service.py:1804`
**Código**: `salario_isr_str = salario_ss_str`

El instructivo dice: *"DEBE REPORTARLO SOLO SI ES DIFERENTE DEL SALARIO_SS"*. No dice explícitamente "enviar cero cuando sean iguales", pero la interpretación más segura es que debe enviarse `0000000000000.00` cuando no hay diferencia.

**Riesgo**: Posible rechazo si SUIRPLUS valida que Salario_ISR ≠ Salario_SS.

**Recomendación**: Validar con TSS/SUIRPLUS el comportamiento esperado antes de considerar esto como incumplimiento confirmado. Implementar lógica condicional.

---

### ⚠️ HF-04: Salario INFOTEP — posible incumplimiento normativo (requiere validación funcional)

**Archivo**: `payroll_service.py:1822`
**Código**: `salario_infotep_str = salario_ss_str`

Misma situación que HF-03. El instructivo dice reportarlo solo si es diferente de Salario_SS. No especifica el comportamiento cuando son iguales.

**Riesgo**: Ídem HF-03.

---

### ⚠️ HF-05: Extranjeros (tipo P) — campos no validados

**Archivo**: `payroll_service.py:1764-1788`

La regla del instructivo exige que cuando el tipo de documento es "P" (pasaporte), los campos Nombres, 1er Apellido, 2do Apellido, Sexo y Fecha Nacimiento sean **obligatorios**. El código actual envía estos campos siempre (rellenados con espacios si están vacíos), pero **no valida que estén poblados**.

**Riesgo**: Extranjeros registrados sin nombres completos generarían registros con campos vacíos, potencialmente rechazados.

---

### ⚠️ HF-06: `_split_name` no utilizado en generación TSS

**Archivo**: `payroll_service.py:1764-1773` vs `payroll_service.py:2134-2158`

El método `_split_name` contiene lógica de fallback para empleados que solo tienen `fullName` (sin nombres/apellidos desglosados). Sin embargo, `generate_tss_autodeterminacion()` accede directamente a `firstName`, `middleName`, etc. sin usar el fallback.

**Riesgo**: Empleados importados sin datos desglosados generarían nombres/apellidos vacíos en el archivo TSS.

---

### ⚠️ HF-07: Gender default "F" sin validación

**Archivo**: `payroll_service.py:1777`

```python
sexo = "M" if gender in ("masculino", "male", "m") else "F"
```

Si `gender` está vacío o es un valor inesperado, se envía "F". Esto puede causar inconsistencias.

---

### ✅ Hallazgos que cumplen

| # | Aspecto | Estado |
|---|---------|--------|
| 5.1 | Encabezado tipo E | ✅ |
| 5.2 | Período MMAAAA | ✅ |
| 5.3 | RNC en encabezado | ✅ |
| 5.4 | Longitud encabezado = 20 | ✅ |
| 5.5 | Tipo doc (C/P/N) | ✅ |
| 5.6 | Documento sin guiones | ✅ |
| 5.7 | Nombres en ASCII uppercase | ✅ |
| 5.8 | Apellidos en ASCII uppercase | ✅ |
| 5.9 | Fecha nacimiento DDMMAAAA | ✅ |
| 5.10 | Salario_SS con tope AFP | ✅ |
| 5.11 | Formato montos 16 chars, 2 decimales, ceros izq | ✅ |
| 5.12 | Longitud detalle = 366 | ✅ |
| 5.13 | Sumario con conteo correcto | ✅ |
| 5.14 | Regalía Pascual formateada como 01+monto | ✅ |

---

## 3. Matriz de Cumplimiento Detallada

| Regla Instructivo v6.0 | Estado | Evidencia |
|------------------------|--------|-----------|
| Ejecutar SUIRPLUS para validación técnica | 🔍 | No ejecutado |
| Encabezado: tipo E | ✅ | |
| Proceso: AM para mensual | ✅ | |
| Proceso: AR para retroactivo | ❌ | Hardcodeado AM |
| RNC/Cédula empleador | ✅ | |
| Período MMAAAA | ✅ | |
| Longitud encabezado = 20 | ✅ | |
| Detalle: tipo D | ✅ | |
| Clave nómina (3) | ✅ | |
| Tipo doc (1): C/N/P | ✅ | |
| Documento (25): sin guiones | ✅ | |
| Nombres (50): obligatorio si tipo P | ⚠️ | No se valida contenido |
| 1er Apellido (40): obligatorio si tipo P | ⚠️ | No se valida contenido |
| 2do Apellido (40): obligatorio si tipo P | ⚠️ | No se valida contenido |
| Sexo (1): obligatorio si tipo P | ⚠️ | No se valida contenido |
| Fecha nac. (8): obligatorio si tipo P | ⚠️ | No se valida contenido |
| Salario_SS (16): devengado en período | ❌ | No se usa salario prorrateado |
| Salario_SS (16): formato 9999999999999.99 | ✅ | |
| Aporte voluntario (16) | ✅ | Siempre 0 |
| Salario_ISR (16): solo si difiere de SS | ⚠️ | Pendiente validación con TSS |
| Otras rem. ISR (16) | ✅ | Siempre 0 |
| Agente retención (11) | ✅ | |
| Rem. otros empleadores (16) | ⚠️ | Siempre 0 |
| Ingresos exentos ISR (16): 000...00 | ✅ | |
| Saldo a favor (16) | ✅ | Siempre 0 |
| Salario INFOTEP (16): solo si difiere de SS | ⚠️ | Pendiente validación con TSS |
| Tipo ingreso (4): 0001–0008 | ❌ | Siempre 0001 |
| Regalía Pascual (18): 01+monto | ✅ | |
| Preaviso/Cesantía (18): 02+monto | ⚠️ | Formato OK, siempre 0 |
| Pensión alimenticia (18): 03+monto | ⚠️ | Formato OK, siempre 0 |
| Longitud detalle = 366 | ✅ | |
| Sumario: tipo S | ✅ | |
| Sumario: total registros = E + D + S | ✅ | |
| Sumario: longitud = 7 | ✅ | |
| Salario proporcional: ingresos mitad de mes | ❌ | ConceptEngine ignora proratedSalary |
| Salario proporcional: salidas mitad de mes | ❌ | ConceptEngine ignora proratedSalary |
| Salario proporcional: vacaciones | 🔍 | No auditado |
| Salario proporcional: licencias | 🔍 | No auditado |

---

## 4. Veredicto Final

### No cumple parcialmente — **~78% estimado**

### Resumen de incumplimientos confirmados:

| # | Hallazgo | Tipo | Impacto |
|---|----------|------|---------|
| HC-01 | Tipo Ingreso hardcodeado 0001 | ❌ Normativo | Rechazo potencial |
| HC-02 | Sin soporte AR en TXT | ❌ Funcional | Brecha operativa |
| HC-03 | Proporcionalidad salarial ignorada | ❌ Normativo | Rechazo potencial |

### Pendientes de validación con TSS/SUIRPLUS:

| # | Hallazgo | Tipo |
|---|----------|------|
| HF-03 | Salario_ISR = Salario_SS | ⚠️ Normativo |
| HF-04 | Salario INFOTEP = Salario_SS | ⚠️ Normativo |

### Cumplimiento parcial:

| # | Hallazgo | Tipo |
|---|----------|------|
| HF-01 | Preaviso/Cesantía siempre 0 | ⚠️ Funcional |
| HF-02 | Pensión alimenticia siempre 0 | ⚠️ Funcional |
| HF-05 | Extranjeros sin validación de campos | ⚠️ Técnico |
| HF-06 | `_split_name` no utilizado | ⚠️ Técnico |
| HF-07 | Gender default "F" | ⚠️ Técnico |

### Porcentaje por categoría:

| Categoría | % Cumplimiento |
|-----------|---------------|
| Estructura física (posiciones, longitudes) | 100% |
| Formato de montos | 100% |
| Encabezado y sumario | 100% |
| Soporte AM | 100% |
| Soporte AR | 0% |
| Tipo Ingreso dinámico | 0% |
| Proporcionalidad salarial | 0% |
| Ingresos exentos desglosados (01/02/03) | 60% (formato OK, valores 0) |
| Salario_ISR / INFOTEP condicional | 50% (pendiente validación) |
| Validación extranjeros | 50% (campos existen, no validados) |
| **Global ponderado** | **~78%** |

---

## 5. Recomendaciones por Prioridad

### Inmediatas (antes de producir archivos para TSS)

1. **HC-03**: Corregir `ConceptEngine.evaluate()` para usar `proratedSalary` en `SALARIO_BASE` cuando esté disponible
2. **HC-01**: Implementar lógica de selección de Tipo Ingreso basada en datos del empleado
3. **HC-02**: Agregar parámetro `tipo_archivo` a `generate_tss_autodeterminacion()` y exponerlo en la ruta web

### Corto Plazo

4. **HF-01**: Extraer preaviso/cesantía de liquidaciones del período y poblarlos en el campo 02
5. **HF-02**: Integrar `GarnishmentService` para detectar embargos por pensión alimenticia
6. **HF-05**: Agregar validación pre-generación que verifique campos obligatorios para tipo P

### Mediano Plazo

7. **HF-03/HF-04**: Confirmar con TSS si Salario_ISR/INFOTEP deben enviarse en cero cuando son iguales a Salario_SS, y ajustar
8. **HF-06**: Usar `_split_name()` como fallback en la generación TSS
9. **HF-07**: Validar gender antes de enviar; no usar "F" como default
10. Agregar casos de prueba específicos para: proporcionalidad, extranjeros, retroactivos, liquidaciones

---

## 6. Notas sobre el Alcance de la Auditoría

### Aspectos NO auditados que requieren revisión independiente:

- Validación SUIRPLUS real (ejecutar archivo generado contra la plataforma)
- Manejo de vacaciones y licencias en el contexto de proporcionalidad salarial
- Cálculo de ISR en la línea de nómina vs. lo reportado en TSS
- Integridad de datos entre Employee → PayrollLine → TSS (consistencia cross-system)
- Archivos de Novedades (formato N, si aplica)
- Archivo de Dependientes (RD) — formato v5.0, no v6.0
