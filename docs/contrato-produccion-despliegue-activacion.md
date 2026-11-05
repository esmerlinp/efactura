# Contrato de Producción — Procedimiento de Despliegue y Activación

> Alcance: sistema de contrato de producción de VykOne (aceptación empresarial +
> reconocimiento individual). Este documento es el **runbook operativo** para
> desplegar y activar la funcionalidad sin habilitar controles parciales.
>
> Regla de oro: **la evidencia contractual es inmutable**. Una reversión técnica
> nunca debe eliminar ni modificar aceptaciones históricas.

---

## 1. Inventario de componentes

### Servicios (código)

| Archivo | Responsabilidad |
|---|---|
| `app/services/production_agreement_service.py` | Sanitización HTML, hash SHA-256, versiones, publicación transaccional, integridad |
| `app/services/production_agreement_acceptance_service.py` | Aceptación empresarial + reconocimiento individual, idempotencia, evidencia |
| `app/services/production_agreement_access_service.py` | Decisiones de acceso por contexto (web/jobs/API) |
| `app/services/production_agreement_guard.py` | Guard web global con excepciones por endpoint |
| `app/services/production_agreement_admin_service.py` | Autorización de administración de plataforma |

### Rutas

| Ruta | Actor | Descripción |
|---|---|---|
| `GET /production-agreement` | Usuario | Lectura y aceptación del contrato |
| `POST /production-agreement/accept-company` | Owner | Aceptación empresarial |
| `POST /production-agreement/acknowledge` | Usuario | Reconocimiento individual |
| `POST /production-agreement/reject` | Usuario | Rechazo → cierre de sesión |
| `GET /admin/production-agreements` | Admin plataforma | Listado de versiones |
| `POST /admin/production-agreements/draft` | Admin plataforma | Crear borrador |
| `POST /admin/production-agreements/<id>/edit` | Admin plataforma | Editar borrador |
| `POST /admin/production-agreements/<id>/publish` | Admin plataforma | Publicar versión |
| `GET /admin/production-agreements/acceptances` | Admin plataforma | Evidencia de aceptaciones |
| `GET /admin/production-agreements/acknowledgements` | Admin plataforma | Evidencia de reconocimientos |
| `GET /admin/production-agreements/export` | Admin plataforma | Exportación CSV de evidencia |

### Modelo Firestore

```
# Versiones maestras (raíz)
production_agreement_versions/{version_id}
  version, title, content, contentHash,
  status (draft|active|superseded), environment,
  createdAt, createdBy, publishedAt, publishedBy

# Puntero global (una única versión activa)
system_config/production_agreement
  active_version_id, updated_at, updated_by

# Administradores de plataforma
system_config/production_agreement_admins
  admins: { uid: ["VIEW","CREATE","EDIT","PUBLISH","AUDIT"] }

# Evidencia — aceptación empresarial (una por compañía y versión)
companies/{company_id}/production_agreement_acceptances/{version_id}
  companyId, agreementVersion, versionId, contentHash,
  acceptedBy, acceptedByName, acceptedByEmail, acceptedAt,
  acceptanceType, acceptanceMethod, ipAddress, userAgent, environment

# Evidencia — reconocimiento individual (uno por usuario y versión)
companies/{company_id}/user_agreement_acknowledgements/{user_id}__{version_id}
  companyId, userId, agreementVersion, versionId, contentHash,
  acknowledgedAt, acceptanceType, acceptanceMethod, ipAddress, userAgent, environment
```

---

## 2. Configuración del entorno

### 2.1 Variables de entorno

```bash
# Administradores de plataforma (bootstrap; separados por coma)
PRODUCTION_AGREEMENT_ADMIN_UIDS=<uid1>,<uid2>

# (Opcional) Confiar en X-Forwarded-For SOLO si existe proxy confiable delante.
# Por defecto FALSE: se usa request.remote_addr como IP de evidencia.
TRUST_PROXY_HEADERS=false
```

> Importante: `TRUST_PROXY_HEADERS` debe permanecer `false` salvo que el despliegue
> esté detrás de un proxy de confianza (Cloud Run con `--ingress` + load balancer
> configurado). Si se habilita, validar que el proxy **sobrescriba** `X-Forwarded-For`
> para que un cliente no pueda inyectar la cabecera.

### 2.2 Firestore

