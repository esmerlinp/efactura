# CONTRATO DE PRESTACIÓN DE SERVICIOS — VYKONE ERP

| Campo | Detalle |
|---|---|
| **Documento** | Contrato estándar de servicios (plantilla) |
| **Código del documento** | COM-CTR-001 |
| **Versión** | 1.0 |
| **Fecha de emisión** | 17 de agosto de 2026 |
| **Clasificación** | Interna (plantilla) |
| **Responsable** | Esmerlin Paniagua Martinez — Gerente |

> **Instrucciones de uso:** esta plantilla se completa por cliente al momento de la
> contratación. Los campos entre corchetes `[___]` son obligatorios. Los anexos
> referenciados se encuentran en la carpeta `politicas/` del proveedor y forman parte
> integrante de este contrato.

---

## 1. LAS PARTES

**EL PROVEEDOR:** **VykCore Automation S.R.L.**, sociedad comercial organizada y existente
de conformidad con las leyes de la República Dominicana, con su domicilio y asiento social
principal en la ciudad de `[___]`, con Registro Nacional de Contribuyentes (RNC) número
`[___]`, representada en este acto por el señor **Esmerlin Paniagua Martinez**, dominicano,
mayor de edad, portador de la cédula de identidad y electoral número `[___]`, en su calidad
de **Gerente**; quien en lo adelante se denominará **"EL PROVEEDOR"**.

**EL CLIENTE:** `[Razón social o nombre del cliente]`, con domicilio en `[___]`, con RNC o
cédula número `[___]`, representada en este acto por `[Nombre del representante]`, portador
de la cédula de identidad y electoral número `[___]`, en su calidad de `[Cargo]`; quien en
lo adelante se denominará **"EL CLIENTE"**.

**EL PROVEEDOR** y **EL CLIENTE** se denominarán conjuntamente "LAS PARTES" e
individualmente "LA PARTE".

## 2. DECLARACIONES

1. **EL PROVEEDOR** declara: (i) que es una empresa dedicada al desarrollo, operación y
   comercialización de soluciones de software, incluyendo la plataforma **VykOne ERP**,
   sistema de facturación electrónica (e-CF) conforme a las normas de la Dirección General
   de Impuestos Internos (DGII); y (ii) que cuenta con las políticas y procedimientos de
   seguridad, contingencia, protección de datos, respaldo y asistencia descritos en los
   Anexos referidos en la cláusula 4.
2. **EL CLIENTE** declara: (i) que es un contribuyente registrado ante la DGII; (ii) que
   dispone de los insumos fiscales necesarios para operar el servicio (certificado de firma
   digital, secuencias e-NCF autorizadas); y (iii) que la información que entregará al
   proveedor es veraz, exacta y está actualizada.

## 3. OBJETO

**EL PROVEEDOR** otorga a **EL CLIENTE** una licencia de uso no exclusiva, intransferible y
temporal de la plataforma **VykOne ERP** en modalidad SaaS (Software como Servicio),
incluyendo:

1. Acceso a la plataforma web multi-tenant alojada en infraestructura de nube
   (Firebase/Google Cloud) para el plan contratado en la cláusula 6.
2. Emisión, firma digital y envío a la DGII de comprobantes fiscales electrónicos (e-CF)
   conforme a la normativa vigente.
3. Modo de contingencia y sincronización posterior conforme al **Anexo 1.2**.
4. Respaldo y recuperación de la información conforme al **Anexo 8**.
5. Asistencia técnica conforme a los niveles de servicio del **Anexo 1.4**.

## 4. DOCUMENTOS INTEGRANTES DEL CONTRATO

Forman parte integrante de este contrato los siguientes documentos, vigentes a la fecha de
firma y actualizables conforme a sus propios procedimientos de revisión:

