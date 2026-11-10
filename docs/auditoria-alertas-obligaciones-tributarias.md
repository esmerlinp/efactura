# Auditoría integral — Módulo de Alertas y Obligaciones Tributarias de VykOne

**Fecha:** 10 de noviembre de 2026
**Alcance:** `app/services/tax_obligation_service.py`, `app/countries/do/tax_obligation_rules.py`
(nuevo), detección de régimen, catálogo de obligaciones, vencimientos, presets, auto-gate,
dedup de notificaciones, configuración de empresa y pruebas.

---

## 1. Resumen ejecutivo

Se auditó el motor de alertas/obligaciones tributarias y se contrastó contra la normativa y
el calendario oficial de la DGII y la TSS. El módulo anterior **colapsaba todas las modalidades
RST en un único preset `rst`**, omitía las declaraciones RS-1/RS-2/RS-3/RS-4, las cuotas
cuatrimestrales del RS-2 y el formato 609, y usaba plazos sin fuente normativa (TSS en día 10
cuando el pago es el 3er día laborable). Estas deficiencias provocaban alertas de régimen
ordinario en empresas RST y obligaciones exentas presentadas como pendientes.

Se corrigió todo lo anterior centralizando las reglas en un único módulo, diferenciando las
cuatro modalidades RST y sus formularios, corrigiendo plazos, separando TSS de DGT-3 y
agregando auto-gate por actividad. Se añadieron 52 pruebas unitarias que cubren regímenes,
modalidades, obligaciones y fechas límite.

---

## 2. Hallazgos (errores identificados)

