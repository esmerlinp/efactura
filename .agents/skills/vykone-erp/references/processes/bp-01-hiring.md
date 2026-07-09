# BP-1: Contratación de Personal (Hiring)

## Overview

Proceso end-to-end de registro de un nuevo empleado con todos los datos
requeridos para nómina DGII, TSS, y cumplimiento laboral dominicano.

## Flow

```
Registrar empleado → validar_documentos() → calcular_retenciones() → activar
  │
  ├─ Validar datos obligatorios:
  │   ├─ Cédula (formato RD: 000-0000000-0)
  │   ├─ Nombres y apellidos
  │   ├─ Fecha de ingreso
  │   ├─ Salario base mensual
  │   ├─ Cargo / Puesto
  │   ├─ Forma de pago (quincenal / mensual)
  │   └─ Tipo de contrato (indefinido / fijo / por obra)
  │
  ├─ Validar documentos DGII/TSS:
  │   ├─ Verificar RNC de la empresa empleadora esté activo en DGII
  │   ├─ Validar cédula no duplicada en el tenant
  │   └─ Validar formato correcto para reporte TSS
  │
  ├─ Configurar parámetros de nómina:
  │   ├─ AFP (Administradora de Fondos de Pensiones)
  │   │   └─ Default: AFP_Siembra (configurable)
  │   ├─ ARS (Seguro Familiar de Salud)
  │   │   └─ Default: ARS_SeNaSa (configurable)
  │   ├─ Salario mínimo sectorizado (según categoría DGII)
  │   └─ Aplica retención ISR (si salario > tramo exento)
  │
  ├─ Guardar en Firestore (colección employees/{owner_uid})
  │
  ├─ EventBus: EmployeeCreated(entity_id, datos_empleado)
  │   └─ Handlers:
  │       ├─ Crear cuenta de usuario (si aplica)
  │       ├─ Registrar en módulo TSS
  │       └─ Notificar a RRHH
  │
  └─ Retornar employee_id + resumen
```

## Validation Rules

| Campo | Validación |
|-------|-----------|
| `cedula` | Regex: `^\d{3}-\d{7}-\d{1}$` |
| `salario` | > salario_mínimo_sectorizado |
| `fecha_ingreso` | <= today, >= 18 años desde fecha_nacimiento |
| `email` | Único dentro del tenant |
| `tipo_contrato` | Enumerable: indefinido / fijo / obra |
| `forma_pago` | Enumerable: quincenal / mensual |

## TSS Registration

Al crear empleado, se requiere:
- AFP (empleador paga 7.10%, empleado paga 2.87% sobre salario cotizable)
- ARS (empleador paga 7.09%, empleado paga 3.04%)
- El salario cotizable tiene un tope de 20 salarios mínimos (ajustable)
- Datos del dependiente (cónyuge, hijos) para ARS

## ISR Projection

Al crear, se calcula la proyección de retención ISR mensual:
- Aplica tabla de retenciones DGII vigente (escala progresiva)
- Salario exento primer tramo (aprox RD$34,685 mensual / RD$416,220 anual)
- Se deduce AFP (2.87%) y ARS (3.04%) de la base imponible

## Events

- `EmployeeCreated(owner_uid, employee_id, nombre, cedula, salario, cargo)`

## Related Files
- `app/services/employee_service.py` — create_employee(), validate_employee_data()
- `app/services/tss_service.py` — registrar_empleado_tss()
- `app/models/pydantic/employee.py` — Employee, EmployeeCreate schemas
- `app/web/employees.py` — employee CRUD endpoints
- `app/events/domain_events.py` — EmployeeCreated
