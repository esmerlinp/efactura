# BP-6: Liquidación de Empleado (Ley 16-92)

## Overview

Calcula la liquidación laboral completa conforme al Código de Trabajo dominicano
(Ley 16-92) cuando un empleado es desvinculado. El cálculo distingue entre despido,
dimisión y renuncia para determinar qué conceptos aplican.

## Cause Types

| Causa | Liquidación pagable | Preaviso | Cesantía |
|-------|-------------------|----------|----------|
| `despido_justificado` | Días trabajados + vacaciones + regalía + salario navidad proporcional | NO | NO |
| `despido_injustificado` | Ídem + preaviso + cesantía + SDP (salarios dejados de percibir) | SÍ | SÍ |
| `dimision_justificada` | Ídem despido_injustificado | SÍ | SÍ |
| `renuncia_voluntaria` | Días trabajados + vacaciones + regalía + salario navidad | SÍ (descuento al empleado) | NO |

## Calculation Formula

```
Total = DíasPendientes × SalarioDiario
      + VacacionesPendientes × SalarioDiario
      + RegalíaPascual × (MesesTrabajados / 12)
      + SalarioNavidad × (MesesTrabajados / 12)
      + [if despido_injustificado or dimision]:
          + Preaviso × DíasSegúnAntigüedad × SalarioDiario
          + Cesantía × DíasSegúnAntigüedad × SalarioDiario
          + SDP (6 meses de salario, máx.)
```

## Antigüedad Scale (Código de Trabajo Art. 80-82)

| Antigüedad | Preaviso (días) | Cesantía (días) |
|------------|----------------|-----------------|
| 3-6 meses | 7 | 6 |
| 6-12 meses | 14 | 13 |
| 1-5 años | 14 | 21 × años |
| 5+ años | 28 | 23 × años |

## Tax Treatment

- **Cesantía**: Exenta de ISR (Art. 297 CT). No se retiene.
- **Preaviso**: Gravado. Se suma al ingreso del período para retención ISR.
- **Vacaciones**: Gravado.
- **Regalía Pascual**: Gravado aplicando Art. 296 exención proporcional.
- **SDP**: Gravado. Se retiene ISR.

## DGII Requirements

Debe emitirse una e-CF de tipo Egreso (03) al momento del pago efectivo.
La empresa debe retener ISR y reportar en el IR-17 (DC4).

## Events

- `EmployeeSettlementCalculated(entity_id, total, breakdown, cause)`
- Used by payroll processing to include settlement in the next payroll run
- Can trigger `EmployeeDeactivated` at controller level

## Related Files
- `app/services/liquidacion_service.py` — calculate_liquidacion()
- `app/models/pydantic/liquidacion.py` — LiquidacionRequest, LiquidacionResponse schemas
- `app/web/employees.py` — POST /employees/<id>/liquidacion
- `app/events/domain_events.py` — EmployeeSettlementCalculated
