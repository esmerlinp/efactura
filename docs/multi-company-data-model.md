# Modelo de Datos Multi-Company — VykOne ERP

> **Versión:** 1.0  
> **Estado:** Aprobado para implementación  
> **Propósito:** Documentar formalmente el nuevo modelo multi-tenant del ERP antes de implementar cualquier cambio.
> 
> **Historial de revisión:**
> - v1.0 (2026-07-22): Versión inicial aprobada.

---

## 1. Arquitectura General

### Principios

1. **La Compañía es la entidad raíz de negocio.** No el Owner ni el Usuario.
2. **Aislamiento total por compañía.** Cada compañía tiene sus propios datos de empleados, nómina, TSS, facturación, etc. No se comparten datos entre compañías.
3. **Un Owner puede tener N compañías.** La relación es directa: `companies.owner_uid` → `users.uid`.
4. **Un usuario (colaborador) puede pertenecer a M compañías.** La membresía es explícita vía `company_memberships`.
5. **Migración gradual por módulo.** No se mueve todo de golpe. Cada módulo migra independientemente.
6. **Capa de compatibilidad.** `selected_company_id` es el único contexto de sesión. `ownerUID` se deriva desde la compañía para código legacy.

### Diagrama de relaciones

```
users/{uid}                          (Owner / Persona física)
  └─ config/user_profile             (Datos personales + preferencias)

companies/{companyId}                (Entidad de negocio)
  ├─ profile                         (RNC, nombre, config fiscal, plan)
  ├─ branches/                       (Sucursales)
  ├─ employees/                      (Empleados de RRHH)
  ├─ payrolls/                       (Nóminas)
  ├─ tss/                            (TSS)
  ├─ invoices/                       (Facturación electrónica)
  ├─ clients/                        (Clientes)
  ├─ ... (demás módulos)
  └─ audit_logs/                     (Logs de auditoría)

company_memberships/{membershipId}   (Membresías: quién tiene acceso a qué compañía)
  ├─ uid                             (Usuario)
  ├─ company_id                      (Compañía)
  ├─ role                            (Rol en esta compañía)
  └─ permissions                     (Permisos específicos en esta compañía)
```

### Estrategia de almacenamiento en Firestore

```
Colecciones raíz:
  ├─ users/{uid}/
  │   └─ config/
  │       └─ user_profile          ← Ya existe. Se agregan campos.
  │
  ├─ companies/{companyId}/
  │   ├─ profile                   ← NUEVO. Perfil completo de la compañía.
  │   ├─ branches/{id}             ← NUEVO (se migra desde users/{uid}/branches)
  │   ├─ employees/{id}            ← NUEVO (se migra desde users/{uid}/employees)
  │   ├─ team/{id}                 ← NUEVO (se migra desde users/{uid}/team)
  │   └─ audit_logs/{id}           ← NUEVO
  │
  └─ company_memberships/{id}      ← NUEVO. Indice de pertenencias.

users/{uid}/{modules} siguen existiendo mientras se migra módulo por módulo.
```

---

## 2. Entidades

### 2.1 Company

**Colección:** `companies/{companyId}/profile`  
**Clave primaria:** `companyId` (UUID v4)  
**Creada por:** Owner del grupo  
**Alcance:** Global (colección raíz)  
**Estrategia de migración:** Crear desde cero. Poblada por script one-time desde `users/{uid}/config/profile`.

