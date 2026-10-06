# API de Integración para Desarrolladores — VykOne ERP

> Documento técnico · `COM-API-001` · v1.0 · 6 de octubre de 2026
>
> VykCore Automation S.R.L. · support@vykcore.com · 809-866-8227

Conecta tu sistema ERP, tienda en línea o aplicación móvil con VykOne para emitir
comprobantes fiscales electrónicos (e-CF) válidos ante la DGII, consultar RNCs de
clientes, anular facturas y sincronizar catálogos.

---

## 1. Requisitos previos

Para consumir la API necesitas:

- **Una cuenta VykOne activa** con una empresa configurada.
- **Tu API Key**, generada desde el panel de **Configuración de Empresa**.
- Acceso a internet hacia la URL base `https://sandbox.one.vykcore.com`.

## 2. Autenticación

Todas las solicitudes deben incluir la cabecera `X-API-Key` con la clave única de
tu empresa. Sin esta cabecera, la API responde `401 Unauthorized`.

### Cabeceras globales

| Cabecera | Tipo | Requerido | Descripción |
| :--- | :--- | :--- | :--- |
| `X-API-Key` | String | Sí | Clave de API única de tu empresa. |
| `X-Sandbox-Mode` | String | No | `"true"` (por defecto) para pruebas en sandbox o `"false"` para producción. |
| `Content-Type` | String | Sí | Debe ser `application/json`. |
| `Idempotency-Key` | String | No | Clave opcional para evitar emisiones duplicadas (solo en `/invoices/emit`). |

> **Sandbox vs. producción**
> En modo sandbox (`X-Sandbox-Mode: true`) las facturas se emiten en un entorno de
> pruebas y no afectan tus secuencias fiscales reales. Usa sandbox durante el
> desarrollo y cambia a `false` solo cuando tu integración esté validada.

## 3. Convenciones

- **URL base:** `https://sandbox.one.vykcore.com`.
- **Formato:** JSON en peticiones y respuestas. Las fechas usan `YYYY-MM-DD`.
- **Codificación:** UTF-8.
- **Errores:** toda respuesta de error incluye `{"success": false, "error": "..."}`.

### Códigos de estado HTTP

| Código | Significado |
| :--- | :--- |
| `200` | Operación exitosa. |
| `400` | Payload inválido o faltan campos requeridos. |
| `401` | API Key ausente o inválida. |
| `404` | Recurso no encontrado (factura, cliente, etc.). |
| `422` | El proveedor de facturación rechazó el comprobante. |
| `500` | Error interno del servidor. |

---

## 4. Facturación Electrónica (e-CF)

### `POST /api/v1/invoices/emit`

Recibe los datos de la factura, calcula los impuestos (ITBIS, ISC, retenciones),
consume el siguiente consecutivo fiscal, firma digitalmente el XML y lo envía a la DGII.

#### Payload de ejemplo

```json
{
  "client_id": "cli_9812739",
  "client_rnc": "132109122",
  "client_name": "Cliente de Ejemplo SRL",
  "ecf_type": "Factura de Crédito Fiscal (E31)",
  "payment_method": "Crédito",
  "due_date": "2026-06-30",
  "currency": "DOP",
  "discount_rate": 0.0,
  "retained_isr_rate": 0.0,
  "retained_itbis_rate": 0.0,
  "income_type": "01 - Ingresos por operaciones",
  "items": [
    {
      "id": "prod_1",
      "name": "Servicio de Consultoría de Software",
      "price": 10000.00,
      "quantity": 1.0,
      "unit": "Servicio",
      "itbis_rate": 0.18
    }
  ]
}
```

#### Respuesta de éxito (`200 OK`)

```json
{
  "success": true,
  "message": "Factura Electrónica e-CF emitida exitosamente.",
  "invoice_id": "c62fb91d-e5ba-4ea2-877e-1d00d68757b7",
  "encf": "E310000000001",
  "track_id": "track_abc123xyz",
  "xmlSignature": "…",
  "qrCodeURL": "https://…",
  "pdfUrl": "https://…",
  "xmlUrl": "https://…",
  "total": 11300.00
}
```

#### Campos principales del payload

| Campo | Tipo | Req. | Descripción |
| :--- | :--- | :--- | :--- |
| `items` | Array | Sí | Lista de artículos del documento (mínimo uno). |
| `client_rnc` | String | No | RNC o cédula del cliente (obligatorio en E31). |
| `client_name` | String | No | Razón social del cliente. |
| `ecf_type` | String | No | Tipo de comprobante (por defecto E32). |
| `payment_method` | String | No | Método de pago (Efectivo, Crédito, etc.). |
| `due_date` | String | No | Fecha de vencimiento (`YYYY-MM-DD`). |
| `discount_rate` | Number | No | Tasa de descuento global (ej. `0.05`). |
| `retained_isr_rate` | Number | No | Tasa de retención de ISR. |
| `retained_itbis_rate` | Number | No | Tasa de retención de ITBIS. |
| `income_type` | String | No | Tipo de ingreso según la DGII. |

#### Campos de cada ítem

| Campo | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | String | Identificador del artículo. |
| `name` | String | Nombre o descripción. |
| `price` | Number | Precio unitario. |
| `quantity` | Number | Cantidad. |
| `unit` | String | Unidad de medida. |
| `itbis_rate` | Number | Tasa de ITBIS (por defecto `0.18`). |
| `discount_rate` | Number | Descuento por línea. |