1. Habilitar Firestore en modo nativo.
2. Crear los índices compuestos que Firestore solicite al ejecutar las consultas
   de administración (`collection_group` sobre `production_agreement_acceptances`
   y `user_agreement_acknowledgements`). El error de Firestore indicará el índice
   exacto; no pre-crear índices innecesarios.

---

## 3. Designación del primer administrador de plataforma

La administración **no depende** de roles de compañía. El bootstrap es por entorno:

```text
PRODUCTION_AGREEMENT_ADMIN_UIDS=<uid-del-responsable>
```

Verificación posterior al despliegue:

1. Iniciar sesión con la cuenta cuyo UID fue configurado.
2. Acceder a `GET /admin/production-agreements`.
3. Confirmar acceso a listado/editor/publicación.
4. Una cuenta **no** listada debe recibir `403` (no redirección a contrato).

Gestión alternativa (sin redeploy): crear/editar el documento
`system_config/production_agreement_admins`:

```json
{ "admins": { "<uid>": ["VIEW", "CREATE", "EDIT", "PUBLISH", "AUDIT"] } }
```

---

## 4. Publicación de la primera versión (activación del contrato)

> **No publicar sin aprobación jurídica.** El contenido legal debe ser revisado
> antes de publicar. Una versión publicada es inmutable.

1. Acceder a `GET /admin/production-agreements/new`.
2. Redactar el contrato como HTML permitido (p, h1–h6, ul/ol/li, strong/em/a,
   table, blockquote, div/section). El sistema **sanea** el HTML antes de guardar
   y calcula el `contentHash` sobre el contenido saneado.
3. Guardar el borrador (`POST /admin/production-agreements/draft`).
4. Revisar la **previsualización saneada** y el hash mostrado.
5. Aprobar legalmente el contenido.
6. Publicar (`POST /admin/production-agreements/<id>/publish` con `confirm=PUBLISH`).

### Efecto inmediato de la publicación

- El puntero `system_config/production_agreement` apunta a la nueva versión.
- **Todas** las compañías en producción quedan `pending` (sin evidencia → bloqueadas).
- **Todos** los usuarios activos, incluido el owner, quedan pendientes.
- Sandbox queda **sin cambios** (no exige contrato).
- APIs de producción permanecen **bloqueadas** (403).
- Jobs de producción omiten compañías sin aceptación empresarial.

---

## 5. Flujo de aceptación posterior a la activación

### Owner

1. En producción es redirigido a `/production-agreement`.
2. Acepta el contrato **en representación de la compañía** (`accept-company`).
3. Se vuelve a evaluar: ahora debe completar su **reconocimiento individual** (`acknowledge`).
4. Tras ambos pasos, accede al sistema.

### Colaborador

1. Si la compañía aún no fue aceptada → ve un aviso de que el owner debe aceptar
   primero. No puede aceptar por la empresa.
2. Si la compañía ya fue aceptada → solo completa su reconocimiento individual.

### Cambio de compañía

Cada cambio de `selected_company_id` re-evalúa el contrato de la nueva compañía.

---

## 6. Verificación en staging (obligatoria antes de producción)

Usar el emulador de Firestore o el proyecto de staging.

1. **Sandbox sin contrato**: el acceso a sandbox funciona sin aceptación.
2. **Producción bloqueada**: sin versión publicada → sin bloqueo; con versión
   publicada → redirección a `/production-agreement`.
3. **Owner acepta + reconoce**: acceso habilitado.
4. **Colaborador**: bloqueado hasta que el owner acepte; luego solo reconoce.
5. **API**: `X-Sandbox-Mode: false` → `403 PRODUCTION_AGREEMENT_REQUIRED`;
   `true` → opera.
6. **Jobs**: con contrato aceptado operan; sin aceptación, omiten la compañía.
7. **Nueva versión**: publicar v2 → todos vuelven a quedar pendientes.
8. **Concurrencia**: dos publicaciones simultáneas no generan dos versiones activas
   (validar con el emulador, que soporta transacciones).
9. **Evidencia**: verificar `acceptedAt`/`acknowledgedAt` con `SERVER_TIMESTAMP`,
   `ipAddress`, `userAgent` y `contentHash` correctos.
10. **CSRF y manipulación**: el POST de aceptación sin token CSRF es rechazado;
    `companyId`/`userId`/`contentHash`/`agreementVersion` del formulario se ignoran.

---

## 7. Despliegue a producción