| # | Hallazgo | Impacto |
|---|----------|---------|
| H1 | `detect_tax_profile` colapsaba `rst_income`/`rst_purchases`/`RST`/`Simplificado` en un solo `rst`. | Imposible distinguir RS-1/RS-2/RS-3/RS-4. |
| H2 | Sin `rst_agropecuario` en `dgii_client.py` ni en el selector de empresa. | Empresas agropecuarias clasificadas como RS-2. |
| H3 | Catálogo sin RS-1/RS-2/RS-3/RS-4, sin cuotas RST y sin formato 609. | Faltaban obligaciones obligatorias. |
| H4 | TSS en `monthly_10`; el pago TSS es el 3er día laborable (FAQ TSS #34). | Alerta con fecha errónea. |
| H5 | TSS y DGT-3 fusionadas en una sola obligación `tss`. | Imposible modelar periodicidad propia de DGT-3. |
| H6 | `ir3_ret` (anticipos) y `rst` (DJ genérica) con nombres/claves ambiguos. | Mantenimiento confuso y riesgo de migración. |
| H7 | `process_notifications` usaba `next_due_date[:7]` como `period_key`. | Dedup incorrecto para obligaciones anuales (clave debe ser el año). |
| H8 | Escalera RST duplicada en `dashboard.py` y `tax_rules.py`. | Divergencia de cálculo. |
| H9 | Anticipos ISR, ACT, IT-1, IR-2, 606/607/608/623 aparecían para RST. | Alertas de régimen ordinario en empresas RST. |
| H10 | Reglas de plazos hardcodeadas y dispersas. | Difícil mantener ante cambios normativos. |

---

## 3. Errores corregidos

- **H1/H2** — Nueva detección con prioridad: (1) modalidad explícita `rstModality`, (2) régimen
  configurado, (3) tipo de contribuyente / validación RNC, (4) compatibilidad modalidad↔formulario.
  Se añadió `rst_agropecuario` a `REGIMEN_CHOICES`, `REGIMEN_RULES`, `provider.py` y
  `DGIIService.is_rst_regimen`/`_normalize_lookup_regimen`.
- **H3** — Catálogo ampliado a 22 obligaciones: `rs1`, `rs2`, `rs3`, `rs4`,
  `rst_cuota_mar/jun/sep/dic`, `form_609`, `dgt3`.
- **H4/H5** — `tss` (pago) → `third_business_day_next_month`; `dgt3` (presentación) como
  obligación independiente (plazo pendiente de confirmación).
- **H6** — `ir3_ret` → `anticipos_isr`; `rst` → `rs2` con `LEGACY_KEY_ALIASES` para migración.
- **H7** — `process_notifications` ahora usa `period_key` calculado por `_get_period_key`.
- **H8** — `dashboard.py` usa `calc_rst_isr` de `tax_rules.py` (fuente única).
- **H9** — Presets por régimen excluyen IT-1, IR-2, anticipos, ACT y formatos 606/607/608/609/623
  para RST.
- **H10** — Reglas centralizadas en `app/countries/do/tax_obligation_rules.py`.

---

## 4. Reglas aplicadas y fuentes normativas

### 4.1 Catálogo de obligaciones (recurrencia → fuente)

| Obligación | Recurrencia | Fuente |
|------------|-------------|--------|
| Formato 606 / 607 | `monthly_15` (día 15) | Norma 08-04 y modif.; Calendario DGII |
| Formato 608 | `monthly_15` (día 15) | Norma 08-04 (pendiente de confirmación) |
| Formato 609 | `monthly_15` (día 15) | Norma 02-05 (pendiente de confirmación) |
| Formato 623 | `monthly_15` (día 15) | Norma 07-07 (pendiente de confirmación) |
| IT-1 | `monthly_20` (día 20) | Código Tributario Art. 353 |
| IR-17 | `monthly_10` (día 10) | Código Tributario Art. 310 |
| IR-3 | `monthly_10` (día 10) | Retenciones ISR salarios (SUIR/TSS; pendiente) |
| TSS (pago) | `third_business_day_next_month` | FAQ TSS #34 |
| DGT-3 | `third_business_day_next_month` | Presentación SUIR (pendiente) |
| Anticipos ISR | `monthly_15` (día 15) | Código Tributario Art. 314 |
| IR-2 | `annual_120days` | Código Tributario Art. 300 |
| IR-1 | `annual_90days` | Código Tributario Art. 300 |
| ACT | `annual_120days` | Ley 107-04 |
| RS-1/RS-2/RS-3/RS-4 | `last_business_day_february` | Decreto 265-19; Norma 04-22 |
| Cuotas RS-2 | `last_business_day_mar/jun/sep/dic` | Decreto 265-19 |

### 4.2 Régimen → obligaciones (matrix)

| Obligación | Ord. Jur. | Ord. Fís. | RS-1 | RS-2 | RS-3 | RS-4 | Exento |
|---|---|---|---|---|---|---|---|
| 606/607 | ✓ | ✓ | — | — | — | — | ✓ |
| 608/609/623 | opt. | opt. | — | — | — | — | opt. |
| IT-1 | ✓ | ✓ | — | — | — | — | — |
| IR-17 | ✓ | ✓ | cond. | cond. | cond. | cond. | ✓ |
| IR-3 | cond. | cond. | cond. | cond. | cond. | cond. | cond. |
| TSS | cond. | cond. | cond. | cond. | cond. | cond. | cond. |
| DGT-3 | cond. | cond. | cond. | cond. | cond. | cond. | cond. |
| Anticipos ISR | ✓ | ✓ | — | — | — | — | — |
| Cuotas RST | — | — | pend. | ✓ (4) | pend. | pend. | — |
| RS-1 | — | — | ✓ | — | — | — | — |
| RS-2 | — | — | — | ✓ | — | — | — |
| RS-3 | — | — | — | — | ✓ | — | — |
| RS-4 | — | — | — | — | — | ✓ | — |
| IR-2 | ✓ | — | — | — | — | — | ✓ |
| IR-1 | — | ✓ | — | — | — | — | — |
| ACT | ✓ | — | — | — | — | — | — |

*(cond. = auto-gate por actividad; opt. = disponible pero desactivada por defecto; pend. = pendiente de confirmación.)*

### 4.3 Auto-gate de obligaciones condicionales (independientes entre sí)

- **IR-17** — NO depende de empleados activos. Depende de operaciones sujetas a retención o
  retribuciones complementarias. No se suprime; se mantiene habilitada (no se marca exenta cuando
  no hay actividad en el período).
- **IR-3** — condicionada a empleados sujetos a retención salarial (auto-gate por empleados activos).
- **TSS** — condicionada a trabajadores registrados.
- **DGT-3** — condicionada a su propia condición de empleador y periodicidad de presentación.

Implementado en `TaxObligationService._has_active_employees` + `EMPLOYEE_CONDITIONS`
(`employees_with_salary_retention`, `registered_workers`, `employer`). Si no hay empleados
activos, IR-3/TSS/DGT-3 se suprimen como pendientes; IR-17 permanece.

---

## 5. Pendientes de confirmación (no verificables contra fuente en esta sesión)

1. **Cuotas RS-1** — frecuencia/plazos no confirmados (Instructivo RS-1 es PDF de imágenes).
2. **Cuotas RS-3** — frecuencia no confirmada (Instructivo RS-3).
3. **Cuotas RS-4** — frecuencia no confirmada (Instructivo RS-4).
4. **Plazo DGT-3** — provisional 3er día laborable; periodicidad pendiente de confirmación.
5. **Plazos exactos 608/609/623** — día 15 provisional; confirmar contra Calendario 2026.

Estos elementos se documentan en `PENDING_CONFIRMATIONS` y **no se emiten alertas** hasta
confirmarse (evita generar reglas equivocadas).

---

## 6. Resultados de pruebas

Ejecutado con `./venv/bin/python -m pytest`.

- `tests/test_tax_obligation_service.py`: **52 passed** (52 pruebas nuevas/actualizadas).
- Suite relacionada (tax_obligation, tax_engine, dgii, country_provider, withholding_options):
  **130 passed**.

Cobertura de las pruebas:
- Detección de los 8 regímenes y las 4 modalidades RST (RS-1/2/3/4) + prioridad de `rstModality`.
- Escenario RS-2: recibe RS-2 + 4 cuotas + condicionales; **no** recibe IT-1/IR-2/anticipos/ACT/606-609/623.
- Auto-gate: sin empleados se suprimen IR-3/TSS/DGT-3, IR-17 permanece.
- Vencimientos dinámicos: último día hábil (febrero/marzo), 3er día laborable (con feriados de enero),
  rollover de año, cierres fiscales.
- Dedup de notificaciones por `period_key` (anual = año).
- DGT-4 (idempotencia, traslado a día hábil), toggle-complete, migración `LEGACY_KEY_ALIASES`.

### Nota sobre la suite completa
La suite completa del repositorio presenta fallos preexistentes (270 fallos) ajenos a este
cambio, causados por la indisponibilidad de `google-cloud-firestore`/`grpc` en el entorno local
(`ImportError: cannot import name 'cygrpc'`). Ningún fallo corresponde al módulo tributario.

---

## 7. Revisión mensual recomendada

La normativa y el calendario DGII cambian con frecuencia. Se recomienda:
1. Revisar mensualmente el **Calendario del Contribuyente** de la DGII.
2. Confirmar los ítems de `PENDING_CONFIRMATIONS` (cuotas RS-1/3/4 y plazo DGT-3).
3. Actualizar `app/countries/do/tax_obligation_rules.py` como fuente única (sin tocar lógica).
