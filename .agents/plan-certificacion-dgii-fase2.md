# Plan de Certificación y Pruebas Fiscales DGII — Fase 2

## Objetivos
- Validar cumplimiento real con DGII (no solo XSD)
- Validar integridad criptográfica post-firma
- Validar reglas de negocio fiscales por tipo de comprobante
- Validar concurrencia y secuencias bajo carga
- Validar contingencia (DGII offline / recuperación)
- Generar evidencia completa para certificación

## Criterio de salida (gate)
**No iniciar** Autoemisión E41/E43, Arquitectura FiscalDocumentType, ni NCF tradicionales (B01–B18) hasta que:
- E31, E32, E33, E34, E41, E43, E45, E46, E47 hayan sido aceptados exitosamente por el ambiente de certificación DGII
- Hayan superado pruebas de concurrencia, contingencia y validación criptográfica

---

## Bloque 1 — Certificación contra DGII real

### E31 Factura de Crédito Fiscal
| Tipo | Caso | Descripción |
|------|------|-------------|
| Positivo | Cliente RNC válido | Cliente con RNC registrado, venta gravada |
| Positivo | Venta exenta | Producto exento de ITBIS |
| Positivo | Venta mixta | Líneas gravadas + exentas + ITBIS diferencial |
| Positivo | Descuento global | Descuento antes de ITBIS |
| Positivo | Múltiples líneas | 5+ líneas con distintas tasas |
| Negativo | RNC inválido | RNC que no pasa validación DGII |
| Negativo | ITBIS incorrecto | Tasa 18% en producto exento |
| Negativo | Totales inconsistentes | Subtotal + ITBIS ≠ Total |
| Negativo | Fecha fuera de período | FechaEmision fuera del rango del NCF |

### E32 Factura de Consumo
| Tipo | Caso | Descripción |
|------|------|-------------|
| Positivo | Consumidor final | Sin identificación fiscal |
| Positivo | Con cédula | Consumidor con cédula |
| Positivo | Menor al límite | Monto < RD$250,000 |
| Negativo | RNC requerido | Monto > RD$250,000 sin RNC |
| Negativo | ITBIS inconsistente | Tasa incorrecta para el tipo |

### E33 Nota de Débito
| Tipo | Caso | Descripción |
|------|------|-------------|
| Positivo | Incremento parcial | Aumento sobre factura existente |
| Positivo | Incremento total | Duplicar monto original |
| Negativo | Factura inexistente | Referencia a factura que no existe en DGII |
| Negativo | Factura anulada | Referencia a factura anulada |
| Negativo | Monto negativo | Intento de nota de débito con monto < 0 |

### E34 Nota de Crédito
| Tipo | Caso | Descripción |
|------|------|-------------|
| Positivo | Devolución parcial | Devolución de 1 línea |
| Positivo | Devolución total | Anulación completa |
| Positivo | Descuento posterior | Ajuste comercial |
| Negativo | Referencia inexistente | NCFModificado inválido |
| Negativo | Monto superior | NC > factura original |
| Negativo | ITBIS recalculado | ITBIS no coincide con devolución |

### E41 Compras
| Tipo | Caso | Descripción |
|------|------|-------------|
| Positivo | Proveedor informal | Compra a persona física sin RNC |
| Positivo | Compra local | Proveedor local con RNC |
| Positivo | Retención ISR | Compra sujeta a retención |
| Positivo | Retención ITBIS | Compra sujeta a retención ITBIS |
| Negativo | Retención > impuesto | ITBIS retenido > ITBIS facturado |
| Negativo | Proveedor incompleto | Datos insuficientes del proveedor |

### E43 Gastos Menores
| Tipo | Caso | Descripción |
|------|------|-------------|
| Positivo | Gasto transporte | Combustible, peaje, parqueo |
| Positivo | Gasto operativo | Suministros, papelería |
| Negativo | Monto excesivo | Gastos que exceden ~RD$100,000 |
| Negativo | Datos incompletos | Sin concepto o fecha |

### E45 Gubernamental
| Tipo | Caso | Descripción |
|------|------|-------------|
| Positivo | Institución pública | RNC gubernamental válido |
| Negativo | Cliente privado | Empresa privada usando E45 |

### E46 Exportación
| Tipo | Caso | Descripción |
|------|------|-------------|
| Positivo | Cliente extranjero | Comprador internacional |
| Positivo | Moneda USD | Facturación en dólares |
| Positivo | Transporte | Incoterm, puerto, país destino |
| Negativo | Cliente local | Cliente dominicano en E46 |
| Negativo | ITBIS aplicado | ITBIS incluido en factura de exportación |