```python
{
    "id": "comp_a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    # === Dueño (solo para transición — no usar como pivote futuro) ===
    "owner_uid": "firebase_uid_del_owner",
    # === Identificación ===
    "name": "Empresa A SRL",
    "trade_name": "Empresa A",
    "rnc": "131234567",
    "type": "srl",
    "status": "active",                   # active | suspended | cancelled
    "is_default": true,                   # ¿Es la compañía principal del owner?
    # === Configuración fiscal ===
    "regimen_fiscal": "ordinary",
    "country": "DO",
    "next_certificate_number": 1,
    "certificate_name": "",
    "certificate_content": "",
    "certificate_password": "",
    # === Branding ===
    "color_marca": "#10b981",
    "gradient_enabled": false,
    "logo_url": "",
    "logo_base64": "",
    "stamp_url": "",
    "signature_url": "",
    # === Plan / Módulos ===
    "plan_id": "",
    "plan_version": 0,
    "pos_enabled": true,
    "production_enabled": true,
    "sandbox_enabled": true,
    # === Dirección ===
    "address": "Santo Domingo, RD",
    "province": "Santo Domingo",
    "municipality": "Santo Domingo de Guzmán",
    "phone": "809-555-0199",
    "email": "factura@empresa.com.do",
    # === Auditoría ===
    "created_by": "firebase_uid",
    "created_at": "2026-07-22T12:00:00Z",
    "updated_by": "firebase_uid",
    "updated_at": "2026-07-22T12:00:00Z"
}
```

**Migración desde `users/{uid}/config/profile`:**

```
Campo actual → Campo nuevo
─────────────────────────────────────
ownerUID    → owner_uid
companyName → name
tradeName   → trade_name
companyRNC  → rnc
companyType → type
status      → status (Activo → active, Cancelado → cancelled, Suspendido → suspended)
companyAddress → address
province    → province
municipality → municipality
companyPhone → phone
companyEmail → email
colorMarca → color_marca
gradientEnabled → gradient_enabled
logoUrl    → logo_url
logoBase64 → logo_base64
regimenFiscal → regimen_fiscal
certificateName → certificate_name
certificateContent → certificate_content
certificatePassword → certificate_password
planId     → plan_id
plan_version → plan_version
posEnabled → pos_enabled
productionEnabled → production_enabled
sandboxEnabled → sandbox_enabled
createdBy  → created_by
createdAt  → created_at
updatedBy  → updated_by
updatedAt  → updated_at
stampUrl   → stamp_url
signatureUrl → signature_url
nextCertificateNumber → next_certificate_number
```

#### Consultas clave

```python
# Obtener compañías de un owner
db.collection("companies").where("owner_uid", "==", uid)

# Obtener compañía por ID
db.collection("companies").document(company_id).get()

# Crear compañía
db.collection("companies").document(company_id).set(profile)
```

---

### 2.2 User (Usuario)

**Colección:** `users/{uid}/config/user_profile`  
**Clave primaria:** `uid` (Firebase Auth UID)  
**Alcance:** Global  
**Estrategia de migración:** Se modifican campos existentes. No se mueve.

#### Campos actuales que se conservan

- `uid`, `name`, `email`, `phone`, `address`, `role`
- `permissions` (dict con permisos globales)
- `two_factor_enabled`, `two_factor_secret`, `backup_codes`
- `posSupervisorPin`, `profileImageUrl`
- `createdAt`

#### Campos que se agregan

```python
{
    # ... campos existentes se conservan ...

    # === Nuevos campos ===
    "default_company_id": "comp_a1b2c3d4...",  # Compañía por defecto al login

    # associated_companies se elimina progresivamente.
    # Se reemplaza por company_memberships como fuente de verdad.
    "associated_companies": [                   # ← Se mantiene durante migración
        {"company_id": "comp_001", "role": "owner"},
        {"company_id": "comp_002", "role": "admin"}
    ]
}
```

#### Migración de campos

```
Campo actual → Nuevo comportamiento
───────────────────────────────────────
ownerUID    → Se resuelve desde selected_company_id. No se usa como pivote.
              Se conserva en el perfil para compatibilidad durante migración.
canManageOwnCompany → Se conserva. Indica si el usuario puede tener su propia compañía.
associated_companies → Se migra de ownerUID → company_id. Luego se reemplaza por
                        consulta a company_memberships.
```

---

### 2.3 CompanyMembership (Membresía)

**Colección:** `company_memberships/{membershipId}`  
**Clave primaria:** `membershipId` (UUID)  
**Alcance:** Global (colección raíz)  
**Estrategia de migración:** Poblada por script one-time desde `associated_companies` + `team`.

