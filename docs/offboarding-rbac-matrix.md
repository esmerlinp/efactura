# Offboarding RBAC Matrix v1.0

**Anexo técnico al Blueprint de Offboarding**  
**Audiencia:** RRHH, auditores, desarrolladores  
**Propósito:** Definir matriz de permisos por rol, reglas SOD y políticas de autorización

---

## 1. Roles del Sistema

| Código | Rol | Descripción |
|---|---|---|
| `supervisor` | Supervisor | Jefe directo del empleado. Puede solicitar desvinculaciones |
| `hr` | RRHH | Departamento de Recursos Humanos. Gestiona el proceso |
| `hr_manager` | Gerente RRHH | Aprueba desvinculaciones y liquidaciones de alto monto |
| `finance` | Finanzas | Aprueba montos de liquidación y ejecuta pagos |
| `it` | TI/Sistemas | Revoca accesos a sistemas |
| `legal` | Legal | Revisa casos de alto riesgo, gestiona litigios |
| `admin` | Administrador | Superusuario con todos los permisos |

---

## 2. Matriz de Permisos por Operación

### 2.1 Solicitud y Aprobación

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Crear solicitud de offboarding | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Ver solicitudes propias | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Ver todas las solicitudes | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Editar solicitud (draft) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Enviar a aprobación | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Aprobar nivel supervisor | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Aprobar nivel RRHH | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Rechazar solicitud | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Cancelar proceso | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Reactivar proceso cancelado | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |

### 2.2 Liquidación

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Calcular liquidación | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Ver cálculo de liquidación | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Editar parámetros de cálculo | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Aprobar liquidación (> X salarios) | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Aprobar liquidación (≤ X salarios) | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Versionar liquidación | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Recalcular liquidación | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |

### 2.3 Activos y Checklist

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Ver checklist de activos | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |
| Marcar ítem como devuelto | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Registrar incidente (pérdida/daño) | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Generar cargo por activo perdido | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Eximir devolución de activo | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Confirmar checklist completo | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |

### 2.4 Pago

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Ver detalle de pago | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Aprobar pago | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Ejecutar pago (vía nómina) | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| Ejecutar pago (transferencia) | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| Anular un pago | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

### 2.5 Documentos

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Generar documentos automáticos | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Firmar documentos digitalmente | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Reenviar documentos al empleado | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Subir documentos manuales | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Verificar código QR de documento | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Eliminar documento del expediente | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

### 2.6 Riesgo Legal

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Clasificar riesgo inicial | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Revisar riesgo (alta/medio) | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Revisar riesgo (crítico) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Asignar abogado al caso | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Cerrar caso legal | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |

### 2.7 TSS

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Generar datos para novedad TSS | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Marcar baja TSS como notificada | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Ver historial de novedades TSS | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |

### 2.8 Accesos

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Solicitar revocación de accesos | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Ejecutar revocación | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ |
| Verificar accesos revocados | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |

### 2.9 Recontratación

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Crear solicitud de recontratación | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Aprobar recontratación | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Ejecutar recontratación | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |

### 2.10 Auditoría

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Ver bitácora de cambios | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Ver versionado de liquidación | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Exportar expediente completo | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Ver dashboard de offboarding | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |

### 2.11 Configuración

| Operación | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Configurar tipos de terminación | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Configurar plantillas de documentos | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Configurar reglas de negocio | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Configurar roles y permisos | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Configurar SOD | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## 3. Reglas de Segregación de Funciones (SOD)

### 3.1 Reglas Obligatorias

| ID | Regla | Descripción | Violación |
|---|---|---|---|
| SOD-01 | Creador ≠ Aprobador RRHH | Quien crea la solicitud no puede ser quien la apruebe en nivel RRHH | Previene colusión en creación |
| SOD-02 | Calculador ≠ Validador liquidación | Quien calcula la liquidación no puede validarla/aprobarla | Previene errores no detectados |
| SOD-03 | Aprobador liquidación ≠ Pagador | Quien aprueba el monto no puede ejecutar el pago | Previene pagos no autorizados |
| SOD-04 | Verificador activos ≠ Devolvedor | Quien verifica la devolución no puede ser quien debía devolver | Previene colusión en activos |
| SOD-05 | Pagador ≠ Conciliador contable | Quien paga no puede crear el asiento contable | Previene fraudes contables |

### 3.2 Reglas Recomendadas