### E47 Pago al Exterior
| Tipo | Caso | Descripción |
|------|------|-------------|
| Positivo | Proveedor extranjero | Servicios del exterior |
| Positivo | Moneda extranjera | USD, EUR |
| Negativo | ITBIS incluido | ITBIS en pago al exterior |
| Negativo | Conversión incorrecta | Tasa de cambio errónea |

---

## Bloque 2 — Validación Criptográfica

Para **cada tipo** de comprobante:

| Verificación | Herramienta | Criterio |
|-------------|-------------|----------|
| XML Well Formed | lxml | Parsing exitoso |
| Canonicalización | signxml / c14n | XML canónico reproduce digest |
| Digest SHA | Verify SHA256 | Valor en <DigestValue> coincide |
| SignatureValue | Verify RSA | Firma válida con certificado emisor |
| Certificado vigente | OpenSSL x509 | Válido para la fecha actual |
| Certificado expirado | OpenSSL x509 | Rechazo esperado |
| Certificado revocado | CRL / OCSP | Rechazo esperado |

**Script**: `tests/test_cryptographic_validation.py` — toma XML firmado, verifica cada paso, reporta tipo, resultado, y evidencia.

---

## Bloque 3 — Stress Test de Secuencias

| Escenario | Usuarios | Emisiones | Validaciones |
|-----------|----------|-----------|--------------|
| A | 100 | 1,000 | Sin duplicados, sin pérdidas, sin corrupción |
| B | 500 | 5,000 | Throughput, tiempo promedio, tiempo máximo, consumo secuencias |
| C | 1 | 50 (con fallo DGII simulado) | Secuencia consumida, registro consistente, recuperación posterior |

**Script**: `tests/test_stress_sequences.py` — usa threads/async para simular concurrencia, verifica Firestore sequence docs.

---

## Bloque 4 — Contingencia

| Escenario | Prueba |
|-----------|--------|
| DGII offline | Cola de contingencia, reintentos (MAX_RETRY_ATTEMPTS=20), sin duplicación |
| Recuperación | Reenvío automático al restaurar conectividad, actualización de estado, cierre correcto de cola |

**Script**: `tests/test_contingency.py` — mock `requests.post` para simular timeout/error, verifica cola y retry.

---

## Bloque 5 — Reportes DGII

| Reporte | Tipos incluidos |
|---------|----------------|
| 606 (Compras) | E41, E43, E45, E47 |
| 607 (Ventas/Ingresos) | E31, E32, E33, E34, E45, E46 |
| 608 (Anulaciones) | NCF anulados de cualquier tipo |
| 623 (Operaciones internacionales) | E46, E47 |

**Verificación**: Cada reporte se genera y contiene los XML aceptados del Bloque 1.

---

## Bloque 6 — Evidencia de Certificación

Para **cada tipo**, generar y archivar:

1. `E{N}_raw.xml` — XML generado por el builder
2. `E{N}_signed.xml` — XML firmado (firma real con certificado)
3. `E{N}_ack.xml` — Acuse DGII (TrackId + estado)
4. `E{N}_status.json` — Consulta de estado final
5. `E{N}.pdf` — Representación PDF del comprobante
6. `E{N}_accounting.json` — Asiento contable generado
7. `E{N}_report.csv` — Registro en reportes fiscales (606/607)

**Criterio de aceptación**: Cada archivo existe y es válido.

---

## Archivos a crear

| Archivo | Propósito |
|---------|-----------|
| `tests/test_cases_e31.py` | Batería E31 (5+ casos) |
| `tests/test_cases_e32.py` | Batería E32 (4+ casos) |
| `tests/test_cases_e33.py` | Batería E33 (4+ casos) |
| `tests/test_cases_e34.py` | Batería E34 (6+ casos, la más importante) |
| `tests/test_cases_e41.py` | Batería E41 (5+ casos) |
| `tests/test_cases_e43.py` | Batería E43 (3+ casos) |
| `tests/test_cases_e45.py` | Batería E45 (2+ casos) |
| `tests/test_cases_e46.py` | Batería E46 (4+ casos) |
| `tests/test_cases_e47.py` | Batería E47 (3+ casos) |
| `tests/test_cryptographic_validation.py` | Verificación firma digital |
| `tests/test_stress_sequences.py` | Concurrencia y secuencias |
| `tests/test_contingency.py` | Contingencia y recuperación |
| `tests/test_reports_606_607.py` | Reportes fiscales |
| `tests/run_certification.py` | Orquestador: ejecuta bloques 1–6, genera evidencia |

---

## Orden de ejecución sugerido

```
1.  test_cryptographic_validation.py   ← validar que firmamos bien
2.  test_cases_e31.py ... e47.py        ← validar lógica fiscal por tipo
3.  test_reports_606_607.py            ← validar reportes
4.  test_contingency.py                ← validar contingencia
5.  test_stress_sequences.py           ← validar concurrencia
6.  run_certification.py               ← generar evidencia para DGII
```