```python
{
    "id": "mem_a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "uid": "firebase_uid_del_usuario",
    "company_id": "comp_a1b2c3d4...",
    "role": "owner",                     # owner | admin | vendedor | contador | consulta | personalizado
    "permissions": {                     # Permisos específicos de esta compañía
        "canInvoice": true,
        "canPayroll": true,
        "canEmployees": true,
        "canTSS": false,
        "canDGII": false,
        ...
    },
    "assigned_branches": [],             # [] = todas; [id1, id2] = restringido
    "status": "active",                  # active | inactive
    "invited_by": "firebase_uid_quien_invito",
    "created_at": "2026-07-22T12:00:00Z",
    "updated_at": "2026-07-22T12:00:00Z"
}
```

#### Consultas clave

```python
# Compañías a las que un usuario tiene acceso
db.collection("company_memberships").where("uid", "==", uid)

# Miembros de una compañía
db.collection("company_memberships").where("company_id", "==", company_id)

# Verificar acceso
db.collection("company_memberships")\
  .where("uid", "==", uid)\
  .where("company_id", "==", company_id)\
  .limit(1).get()
```

#### Migración desde `associated_companies`

Cada entrada en `associated_companies` se convierte en un documento `company_memberships`:

```python
# Antes (en user_profile):
associated_companies = [
    {"ownerUID": "uid123", "companyName": "Empresa A", "role": "owner"}
]

# Después (en company_memberships):
{
    "uid": "uid_del_usuario",
    "company_id": "comp_a1b2...",
    "role": "owner",
    "permissions": {...},
    "assigned_branches": [],
    "status": "active",
    "created_at": "..."
}
```

---

### 2.4 Branch (Sucursal)

**Colección destino:** `companies/{companyId}/branches/{branchId}`  
**Colección origen:** `users/{ownerUID}/branches/{branchId}` (production) / `sandbox_branches` (sandbox)  
**Clave primaria:** `branchId` (string, como hoy)  
**Alcance:** Por compañía (subcolección)  
**Estrategia de migración:** **Primero en migrar** (riesgo bajo).

**Documento (sin cambios estructurales):**

```python
{
    "id": "branch_001",
    "name": "Sucursal Principal",
    "code": "SP-001",
    "address": "Santo Domingo, RD",
    "isDefault": true,
    "createdAt": "2026-01-01T12:00:00Z"
}
```

#### Plan de migración

```
Fase 1: Copia
  - Al leer branches, leer de companies/{companyId}/branches.
  - Si no existe, leer de users/{ownerUID}/branches como fallback.
  - Al escribir, escribir en AMBOS (companies + users).

Fase 2: Corte
  - Dejar de leer de users/{ownerUID}/branches.
  - Dejar de escribir en users/{ownerUID}/branches.

Fase 3: Limpieza
  - Eliminar datos de users/{ownerUID}/branches (opcional).
```

---

### 2.5 Employee (Empleado de RRHH)

**Colección destino:** `companies/{companyId}/employees/{employeeId}`  
**Colección origen:** `users/{ownerUID}/employees/{employeeId}`  
**Clave primaria:** `employeeId` (string, como hoy)  
**Alcance:** Por compañía (subcolección)  
**Estrategia de migración:** **Quinta en migrar** (riesgo medio).

**Documento (con `company_id` como campo obligatorio):**

```python
{
    "id": "emp_001",
    "company_id": "comp_a1b2c3...",       # ← OBLIGATORIO
    "cedula": "00123456789",
    "firstName": "Juan",
    "firstLastName": "Pérez",
    ...  # (el resto del Employee model se mantiene igual)
}
```

#### Restricciones

- `company_id` es **obligatorio**. Un empleado pertenece a **exactamente una compañía**.
- Si la misma persona física trabaja en dos compañías, se crean dos registros distintos:
  `companies/A/employees/emp001` y `companies/B/employees/emp045`.
- Cada registro es independiente: TSS, autodeterminación, novedades, ISR, prestaciones y liquidaciones se calculan por compañía.

---

### 2.6 Payroll (Nómina)

