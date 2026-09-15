# Modulo de Planes de Seguro

## Regla de datos

`InsurancePlan` contiene la configuracion vigente para nuevas afiliaciones.
`InsuranceEnrollment` copia la tarifa, reglas, concepto y politica de prorrateo
al momento de crearse. Las transacciones de nomina consumen exclusivamente ese
snapshot y registran el importe aplicado.

## Reglas de costo

Cada parte puede ser `percentage`, `fixed_amount` o `remainder`. Solo una parte
puede ser `remainder` y empresa mas empleado debe completar la tarifa base.
Los calculos utilizan `Decimal` y redondeo `ROUND_HALF_UP` a dos decimales.

## Rutas iniciales

- `/rrhh/insurance/providers`
- `/rrhh/insurance/plans`
- `/rrhh/employees/<employee_id>/insurance`

La cancelacion cierra la vigencia y conserva el registro. Un cambio de plan debe
crear una nueva afiliacion en lugar de sobrescribir la anterior.