| ID | Regla | Descripción |
|---|---|---|
| SOD-06 | Aprobador supervisor ≠ Aprobador RRHH | Misma persona no puede aprobar en ambos niveles |
| SOD-07 | Calculador ≠ Pagador | Quien calcula no puede ejecutar el pago |
| SOD-08 | Aprobador ≠ Cancelador | Quien aprobó no puede cancelar el proceso (excepto admin) |

### 3.3 Implementación de SOD

```python
# Validación de SOD centralizada

class SODValidator:
    """Validador de segregación de funciones."""

    RULES = {
        "SOD-01": {
            "description": "Creador ≠ Aprobador RRHH",
            "check": lambda req, user: (
                req.status in ("pending_hr_approval",)
                and req.createdBy == user.email
            ),
            "error": "No puedes aprobar una solicitud que tú mismo creaste.",
        },
        "SOD-02": {
            "description": "Calculador ≠ Validador liquidación",
            "check": lambda req, settlement, user: (
                settlement is not None
                and settlement.calculatedBy == user.email
            ),
            "error": "No puedes validar una liquidación que tú mismo calculaste.",
        },
        "SOD-03": {
            "description": "Aprobador liquidación ≠ Pagador",
            "check": lambda req, settlement, user: (
                settlement is not None
                and settlement.approvedBy == user.email
            ),
            "error": "No puedes pagar una liquidación que tú mismo aprobaste.",
        },
        "SOD-04": {
            "description": "Verificador activos ≠ Empleado",
            "check": lambda req, user: (
                req.employeeId == user.employeeId
            ),
            "error": "Un empleado no puede verificar su propia devolución de activos.",
        },
    }

    @classmethod
    def validate(cls, rule_id: str, **kwargs) -> Optional[str]:
        """Valida una regla SOD. Retorna mensaje de error o None."""
        rule = cls.RULES.get(rule_id)
        if not rule:
            return None
        if rule["check"](**kwargs):
            return rule["error"]
        return None

    @classmethod
    def validate_all(cls, rules: list[str], **kwargs) -> list[str]:
        """Valida múltiples reglas. Retorna lista de errores."""
        errors = []
        for rule_id in rules:
            error = cls.validate(rule_id, **kwargs)
            if error:
                errors.append(f"[{rule_id}] {error}")
        return errors
```

---

## 4. Políticas de Autorización por Monto

### 4.1 Límites de Aprobación

| Monto liquidación | Aprueba |
|---|---|
| ≤ 5 salarios mínimos | RRHH |
| > 5 y ≤ 15 salarios mínimos | Gerente RRHH |
| > 15 salarios mínimos | Gerente RRHH + Finanzas (doble aprobación) |
| ≥ 30 salarios mínimos | Gerente RRHH + Finanzas + Dirección General |

### 4.2 Implementación

```python
SALARIO_MINIMO = 23223  # 2026 RD

LIMITES_APROBACION = {
    "settlement_approval": [
        {"max": 5 * SALARIO_MINIMO, "role": "hr"},
        {"max": 15 * SALARIO_MINIMO, "role": "hr_manager"},
        {"max": 30 * SALARIO_MINIMO, "role": "hr_manager+finance"},
        {"max": float("inf"), "role": "hr_manager+finance+direction"},
    ],
}
```

---

## 5. Políticas de Notificación por Rol

| Evento | Supervisor | RRHH | HR Mgr | Finance | TI | Legal | Admin |
|---|---|---|---|---|---|---|---|
| Solicitud creada | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Pendiente aprobación | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Solicitud aprobada | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Solicitud rechazada | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Liquidación calculada | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Activos devueltos | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Pago pendiente | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Pago ejecutado | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Riesgo alto/crítico | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Documentos generados | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Proceso completado | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Recontratación solicitada | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |

---

## 6. Resumen de Reglas de Autorización

| # | Regla | Nivel | Descripción |
|---|---|---|---|
| AUTH-01 | 4 ojos | Obligatorio | Toda desvinculación requiere al menos 2 personas distintas |
| AUTH-02 | Límite por monto | Obligatorio | Aprobación según escala de montos |
| AUTH-03 | Doble aprobación | Condicional | Si monto > 15 salarios mínimos |
| AUTH-04 | Revisión legal | Condicional | Si riesgo ≥ HIGH |
| AUTH-05 | Aprobación dirección | Condicional | Si riesgo = CRITICAL |
| AUTH-06 | No auto-aprobación | Obligatorio | SOD-01 a SOD-05 |

---

*Fin del documento de matriz RBAC.*  
*Versión 1.0 — Julio 2026*