**Colección destino:** `companies/{companyId}/payrolls/{payrollId}`  
**Colección origen:** `users/{ownerUID}/payrolls/{payrollId}`  
**Clave primaria:** `payrollId`  
**Alcance:** Por compañía (subcolección)  
**Estrategia de migración:** **Sexta en migrar** (riesgo alto).

**Documento (sin cambios estructurales):**

```python
{
    "id": "pay_001",
    "company_id": "comp_a1b2c3...",       # ← Nuevo campo
    "period": "2026-06",
    "type": "regular",
    "employees": [...],
    "totals": {...},
    "status": "generated",
    ...
}
```

---

### 2.7 Team (Colaboradores internos)

**Colección destino:** `companies/{companyId}/team/{userUid}`  
**Colección origen:** `users/{ownerUID}/team/{userUid}`  
**Clave primaria:** `userUid`  
**Alcance:** Por compañía (subcolección)  
**Estrategia de migración:** **Cuarta en migrar** (antes que empleados, riesgo bajo).

> **Razón:** Team es más simple (invitaciones, roles, permisos, accesos). No tiene impacto fiscal.
> Si algo sale mal, un usuario que no puede entrar es menos grave que una nómina mal calculada.
> Mover Team primero valida: CompanyMembership, CompanyContext, selección de compañía y permisos.

**Documento (sin cambios estructurales):**

```python
{
    "uid": "firebase_uid",
    "name": "María García",
    "email": "maria@example.com",
    "role": "admin",
    "permissions": {...},
    "status": "active",
    "createdAt": "2026-01-01T12:00:00Z"
}
```

---

## 3. CompanyContext (Clase de contexto)

### Propósito

Evitar que el código pase `owner_uid` suelto como string. Todas las operaciones de negocio reciben un `CompanyContext` con la compañía activa.

```python
class CompanyContext:
    company_id: str
    owner_uid: str        # Para compatibilidad durante migración
    company_name: str
    rnc: str
    role: str             # Rol del usuario actual en esta compañía
    permissions: dict     # Permisos del usuario actual en esta compañía
    is_sandbox: bool      # ¿Estamos en sandbox?
    branch_id: str | None # Sucursal seleccionada
```

### Cómo se obtiene

```python
# En app/__init__.py — before_request:
def get_current_company() -> CompanyContext | None:
    company_id = session.get('selected_company_id')
    if not company_id:
        return None

    company = DatabaseService.get_company(company_id)
    if not company:
        return None

    membership = DatabaseService.get_membership(session['user']['uid'], company_id)
    if not membership:
        return None

    return CompanyContext(
        company_id=company_id,
        owner_uid=company['owner_uid'],
        company_name=company['name'],
        rnc=company['rnc'],
        role=membership['role'],
        permissions=membership.get('permissions', {}),
        is_sandbox=session.get('is_sandbox_mode', False),
        branch_id=session.get('selected_branch_id'),
    )


# En cada ruta, en lugar de:
uid = session.get("selected_owner_uid", "") or session.get("user", {}).get("ownerUID", "")
employees = DatabaseService.get_employees(uid)

# Se escribe:
ctx = get_current_company()
employees = DatabaseService.get_employees(ctx.company_id)
```

### Compatibilidad durante migración

```python
# Para código legacy que todavía usa owner_uid:
def resolve_owner_uid(company_id: str) -> str | None:
    company = DatabaseService.get_company(company_id)
    return company['owner_uid'] if company else None

# En before_request:
if 'selected_company_id' in session:
    company = DatabaseService.get_company(session['selected_company_id'])
    if company:
        session['user']['ownerUID'] = company['owner_uid']
```

---

## 4. Flujo de Autenticación y Selección de Compañía

### Login

