# Documentación de la API de e-Factura v1

Bienvenido a la API REST de **e-Factura**. Esta API permite a integradores de terceros, sistemas ERP y aplicaciones móviles emitir e-CFs (Comprobantes Fiscales Electrónicos) válidos ante la DGII en República Dominicana, consultar RNCs de clientes, anular facturas y sincronizar catálogos.

---

## 1. Autenticación

Todas las solicitudes HTTP dirigidas a la API deben incluir el encabezado `X-API-Key` con la clave secreta generada en tu panel de **Configuración de Empresa**.

### Cabeceras Globales
| Cabecera | Tipo | Requerido | Descripción |
| :--- | :--- | :--- | :--- |
| `X-API-Key` | String | **Sí** | Tu clave de API única (`ef_...`). |
| `X-Sandbox-Mode` | String | No | `"true"` (por defecto) para pruebas en sandbox o `"false"` para producción. |
| `Content-Type` | String | **Sí** | Debe ser `application/json`. |

---

## 2. Referencia de Endpoints

### 2.1 Emisión de Comprobantes Fiscales (e-CF)
`POST /api/v1/invoices/emit`

Recibe la información de la factura y emite el Comprobante Fiscal Electrónico correspondiente.

#### Payload de Ejemplo (JSON)
```json
{
  "client_id": "cli_9812739",
  "client_rnc": "101012345",
  "client_name": "Cliente de Ejemplo SRL",
  "ecf_type": "Factura de Crédito Fiscal Electrónica (E31)",
  "payment_method": "Crédito",
  "due_date": "2026-06-30",
  "currency": "DOP",
  "discount_rate": 0.05,
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

#### Respuesta de Éxito (`200 OK`)
```json
{
  "success": true,
  "message": "Factura Electrónica e-CF emitida exitosamente.",
  "invoice_id": "c62fb91d-e5ba-4ea2-877e-1d00d68757b7",
  "encf": "E310000000001",
  "track_id": "track_abc123xyz",
  "total": 11300.00
}
```

---

### 2.2 Consulta de Estado de e-CF
`GET /api/v1/invoices/<invoice_id>/status`

Verifica el estado actual de sincronización, el código e-CF (ENFC) y los posibles errores asociados.

#### Respuesta de Éxito (`200 OK`)
```json
{
  "success": true,
  "invoice_id": "c62fb91d-e5ba-4ea2-877e-1d00d68757b7",
  "status": "Emitida",
  "encf": "E310000000001",
  "track_id": "track_abc123xyz",
  "is_synced_dgii": true,
  "error_detail": null
}
```

---

### 2.3 Anulación de e-CF
`POST /api/v1/invoices/<invoice_id>/cancel`

Solicita la anulación formal de un comprobante ante la DGII/Alanube.

#### Payload de Ejemplo
```json
{
  "reason": "Error en digitación de cantidad de artículos"
}
```

#### Respuesta de Éxito
```json
{
  "success": true,
  "message": "Factura anulada con éxito.",
  "invoice_id": "c62fb91d-e5ba-4ea2-877e-1d00d68757b7",
  "encf": "E310000000001"
}
```

---

### 2.4 Validación y Búsqueda de RNC (DGII)
`GET /api/v1/dgii/rnc/<rnc>`

Consulta el RNC o Cédula directamente en la base de datos de la DGII.

#### Respuesta de Éxito
```json
{
  "rnc": "101012345",
  "razonSocial": "COMPAÑIA DE EJEMPLO DE LA DGII",
  "nombreComercial": "EJEMPLO DGII",
  "estado": "ACTIVO",
  "regimen": "GENERAL",
  "valid": true
}
```

---

### 2.5 Sincronización de Clientes
`POST /api/v1/clients`

Registra a un cliente de forma externa en la agenda de e-Factura.

#### Payload de Ejemplo
```json
{
  "rnc": "132109122",
  "razon_social": "Soluciones Tecnológicas del Caribe SRL",
  "email": "soporte@solucionescaribe.com",
  "telefono": "809-555-0144",
  "direccion": "Av. Winston Churchill #102, Santo Domingo"
}
```

#### Respuesta de Éxito
```json
{
  "success": true,
  "message": "Cliente registrado exitosamente.",
  "client_id": "a86cfb66-afd7-4d9b-8426-1ca57c5faebe",
  "rnc": "132109122"
}
```

---

### 2.6 Consultar Documentos y Cotizaciones
`GET /api/v1/invoices` y `GET /api/v1/documents`

Retorna el listado de documentos. Usa el parámetro `?is_quotation=true` en `/invoices` para obtener cotizaciones.

---

### 2.7 Consultar Clientes
`GET /api/v1/clients`

Retorna el listado de clientes registrados en el directorio de la empresa.

---

### 2.8 Consultar Productos y Servicios
`GET /api/v1/items`

Retorna el catálogo de artículos y servicios de la empresa.

---

### 2.9 Consultar Secuencias Fiscales Autorizadas
`GET /api/v1/dgii/sequences`

Consulta las secuencias (rangos) de comprobantes fiscales autorizadas y su estado de consumo (usadas vs disponibles).

---

### 2.10 Consultar Auditoría DGII
`GET /api/v1/dgii/audit`

Consulta los logs de auditoría de secuencias usadas, mostrando si la DGII las aceptó, los Track IDs y motivos de aceptación condicional.

---

### 2.11 Enviar Recibo de Ingreso por Correo
`POST /api/v1/invoices/<invoice_id>/send_receipt`

Envía un correo electrónico al cliente con el recibo de pago de una factura cobrada. Soporta SMTP interno configurado.

#### Payload de Ejemplo
```json
{
  "email": "cliente@ejemplo.com",
  "paymentMethod": "Efectivo",
  "amount": 2500.00
}
```

---

### 2.12 Enviar Factura Electrónica (XML/PDF) por Correo
`POST /api/v1/invoices/<invoice_id>/send_email`

Envía un correo electrónico al cliente adjuntando su comprobante fiscal electrónico y enlaces al XML y PDF.

#### Payload de Ejemplo
```json
{
  "email": "cliente@ejemplo.com"
}
```

---

## 3. Ejemplo de Integración en cURL

```bash
curl -X POST http://127.0.0.1:5000/api/v1/invoices/emit \
  -H "X-API-Key: ef_TU_API_KEY_AQUI" \
  -H "X-Sandbox-Mode: true" \
  -H "Content-Type: application/json" \
  -d '{
    "client_rnc": "132109122",
    "client_name": "Cliente de Ejemplo SRL",
    "ecf_type": "Factura de Consumo Electrónica (E32)",
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
