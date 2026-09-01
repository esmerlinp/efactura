# Receptor e-CF DGII — Implementación y Certificación (Resumen de cambios)

> Resumen de los cambios realizados en la implementación del módulo receptor de
> comprobantes fiscales electrónicos (e-CF) para la certificación DGII
> (URLs `/fe/autenticacion/api/[semilla|ValidacionCertificado]` y
> `/fe/recepcion/api/ecf`), incluyendo las correcciones iteradas contra las
> pruebas reales del portal DGII.

## Contexto

La DGII certifica al sistema como **receptor** de e-CF: el sistema debe exponer
servicios de autenticación y recepción en URLs exactas, responder acuses de
recibo (ARECF) síncronos y pasar las pruebas de datos del portal. El dominio es
compartido por múltiples clientes, por lo que **no puede haber datos estáticos
de empresa** en el flujo: cada petición se resuelve dinámicamente por el
`RNCComprador` del e-CF recibido.

## Archivos modificados

| Archivo | Cambio |
|---|---|
| `app/__init__.py` | Blueprint receptor registrado sin prefijo (rutas exactas `/fe/...`); exención CSRF para `/fe/` (case-insensitive) |
| `app/api/v1/receptor.py` | Endpoints DGII, autenticación por token, resolución dinámica de empresa, dispatcher case-insensitive |
| `app/services/receptor_auth_service.py` | Semilla `SemillaModel`, validación de semilla firmada (XMLDSig), verificador manual .NET/Java-equivalente, tokens |
| `app/services/receptor_xml_service.py` | Parseo namespace-aware del e-CF, verificación de firma, ARECF en formato oficial XSD |
| `app/repositories/receptor_repository.py` | Persistencia de semillas/tokens/e-CF/ARECF/aprobaciones + diagnóstico de rechazos |
| `app/services/db_service.py` | `get_company_by_rnc()` para resolución de empresa |
| `app/web/recepcion.py` | UI `/recepcion/ecf` con lecturas combinadas sandbox+producción y `selected_owner_uid` |
| `config.py` | `RECEPTOR_AUTH_ENABLED`, `RECEPTOR_TOKEN_EXPIRY_MINUTES=30`, `RECEPTOR_SEED_TTL_SECONDS=900`, `RECEPTOR_REQUIRE_SIGNATURE`, `RECEPTOR_DEFAULT_OWNER_UID` |
| `tests/test_receptor_endpoints.py` | 38 tests de regresión del flujo completo |
| `.gcloudignore` | Evitar subida de `venv/` en deploys con `gcloud run deploy --source` |

## Rutas DGII (registradas sin prefijo `/api/v1`)

```
GET  /fe/autenticacion/api/semilla                → <SemillaModel>
POST /fe/autenticacion/api/validacioncertificado  → token (JSON o XML)
POST /fe/recepcion/api/ecf                        → ARECF firmado (Estado 0/1)
POST /fe/aprobacioncomercial/api/ecf              → ACECF recibido
```

- Cualquier variante de mayúsculas/minúsculas en cualquier segmento funciona
  (dispatcher `fe_dispatch` bajo `/fe/`, `/Fe/`, `/fE/`, `/FE/` con
  `<path:rest>` normalizado a minúsculas). La DGII varía el casing
  (`validacionCertificado`, `VALIDACIONCERTIFICADO`, etc.).
- Exentas de CSRF (comparación case-insensitive del prefijo `/fe/`).
- Sin rate limits.

## Flujo de autenticación (semilla → token)

1. `GET semilla` emite `<SemillaModel><valor/><fecha/></SemillaModel>` y guarda
   la semilla en Firestore (`receptor_seeds`, TTL 15 min, doc id = semilla).
2. `POST validacioncertificado` recibe el XML firmado en cualquier formato
   (multipart `xml`/`file`/`archivo`/`semilla`, form, JSON o cuerpo crudo).
   - La semilla se valida contra las emitidas **server-side** (sin depender de
     headers del cliente; `X-Seed-Value` opcional).
   - Firma: primero `signxml` (con reintentos `id_attribute` en `.verify()`);
     si falla, **verificador manual equivalente al firmante Java/.NET**.
   - Token SHA-256 guardado en `receptor_tokens` (top-level), TTL 30 min,
     vinculado al RNC del certificado del emisor.
3. La semilla se consume **solo tras una firma válida** (permite reintentos).

## Verificador XMLDSig manual (`_manual_xmldsig_verify`)

Diseñado contra el payload real de la DGII (validado localmente con RSA real):