```
Usuario ingresa credenciales
  ↓
Firebase Auth verifica
  ↓
Cargar perfil de usuario (users/{uid}/config/user_profile)
  ↓
Obtener membresías (company_memberships.where("uid", uid))
  ↓
Si membresías == 0:
  → Error: "No tienes acceso a ninguna compañía"
Si membresías == 1:
  → session["selected_company_id"] = única compañía
  → Redirigir a dashboard
Si membresías > 1:
  → Si existe default_company_id en perfil:
      → session["selected_company_id"] = default_company_id
      → Redirigir a dashboard
  → Si no existe default_company_id:
      → Mostrar pantalla de selección de compañía
      → Usuario selecciona → session["selected_company_id"]
      → Opcional: "Recordar mi selección" → guarda default_company_id
```

### Cambio de compañía

```
Usuario hace clic en "Cambiar Empresa" (top bar)
  ↓
GET /select-company  (página completa, como hoy)
  ↓
Muestra lista de compañías del usuario (desde company_memberships)
  ↓
Cada compañía muestra: nombre + RNC (ej. "Empresa ABC, SRL — RNC: 131234567")
  ↓
Usuario selecciona una compañía
  ↓
POST /select-company { company_id: "comp_001" }
  ↓
session["selected_company_id"] = "comp_001"
  ↓
Redirigir a dashboard
```

### Logout

```
session.pop("selected_company_id", None)
session.clear()
```

---

## 5. Auditoría

### Eventos a registrar

| Evento | Módulo | Acción |
|---|---|---|
| Crear compañía | `Compañías` | `CREATE` |
| Actualizar compañía | `Compañías` | `UPDATE` |
| Cambiar estado compañía | `Compañías` | `UPDATE` |
| Usuario cambia de compañía | `Sesión` | `UPDATE` |
| Invitar colaborador a compañía | `Compañías` | `CREATE` |
| Remover colaborador de compañía | `Compañías` | `DELETE` |
| Actualizar membresía | `Compañías` | `UPDATE` |

### Almacenamiento

Los logs de auditoría se almacenan en:

```
companies/{companyId}/audit_logs/{logId}
```

Esto asegura que cada compañía tiene su propio registro de auditoría aislado.

### Formato del log

```python
{
    "id": "log_uuid",
    "company_id": "comp_001",
    "action": "CREATE",           # CREATE | UPDATE | DELETE | VIEW | SWITCH_COMPANY
    "module": "Compañías",
    "entity_id": "comp_001",
    "entity_label": "Empresa A SRL",
    "performed_by": "Juan Pérez",
    "performed_by_uid": "firebase_uid",
    "performed_by_email": "juan@example.com",
    "before": {...},              # Snapshot antes del cambio (UPDATE)
    "after": {...},               # Snapshot después del cambio
    "ip_address": "...",
    "user_agent": "...",
    "timestamp": "2026-07-22T12:00:00Z",
}
```

---

## 6. Orden de Migración por Módulo

| # | Módulo | Riesgo | Estrategia |
|---|---|---|---|
| 0 | **Compañías** (creación) | Bajo | Crear colección `companies/`. Poblar con script one-time. |
| 1 | **Sucursales** | Bajo | Copy-first: escribir en ambos, leer de nuevo, cortar después. |
| 2 | **Campos dinámicos** | Bajo | Misma estrategia que sucursales. |
| 3 | **Departamentos / Puestos** | Bajo | Misma estrategia. |
| 4 | **Team** (colaboradores) | Bajo | Copy-first. Valida CompanyContext y membresías antes de tocar RRHH. |
| 5 | **Empleados** | Medio | Copy-first. Requiere actualizar referencias en nóminas. |
| 6 | **Reclutamiento** | Medio | Copy-first. |
| 7 | **Nómina** | Alto | Copy-first + pruebas exhaustivas. Rollback plan definido. |
| 8 | **TSS** | Muy alto | Último en migrar. Solo después de validar nómina en producción. |
| 9 | **DGII / e-CF** | Muy alto | Último en migrar. Solo después de validar TSS. |

### Sandbox

Los datos sandbox se migran exactamente igual que producción, manteniendo estructuras paralelas:

```
companies/{companyId}/branches          → producción
companies/{companyId}/sandbox_branches  → sandbox

companies/{companyId}/invoices          → producción
companies/{companyId}/sandbox_invoices  → sandbox
```