| Anexo | Documento | Código |
|---|---|---|
| 1 | Política de Seguridad de la Información | POL-SEG-001 |
| 2 | Política de Contingencia | POL-CONT-002 |
| 3 | Política de Protección de Datos Personales | POL-PDP-003 |
| 4 | Vías de Asistencia Habilitadas (SLA) | POL-ASIS-004 |
| 5 | Información de Contacto para Requerimientos de la DGII | POL-CON-005 |
| 6 | Certificación de Seguridad | POL-CER-006 |
| 7 | Bitácora de Eventos | POL-BIT-007 |
| 8 | Procedimientos de Respaldo y Recuperación | POL-RES-008 |

En caso de contradicción entre este contrato y un anexo, prevalecerá lo establecido en este
contrato.

## 5. ALCANCE DEL SERVICIO

1. **EL CLIENTE** recibe una cuenta principal de propietario (`owner`) sobre un entorno
   multi-tenant aislado (colecciones segmentadas por empresa), con separación estricta entre
   ambiente de pruebas (sandbox) y producción, conforme al **Anexo 1.1**.
2. Las funcionalidades habilitadas dependen del plan contratado, de acuerdo con la
   comparativa de planes publicada en `https://vykcore.com/precios` y la cláusula 6.
3. **EL CLIENTE** es responsable de la gestión de usuarios, roles y permisos de su entorno,
   incluyendo el cumplimiento de la matriz de Segregación de Funciones (SoD) indicada en el
   **Anexo 1.1** (por ejemplo: no asignar a un mismo usuario los permisos de emitir y anular
   comprobantes, ni de gestionar RRHH y aprobar nóminas).
4. La habilitación del modo producción requiere completar la configuración fiscal del
   entorno (datos de empresa, RNC, certificado de firma digital y secuencias e-NCF) y la
   validación previa en ambiente de pruebas, según el plan de implementación acordado.

## 6. PLAN CONTRATADO, PRECIO Y FORMA DE PAGO

1. **EL CLIENTE** contrata el plan `[Esencial / Pro / Enterprise]` de VykOne ERP.
2. **Precio:** `[___]` por `[mes / año]`, en `[RD$ / US$]`, impuestos incluidos
   `[sí / no]`. La implementación inicial tiene un costo de `[___]` y `[incluye / no
   incluye]` capacitación.
3. **Forma de pago:** `[factura bancaria / tarjeta / transferencia]`; la facturación se
   emite `[mensual / trimestral / anual]`, pagadera dentro de los `[___]` días de su
   emisión.
4. La falta de pago dentro del plazo faculta a **EL PROVEEDOR** a suspender el servicio,
   previa notificación con `[___]` días de antelación, sin perjuicio de la recuperación de
   los comprobantes ya emitidos (exportación conforme a la cláusula 14).
5. Los precios pueden ser actualizados por **EL PROVEEDOR** con una notificación mínima de
   treinta (30) días, aplicable a partir del período de renovación siguiente.

## 7. OBLIGACIONES DEL PROVEEDOR

1. Prestar el servicio con los estándares de seguridad descritos en el **Anexo 1.1**
   (autenticación con 2FA/TOTP, cifrado TLS en tránsito y en reposo, aislamiento
   multi-tenant, bitácora de eventos).
2. Mantener el modo de contingencia y la sincronización posterior con la DGII conforme al
   **Anexo 1.2** (ventana legal de 72 horas, alerta temprana a las 48 horas).
3. Tratar los datos personales conforme a la Ley núm. 172-13 y al **Anexo 1.3**,
   garantizando los derechos de acceso, rectificación, cancelación/supresión y oposición.
4. Ejecutar los respaldos conforme al **Anexo 8** (respaldo íntegro diario, retención
   mínima de 30 días, restauración con tiempo objetivo ≤ 4 horas).
5. Atender las solicitudes de asistencia por los canales y con los tiempos del **Anexo 1.4**.
6. Mantener una bitácora de eventos con trazabilidad completa conforme al **Anexo 7**.

## 8. OBLIGACIONES DEL CLIENTE

1. Suministrar información fiscal veraz y completa (datos de empresa, RNC, régimen fiscal,
   datos de facturación) y mantenerla actualizada.
