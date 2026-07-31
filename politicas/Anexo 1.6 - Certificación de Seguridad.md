# ANEXO 1.6 — CERTIFICACIÓN DE SEGURIDAD

| Campo | Detalle |
|---|---|
| **Empresa Proveedora** | VykCore Automation S.R.L. |
| **Producto/Servicio** | VykOne ERP — Plataforma de Facturación Electrónica (e-CF) conforme DGII |
| **Código del documento** | POL-CER-006 |
| **Versión** | 1.0 |
| **Fecha de emisión** | 31 de julio de 2026 |
| **Clasificación** | Pública |
| **Responsable** | Esmerlin Paniagua Martinez — Gerente |

---

## 1. Objetivo

Declarar la situación del proveedor respecto a la posesión de certificaciones de seguridad de
la información (ej. ISO/IEC 27001 u otras) y las medidas compensatorias implementadas.

## 2. Certificación ISO/IEC 27001

A la fecha de emisión de este documento, **VykCore Automation S.R.L. no dispone de la
certificación ISO/IEC 27001** ni de otra certificación formal de seguridad de la información
emitida por un organismo certificador acreditado.

## 3. Medidas Compensatorias Implementadas

El proveedor mantiene implementados los siguientes controles de seguridad (detallados en el
**Anexo 1.1 — Política de Seguridad de la Información**):

- Autenticación robusta con **2FA/TOTP** y bloqueo de intentos fallidos.
- **Cifrado TLS/HSTS** en tránsito y cifrado de campos sensibles en reposo.
- **Firma digital XML** (XMLDSig RSA-SHA256) para los comprobantes e-CF.
- **Aislamiento multi-tenant** entre empresas y entre ambientes sandbox/producción.
- **Bitácora de eventos** con trazabilidad completa (Anexo 7).
- **Segregación de funciones (SoD)** y control de acceso basado en roles (RBAC).
- Cabeceras de seguridad, protección CSRF, validación de entradas y limitación de tasa.

## 4. Plan de Acción

El proveedor tiene en evaluación la implementación de un **Sistema de Gestión de Seguridad de
la Información (SGSI)** conforme a ISO/IEC 27001, con la meta de obtener la certificación en
un plazo futuro, y mantendrá actualizada esta información ante la DGII conforme a la
normativa vigente.

---

## 5. Control de Versiones

| Versión | Fecha | Descripción del cambio | Elaborado por | Aprobado por |
|---|---|---|---|---|
| 1.0 | 2026-07-31 | Emisión inicial para requerimiento DGII | Esmerlin Paniagua Martinez | Esmerlin Paniagua Martinez |

## 6. Aprobación y Firma

| | Nombre | Cargo | Firma | Fecha |
|---|---|---|---|---|
| Elaborado por | Esmerlin Paniagua Martinez | Gerente | ____________________ | 2026-07-31 |
| Aprobado por | Esmerlin Paniagua Martinez | Gerente | ____________________ | 2026-07-31 |