### `GET /api/v1/invoices/{invoice_id}/status`

Verifica el estado de sincronización, el código e-CF (eNCF) y posibles errores asociados a una factura.

```json
{
  "success": true,
  "invoice_id": "c62fb91d-e5ba-4ea2-877e-1d00d68757b7",
  "status": "Emitida",
  "encf": "E310000000001",
  "track_id": "track_abc123xyz",
  "is_synced_dgii": true,
  "dgii_status": "ACCEPTED",
  "error_detail": null
}
```

### `POST /api/v1/invoices/{invoice_id}/cancel`

Solicita la anulación formal de un comprobante ante la DGII.

**Payload**

```json
{ "reason": "Error en digitación de cantidad de artículos" }
```

**Respuesta**

```json
{
  "success": true,
  "message": "Factura anulada con éxito.",
  "invoice_id": "c62fb91d-e5ba-4ea2-877e-1d00d68757b7",
  "encf": "E310000000001"
}
```

### `POST /api/v1/invoices/{invoice_id}/send_email`

Envía al cliente un correo con su comprobante fiscal (PDF y enlaces al XML).

```json
{ "email": "cliente@ejemplo.com" }
```

### `POST /api/v1/invoices/{invoice_id}/send_receipt`

Envía por correo el recibo de pago de una factura cobrada.

```json
{
  "email": "cliente@ejemplo.com",
  "paymentMethod": "Efectivo",
  "amount": 2500.00
}
```

### `GET /api/v1/invoices`

Retorna el listado de documentos de la empresa. Usa el parámetro
`?is_quotation=true` para obtener cotizaciones.

### `GET /api/v1/documents`

Retorna el listado general de documentos (facturas, cotizaciones y notas).

### Tipos de comprobante (`ecf_type`)

El valor de `ecf_type` es una cadena que identifica el tipo de documento. Los más comunes:

| Código | Descripción |
| :--- | :--- |
| `E31` | Factura de Crédito Fiscal (requiere RNC/Cédula válido del cliente). |
| `E32` | Factura de Consumo (cliente final; admite RNC genérico). |
| `E33` / `E34` | Notas de Crédito / Notas de Débito. |
| `E41` | Comprobante de Gasto Menor. |
| `E43` | Comprobante Especial (entidades gubernamentales y regímenes especiales). |
| `E45` | Factura Gubernamental. |

---

## 5. Clientes

### `GET /api/v1/clients`

Retorna el listado de clientes registrados en el directorio de la empresa.

### `POST /api/v1/clients`

Registra un cliente de forma externa en la agenda de VykOne. Si el RNC ya existe,
actualiza la ficha.

**Payload**

```json
{
  "rnc": "132109122",
  "razon_social": "Soluciones Tecnológicas del Caribe SRL",
  "email": "soporte@cliente.com",
  "telefono": "809-555-0144",
  "direccion": "Av. Winston Churchill #102, Santo Domingo"
}
```

**Respuesta**

```json
{
  "success": true,
  "message": "Cliente registrado exitosamente.",
  "client_id": "a86cfb66-afd7-4d9b-8426-1ca57c5faebe",
  "rnc": "132109122"
}
```

---

## 6. Productos y Servicios

### `GET /api/v1/items`

Retorna el catálogo de artículos y servicios de la empresa.

---

## 7. Consultas DGII

### `GET /api/v1/dgii/rnc/{rnc}`

Consulta el RNC o Cédula directamente en la base de datos de la DGII.

```json
{
  "rnc": "132109122",
  "razonSocial": "SOLUCIONES TECNOLOGICAS DEL CARIBE SRL",
  "nombreComercial": "SOLUCIONES CARIBE",
  "estado": "ACTIVO",
  "regimen": "GENERAL",
  "valid": true
}
```

### `GET /api/v1/dgii/sequences`

Consulta las secuencias (rangos) de comprobantes autorizadas por la DGII y su
estado de consumo (usadas vs. disponibles).

### `GET /api/v1/dgii/audit`

Consulta los logs de auditoría de secuencias usadas, con el estado de aceptación
de la DGII, Track IDs y motivos de aceptación condicional.

---

## 8. Ejemplo de integración (cURL)

Emisión de una factura de consumo (E32) en modo sandbox:

```bash
curl -X POST https://one.vykcore.com/api/v1/invoices/emit \
  -H "X-API-Key: vyk_TU_API_KEY_AQUI" \
  -H "X-Sandbox-Mode: true" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -d '{
    "client_rnc": "132109122",
    "client_name": "Cliente de Ejemplo SRL",
    "ecf_type": "Factura de Consumo (E32)",
    "items": [
      {
        "name": "Licencia SaaS Mensual",
        "price": 2500.00,
        "quantity": 2,
        "itbis_rate": 0.18
      }
    ]
  }'
```

## 9. Buenas prácticas

- Envía siempre un `Idempotency-Key` único por operación para evitar duplicados ante reintentos de red.
- Desarrolla en sandbox y pasa a producción solo tras validar el flujo completo.
- Guarda el `invoice_id` y el `encf` devueltos para consultas posteriores.
- Ante un `422`, revisa el campo `details` para conocer el motivo de rechazo de la DGII.

---

**Control de versiones** · Versión 1.0 · 6 de octubre de 2026 · Emisión inicial ·
Documento técnico de la API de VykOne ERP.