2. Disponer y mantener vigente su certificado de firma digital (PKCS#12) y sus secuencias
   e-NCF autorizadas por la DGII. **EL PROVEEDOR** no es responsable por rechazos de la
   DGII derivados de certificados vencidos o revocados, secuencias agotadas o inválidas, o
   datos inexactos del contribuyente o de sus clientes.
3. Hacer uso legítimo de la plataforma y custodiar las credenciales de acceso; activar la
   autenticación en dos pasos (2FA) para los usuarios de su entorno.
4. Gestionar usuarios, roles y permisos respetando la matriz SoD del **Anexo 1.1**.
5. Pagar puntualmente los montos pactados.
6. Responder oportunamente los requerimientos del plan de implementación (información de
   clientes, productos, precios, pruebas y aprobaciones).

## 9. NIVELES DE SERVICIO (SLA)

Los tiempos de compromiso de respuesta y resolución son los establecidos en el **Anexo 1.4**:

| Nivel | Descripción | Primera respuesta | Resolución |
|---|---|---|---|
| Crítico | Indisponibilidad de emisión e-CF | 1 hora | 4 horas |
| Alto | Errores en emisión, contingencia, rechazos | 2 horas | 8 horas (día hábil) |
| Normal | Consultas, configuración, dudas operativas | 4 horas | 24 horas (día hábil) |
| Bajo | Solicitudes de información, sugerencias | 8 horas | 72 horas |

Los tiempos se computan en horario hábil (lunes a viernes, 8:00 a.m. – 6:00 p.m., hora de
República Dominicana). Los incidentes de recepción de comprobantes e-CF por la DGII se
escalan de inmediato conforme al **Anexo 1.2**.

## 10. PROPIEDAD INTELECTUAL

1. La plataforma VykOne ERP, su código fuente, marcas, diseños y documentación son
   propiedad exclusiva de **EL PROVEEDOR**. Este contrato no transfiere titularidad alguna.
2. Los datos ingresados por **EL CLIENTE** (clientes, productos, comprobantes, asientos
   contables, nómina) son de titularidad exclusiva de **EL CLIENTE**, y **EL PROVEEDOR** los
   tratará únicamente para la prestación del servicio y el cumplimiento de obligaciones
   legales.

## 11. CONFIDENCIALIDAD Y PROTECCIÓN DE DATOS

1. **LAS PARTES** se obligan a guardar confidencialidad sobre la información de la otra
   parte a la que tengan acceso con ocasión de este contrato, durante su vigencia y por dos
   (2) años posteriores a su terminación.
2. El tratamiento de datos personales se rige por la Ley núm. 172-13 y el **Anexo 1.3**.
   **EL CLIENTE**, como responsable del tratamiento respecto de sus clientes y empleados,
   autoriza a **EL PROVEEDOR** a tratarlos como encargado, exclusivamente para operar el
   servicio de facturación electrónica.
3. Los datos de facturación electrónica se conservan conforme a los plazos legales
   tributarios; la bitácora de auditoría se conserva sin eliminación automática
   (**Anexo 7**).

## 12. RESPONSABILIDAD Y LIMITACIONES

1. **EL PROVEEDOR** responderá por los daños directos causados por dolo o culpa grave. En
   ningún caso la responsabilidad total de **EL PROVEEDOR** por cualquier concepto superará
   el importe pagado por **EL CLIENTE** en los tres (3) meses anteriores al hecho que la
   origine.
2. **EL PROVEEDOR** no será responsable por: (i) rechazos o sanciones de la DGII
   originados por datos, certificados o secuencias del contribuyente; (ii) el uso indebido
   de la plataforma por usuarios del entorno del cliente; (iii) interrupciones del servicio
   de recepción de la DGII, en cuyo caso aplicará el modo de contingencia del **Anexo 1.2**;
   (iv) fuerza mayor o caso fortuito; (v) pérdidas indirectas, lucro cesante o pérdida de
   oportunidad.
3. **EL CLIENTE** es el único responsable ante la DGII por la exactitud de sus
   declaraciones y comprobantes, y por la gestión de sus secuencias e-NCF y certificados.

## 13. VIGENCIA Y RENOVACIÓN

1. Este contrato entra en vigor en la fecha de firma y tiene una vigencia inicial de
   `[___]` `[meses / años]`, renovable automáticamente por períodos iguales, salvo
   notificación escrita de cualquiera de **LAS PARTES** con al menos treinta (30) días de
   antelación a la fecha de renovación.
2. Cualquiera de **LAS PARTES** podrá resolver este contrato por incumplimiento grave de la
   otra parte, previa notificación escrita otorgando un plazo de quince (15) días para
   subsanar, sin que la subsanación se verifique.

## 14. TERMINACIÓN Y DEVOLUCIÓN DE DATOS

1. A la terminación del contrato, por cualquier causa, **EL CLIENTE** dispondrá de un plazo
   de `[___]` días para exportar su información mediante las funcionalidades de la
   plataforma descritas en el **Anexo 8** (respaldo íntegro JSON, ZIP con CSV por módulo,
   exportación de datos de la empresa y exportaciones contables y de nómina).
2. Transcurrido ese plazo, **EL PROVEEDOR** podrá eliminar los datos del entorno del
   cliente conforme a su política de retención, sin responsabilidad ulterior, salvo los
   plazos legales de conservación tributaria aplicables.

## 15. CESIONES Y SUBCONTRATACIÓN

**EL CLIENTE** no podrá ceder este contrato sin autorización escrita de **EL PROVEEDOR**.
**EL PROVEEDOR** podrá subcontratar servicios de infraestructura (Google Cloud/Firebase)
garantizando los mismos niveles de seguridad y protección de datos pactados.

## 16. NOTIFICACIONES

Toda notificación se realizará a los correos electrónicos declarados por **LAS PARTES** en
la hoja de datos del cliente y al correo de soporte `support@vykcore.com`, y se tendrá por
efectuada a la confirmación de envío. Los datos de contacto del proveedor ante la DGII son
los del **Anexo 1.5**.

## 17. LEGISLACIÓN APLICABLE Y JURISDICCIÓN

Este contrato se rige por las leyes de la República Dominicana. **LAS PARTES** se someten
expresamente a la jurisdicción de los tribunales ordinarios del Distrito Judicial de
`[___]`, renunciando a cualquier otro fuero que pudiera corresponderles.

## 18. ACEPTACIÓN Y FIRMA

En señal de conformidad con todas y cada una de las cláusulas precedentes, **LAS PARTES**
firman el presente contrato en dos (2) ejemplares de un mismo tenor y efecto, en la ciudad
de `[___]`, a los `[___]` días del mes de `[___]` del año `[___]`.

| | Nombre | Cargo | RNC/Cédula | Firma | Fecha |
|---|---|---|---|---|---|
| **EL PROVEEDOR** | Esmerlin Paniagua Martinez | Gerente | VykCore Automation S.R.L. | ____________________ | `[___]` |
| **EL CLIENTE** | `[___]` | `[___]` | `[___]` | ____________________ | `[___]` |

---

## HOJA DE DATOS DEL CLIENTE (COMPLETAR AL FIRMAR)

| Campo | Dato |
|---|---|
| Razón social / nombre | `[___]` |
| RNC / Cédula | `[___]` |
| Régimen fiscal | `[___]` |
| Domicilio | `[___]` |
| Teléfono | `[___]` |
| Correo de notificaciones | `[___]` |
| Representante | `[___]` |
| Plan contratado | `[Esencial / Pro / Enterprise]` |
| Precio y periodicidad | `[___]` |
| Usuarios contratados | `[___]` |
| Fecha de inicio del servicio | `[___]` |
| Fecha objetivo de go-live | `[___]` |
| Certificado de firma digital | `[Cargado en plataforma: sí / no]` |
| Secuencias e-NCF | `[Autorizadas: sí / no]` |
| Plan de implementación aplicable | `docs/comercial/plan-implementacion-clientes.md` |

---

## Control de versiones

| Versión | Fecha | Descripción del cambio | Elaborado por | Aprobado por |
|---|---|---|---|---|
| 1.0 | 2026-08-17 | Emisión inicial de plantilla estándar | Esmerlin Paniagua Martinez | Esmerlin Paniagua Martinez |