1. Ejecutar la suite completa:
   ```bash
   python -m pytest tests/test_production_agreement.py \
     tests/test_production_agreement_guard.py \
     tests/test_production_agreement_security.py \
     tests/test_production_agreement_admin.py \
     tests/test_production_agreement_jobs_api.py
   ```
2. Revisar `git diff` de los archivos del alcance (ver §1).
3. Desplegar el código (no publicar el contrato aún).
4. Configurar `PRODUCTION_AGREEMENT_ADMIN_UIDS`.
5. Publicar la primera versión **manualmente** (sección §4), tras aprobación legal.
6. Monitorear: usuarios bloqueados redirigidos, owner completa el flujo,
   colaboradores completan reconocimiento, jobs omiten compañías pendientes.

> El despliegue del código **no** bloquea a nadie por sí solo. El bloqueo solo
> se activa al publicar la primera versión.

---

## 8. Reversión técnica (sin eliminar evidencia)

Una reversión técnica desactiva la **exigencia**, no la **historia**.

### Opción A — revertir código

`git revert` del commit de integración del guard. Efecto: el sistema deja de
exigir el contrato. La evidencia almacenada en Firestore **permanece intacta**.

### Opción B — desactivar sin revertir (puente temporal, NO bypass permanente)

No existe un switch global "off" en el código. La forma controlada de desactivar
la exigencia es **retirar el puntero activo** (ver §9.2) o revertir el código.
Cualquier cambio debe quedar registrado en auditoría.

---

## 9. Recuperación operativa (sin bypass contractual permanente)

### 9.1 Compañía bloqueada por error operativo (p. ej. despliegue fallido)

1. Verificar el puntero activo `system_config/production_agreement`.
2. Confirmar que existe la versión activa y su `contentHash`.
3. Si el error es de despliegue (no de aceptación), corregir y re-desplegar.
4. No registrar aceptaciones ficticias.

### 9.2 Retirar la exigencia temporalmente

Retirar `active_version_id` del documento `system_config/production_agreement`
(o marcar la versión como `superseded` y no publicar otra). Esto restablece el
comportamiento "sin versión publicada → sin exigencia".

> Esto **no** es un bypass permanente: es una operación administrativa reversible
> y auditable. Debe registrarse quién, cuándo y por qué.

### 9.3 Evidencia de una versión corrupta

- La evidencia no se edita. Si el hash publicado no coincide con el HTML
  (verificable con `ProductionAgreementService.verify_integrity`), publicar una
  **nueva** versión corregida. La anterior queda como `superseded`.

---

## 10. Checklist de activación

- [ ] Revisión jurídica del contenido del contrato.
- [ ] `PRODUCTION_AGREEMENT_ADMIN_UIDS` configurado en el entorno.
- [ ] Staging: 10 verificaciones de §6 aprobadas.
- [ ] Suite de pruebas completa en verde.
- [ ] Primera versión publicada por acción administrativa explícita.
- [ ] Owner de referencia completó aceptación + reconocimiento.
- [ ] Colaborador de referencia completó reconocimiento.
- [ ] Jobs de producción verificados (omiten compañías pendientes).
- [ ] API de producción verificada (`403` sin identidad contractual).
- [ ] Evidencia (IP/User-Agent/hash/fecha) verificada en Firestore.

---

## 11. Riesgos residuales y limitaciones

1. **Identidad de API keys**: las credenciales actuales no identifican a una
   persona; por eso las APIs de producción permanecen bloqueadas. Habilitarlas
   requiere añadir una identidad contractual generada por el servidor a la
   credencial (p. ej. `api_key_owner_uid`) y no aceptar `userId` del cliente.
2. **Representación legal**: solo `companies/{company_id}.owner_uid` puede aceptar
   por la compañía. Un "representante autorizado" distinto del owner aún no está
   modelado; requiere un campo explícito (`authorized_representative_uid`) y su
   flujo de gestión auditable.
3. **Concurrencia transaccional**: validada por diseño; la prueba física se realiza
   contra el emulador de Firestore en staging.
4. **IP de evidencia**: confiable solo si `TRUST_PROXY_HEADERS` se configura
   correctamente junto con el proxy que sobrescribe `X-Forwarded-For`.
5. **Jobs legacy**: el descubrimiento de compañías en el scheduler usa el bridge
   `owner_uid → company_id`; si una compañía no resuelve, el job falla cerrado
   (omite). Verificar la resolución de compañía de cada entorno.