**Regla:** No mezclar sandbox con producción jamás. Mantener colecciones paralelas aunque parezcan duplicadas. Esto evita errores donde una prueba contamina datos reales.

### Estrategia de Copy-First

```
Fase 1 (Copiar):
  - Al leer: leer de la nueva ubicación (companies/{companyId}/{collection}).
    Si no existe, leer de la vieja (users/{ownerUID}/{collection}) como fallback.
  - Al escribir: escribir en AMBOS lados.
  - Validar consistencia periódicamente.

Fase 2 (Corte):
  - Dejar de leer de la vieja ubicación.
  - Dejar de escribir en la vieja ubicación.
  - Monitorear errores.

Fase 3 (Limpieza):
  - Eliminar datos viejos después de N días sin errores.
```

---

## 7. Glosario

| Término | Definición |
|---|---|
| **Owner** | Persona física que posee una o más compañías. Es un usuario con `role=owner` y `canManageOwnCompany=true`. |
| **Compañía** | Entidad legal independiente con RNC propio. Tiene sus propios empleados, nóminas, TSS, facturación. |
| **Colaborador** | Usuario que tiene acceso a una o más compañías sin ser owner. |
| **Membresía** | Relación entre un usuario y una compañía. Define rol y permisos. |
| **Grupo** | Conjunto de compañías que pertenecen a un mismo owner. No es una entidad separada; se consulta vía `companies.where("owner_uid", uid)`. |
| **Compañía default** | Compañía que se selecciona automáticamente al iniciar sesión. Se guarda en `user_profile.default_company_id`. |
| **Contexto activo** | La compañía actualmente seleccionada en la sesión. `session["selected_company_id"]`. |
| **Copy-first** | Estrategia de migración donde los datos se escriben en ambas ubicaciones (vieja y nueva) antes de cortar a la nueva. |

---

## 8. Fuera de Alcance v1

| Funcionalidad | Motivo |
|---|---|
| **Transferir compañía a otro owner** | Implica cambio de propiedad, auditoría, permisos, facturación, certificados DGII, membresías e historial. Funcionalidad completa por sí sola. |
| **Compañías canceladas que generan nóminas** | Violaría el invariante #8. Una compañía cancelada no puede generar actividad. |
| **Empleado compartido entre compañías** | Cada compañía es una entidad legal independiente. El empleado tiene dos relaciones laborales distintas. |

> `transfer_company(company_id, new_owner_uid)` puede implementarse en el futuro como una funcionalidad independiente.

---

## 9. Invariantes del Sistema

Estas reglas deben cumplirse en todo momento. Son más importantes que cualquier diagrama.

1. **Toda compañía tiene exactamente un owner activo.**
2. **Todo employee pertenece a exactamente una compañía.** `employee.company_id` es obligatorio.
3. **Toda nómina pertenece a exactamente una compañía.**
4. **Todo company_membership referencia una compañía existente** (`company_id` existe en `companies/`).
5. **Todo company_membership referencia un usuario existente** (`uid` existe en Firebase Auth).
6. **El `selected_company_id` en sesión siempre debe existir en `company_memberships` del usuario autenticado.**
7. **Los datos sandbox nunca se mezclan con producción.** Colecciones paralelas siempre.
8. **Una compañía cancelada no puede generar nóminas ni comprobantes fiscales.**
9. **Un usuario sin `company_memberships` activas no puede acceder al sistema.**
10. **El `owner_uid` de una compañía no cambia.** (Fuera de alcance v1.)

### Validación de invariantes

```python
# Ejemplo: validar invariante #6 en before_request:
def _validate_company_access():
    if 'selected_company_id' in session and 'user' in session:
        uid = session['user']['uid']
        company_id = session['selected_company_id']
        membership = DatabaseService.get_membership(uid, company_id)
        if not membership or membership.get('status') != 'active':
            # Membresía inválida — forzar selección
            session.pop('selected_company_id', None)
            return redirect(url_for('web_auth.select_company'))
    return None
```