- Resuelve `Reference URI=""` (documento completo) o `URI="#id"` (elemento con
  `Id`), aplica transform `enveloped-signature`, c14n inclusiva/exclusiva según
  el `CanonicalizationMethod` declarado, verifica digest (sha1/sha256/sha384/
  sha512) y `SignatureValue` (rsa-sha1/…/rsa-sha512, PKCS#1 v1.5).
- **Clave**: el `SignedInfo` se canonicaliza reconstruyendo el elemento con
  **todas las declaraciones de namespaces en alcance** (`xmlns`, `xmlns:xsd`,
  `xmlns:xsi` heredados) — `_signed_info_c14n()`. lxml/libxml2 emite `xmlns=""`
  espurios en subárboles con default-namespace y signxml usa c14n spec-estricta;
  ambos fallan con la firma de la DGII. Los bytes exactos verificados:
  `<SignedInfo xmlns="…xmldsig#" xmlns:xsd="…" xmlns:xsi="…">…` (elementos vacíos
  expandidos `<x></x>`, sin ns extra en hijos).

## Recepción e-CF (`/fe/recepcion/api/ecf`)

1. Token Bearer válido (sin resolver empresa en auth).
2. Parseo namespace-aware (`local-name()`), verificación de firma del e-CF.
3. **Resolución dinámica de empresa por `RNCComprador` del e-CF**
   (`get_company_by_rnc`) — multi-tenant, sin datos estáticos por cliente.
   Fallback (solo para poder responder ARECF motivo 4): header `X-Owner-UID` →
   owner del token → `RECEPTOR_DEFAULT_OWNER_UID` (env, opcional).
4. ARECF en formato oficial `Schemas/ARECF v1.0.xsd`
   (`ARECF/DetalleAcusedeRecibo/Version/RNCEmisor/RNCComprador/eNCF/Estado/
   CodigoMotivoNoRecibido?/FechaHoraAcuseRecibo` dd-MM-yyyy HH:mm:ss), firmado
   con el certificado de la empresa (el `ds:Signature` calza en el `xs:any` del
   XSD). Sin TrackId en el cuerpo (se devuelve como header `X-Track-Id`).
5. `Estado=1` con `CodigoMotivoNoRecibido`: 2 (firma inválida, si
   `RECEPTOR_REQUIRE_SIGNATURE`), 3 (duplicado eNCF+emisor), 4 (RNCComprador no
   corresponde). RNCComprador desconocido sin fallback → 404 JSON.
6. Persistencia: `companies/{owner_uid}/{sandbox_}received_ecf` con XML completo,
   ARECF, track_id, estado y `received_at`. Rechazos de autenticación guardan el
   XML completo en `receptor_diagnostics` para diagnóstico.

## Visualización y persistencia en la UI

- Persistencia en Firestore (durable entre reinicios).
- UI `/recepcion/ecf` (lista, detalle, descargas XML/ARECF) usa lecturas
  combinadas sandbox+producción (`list_received_ecf_merged`,
  `get_received_ecf_merged`, `list_received_approvals_merged`) y
  `selected_owner_uid` — los documentos siempre son visibles sin importar el
  toggle de sandbox ni el usuario logueado.
- El filtro por estado se aplica en memoria (evita índice compuesto Firestore
  `status + received_at`).

## Ops / Despliegue

- `one-sandbox` (Cloud Run, `us-central1`): revisiones desplegadas con
  `gcloud run deploy one-sandbox --region us-central1 --source .`
  (`.gcloudignore` excluye `venv/`).
- `RECEPTOR_DEFAULT_OWNER_UID=4vdcp3ysKGQgP2DVfHZpIVbXp793` (VYKCORE AUTOMATION
  SRL, RNC 133753652) configurado como fallback — **no es necesario para el
  happy path**; cada cliente resuelve por su RNCComprador.
- Dominio registrado ante la DGII: `sandbox.one.vykcore.com` (apunta a la raíz
  del servicio, sin prefijos de path).

## Errores reales de la DGII corregidos (cronología)

1. **400 en autenticación** (payload rechazado): formato de firma de la DGII no
   aceptado por signxml → verificador manual + logging por etapa + payload
   completo en `receptor_diagnostics`.
2. **400 "SignatureValue no válida"**: c14n del SignedInfo incorrecto → 
   `_signed_info_c14n()` con namespaces en alcance (verificado byte a byte
   contra la firma real: digest OK + RSA OK).
3. **401 Unauthorized en recepción**: se resolvía empresa por el RNC del
   certificado de prueba de la DGII (`IDCDO-00199999996`) → auth ligera (solo
   token) + resolución dinámica por `RNCComprador` del e-CF.
4. **404 en `validacionCertificado`**: casing variable del cliente DGII →
   dispatcher case-insensitive de rutas `/fe/...`.

## Verificación

- `python3 -m pytest tests/test_receptor_endpoints.py` (38 tests: rutas, semilla,
  token, payloads raw/form, verificador manual con digest/referencia por Id/
  transform enveloped, multi-tenant por RNCComprador, motivo 3/4, CSRF, 
  dispatcher case-insensitive, diagnóstico persistido).
- Regresión: `tests/test_dgii_direct.py`, `tests/test_dgii.py`,
  `tests/test_cert_excel_loader.py` (76 tests en total).
- Nota local: `cryptography` no corre en esta Mac (mismatch de arquitectura),
  por eso `tests/conftest.py` la mockea; la validación RSA real se hizo con
  `openssl` + aritmética pura contra el payload guardado en
  `receptor_diagnostics`.
