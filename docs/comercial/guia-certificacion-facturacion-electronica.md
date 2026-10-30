# Guía Completa de Habilitación para Facturación Electrónica (e-CF) con VykOne

> **Dirigido a:** Clientes, administradores de empresas y contadores  
> **Objetivo:** Guiarte paso a paso desde la obtención de tu Firma Digital hasta completar los 15 pasos del proceso de certificación de la DGII para emitir Comprobantes Fiscales Electrónicos (e-CF) de forma rápida y sencilla con **VykOne ERP**.  
> **Marco Legal:** Ley No. 32-23 de Facturación Electrónica de la República Dominicana.

---

## 1. Introducción y Prerrequisitos Esenciales

Bajo la **Ley 32-23**, la República Dominicana estableció la obligatoriedad gradual de la facturación electrónica para todos los contribuyentes. Con la **Facturación Electrónica (e-CF)**, cada factura se genera en formato digital **XML**, se firma criptográficamente y viaja a la DGII en milisegundos para recibir un **Timbre Electrónico con código QR**.

### ⚠️ Prerrequisitos Esenciales (Tener a mano antes de iniciar):

Antes de comenzar el proceso de registro y certificación, tu empresa debe contar obligatoriamente con los siguientes cuatro elementos:

1. **RNC Activo y al Día:** Tu Registro Nacional de Contribuyentes (RNC) debe estar activo en la DGII y sin omisiones ni deudas pendientes de declaraciones juradas (IT-1, IR-2 / IR-1).
2. **Acceso a la Oficina Virtual (OFV):** Usuario y contraseña activos en el portal de la [Oficina Virtual de la DGII](https://oficinavirtual.dgii.gov.do/).
3. **Representante Legal Registrado:** Los datos del titular o apoderado legal deben coincidir exactamente con los registrados ante la administración tributaria.
4. **Certificado de Firma Digital (.p12 / .pfx):** Certificado digital para procedimientos tributarios emitido por una entidad autorizada por INDOTEL ([DigiFirma CCPSD](https://digifirma.camarasantodomingo.do/) o [Avansi](https://www.avansi.com.do/)) junto con su contraseña privada.

### ¿Por qué hacerlo con VykOne?
El proceso de certificación técnica de la DGII puede requerir meses de desarrollo y complejas validaciones XSD. **VykOne ya tiene toda la infraestructura técnica construida y homologada**. 

A través del **Asistente de Certificación de VykOne** (`/certificacion`), el sistema:
1. Firma automáticamente los archivos XML requeridos con tu certificado digital.
2. Lee los archivos de prueba de la DGII y genera todas las facturas de prueba sin errores de cálculo.
3. Se conecta directamente a los servidores de la DGII vía API.
4. Provee los servicios web de recepción y aprobación comercial en la nube sin que tengas que configurar servidores propios.

---

## 2. Obtención y Carga de la Firma Digital

La DGII exige un **Certificado Digital de Persona Física para Procesos Tributarios** emitido por una entidad de certificación acreditada por el **INDOTEL** (Instituto Dominicano de las Telecomunicaciones).

El certificado se entrega como un archivo con extensión **`.p12`** o **`.pfx`** acompañado de una **contraseña segura**.

### Proveedores Oficiales Acreditados:

1. **[DigiFirma — Cámara de Comercio de Santo Domingo (CCPSD)](https://digifirma.camarasantodomingo.do/)**
   * **Enlace directo:** [Solicitar en DigiFirma](https://digifirma.camarasantodomingo.do/)
   * **Sitio institucional:** [Cámara de Santo Domingo](https://www.camarasantodomingo.do/digifirma/)
   * **Modalidad:** Solicitud 100% en línea o presencial.
   * **Tipo a solicitar:** *Certificado de Persona Física para Procedimientos Tributarios*.

2. **[Avansi — Certificados Digitales](https://www.avansi.com.do/)**
   * **Enlace directo:** [Solicitar en Avansi](https://www.avansi.com.do/)
   * **Modalidad:** Solicitud en línea con verificación de identidad remota.
   * **Tipo a solicitar:** *Firma Digital para Facturación Electrónica DGII*.

3. **[FirmaGob / OGTIC](https://optic.gob.do/)** *(Aplica únicamente a instituciones públicas y gubernamentales)*

### Cargar tu Firma Digital en VykOne

Una vez recibido tu archivo `.p12`:

1. Inicia sesión en tu cuenta de **VykOne**.
2. Dirígete a **Configuración** (`⚙️`) &rarr; pestaña **Firma Digital** (o directamente en el **Paso 1** del Asistente de Certificación).
3. Arrastra tu archivo `.p12` o `.pfx` y escribe la **contraseña** asignada al certificado.
4. Haz clic en **Cargar y Validar**.
5. VykOne validará la vigencia, el titular del certificado y el RNC emisor, dejándolo listo para firmar todas las transacciones de manera cifrada y segura.

---

## 3. Los 15 Pasos de Certificación DGII (Explicados con VykOne)

La DGII establece un flujo formal de 15 pasos para autorizar a un contribuyente como **Emisor Electrónico**. VykOne cuenta con un módulo dedicado accesible desde el menú lateral en **Certificación DGII**, que simplifica cada uno de estos pasos:

```
[ Fase 1: Postulación ]  ──▶  [ Fase 2: Set de Pruebas ]  ──▶  [ Fase 3: Conectividad Web ]  ──▶  [ Fase 4: Producción ]
(Paso 1)                      (Pasos 2 al 6)                  (Pasos 7 al 12)                 (Pasos 13 al 15)
```

---

### Fase 1: Postulación y Registro

#### Paso 1: Registrado (Solicitud de Postulación)
* **¿Qué hace la DGII?** En la Oficina Virtual (OFV), en el apartado de *Facturación Electrónica*, seleccionas la opción de postularte como emisor electrónico. La DGII te proporciona un archivo llamado `postulacion.xml`.
* **¿Qué hace VykOne?** En el **Paso 1 de VykOne**, arrastras el archivo `postulacion.xml`. VykOne lo firma digitalmente con tu certificado `.p12` y genera el archivo `postulacion_firmada.xml`.
* **Acción del cliente:** Descargas el XML firmado y lo subes al portal de certificación de la DGII. Al aprobarse, la DGII te da acceso al ambiente de pruebas (**CerteCF**).

---

### Fase 2: Pruebas de Datos e-CF y Simulación

#### Paso 2: Pruebas de Datos e-CF
* **¿Qué hace la DGII?** Te entrega una plantilla oficial de Excel con un set de pruebas que contiene diferentes tipos de facturas (Crédito Fiscal `E31`, Consumo `E32`, Notas de Débito `E33`, Notas de Crédito `E34`, Compras `E41`, Gastos Menores `E43`, Regímenes Especiales `E44`, Gubernamentales `E45`, Exportaciones `E46`, Pagos al Exterior `E47` y Resumen de Facturas de Consumo `RFCE`).
* **¿Qué hace VykOne?** Subes el archivo Excel directamente a VykOne. El sistema analiza automáticamente cada caso, arma los XMLs respetando la estructura exigida por la DGII, los firma y los envía automáticamente vía API a los servidores de prueba. Para los casos de subida manual (Grupo 4), VykOne te descarga los archivos listos para adjuntar en el portal.
* **Resultado:** Si todos los casos son aceptados por la DGII, el paso se marca como aprobado.

#### Paso 3: Pruebas de Datos de Aprobación Comercial
* **¿Qué es la Aprobación Comercial?** Es el mecanismo legal mediante el cual un comprador notifica si aprueba, aprueba parcialmente o rechaza comercialmente una factura recibida.
* **¿Qué hace VykOne?** VykOne genera automáticamente las respuestas electrónicas de aprobación comercial (`ACECF`) firmadas con tu certificado y las transmite a la DGII con un solo clic.

#### Paso 4: Pruebas de Simulación e-CF
* **¿Qué hace la DGII?** Evalúa la capacidad del sistema de emitir facturas en un ambiente continuo y realista.
* **¿Qué hace VykOne?** VykOne envía un lote de comprobantes de simulación a la DGII de manera desatendida, confirmando que la lógica contable, los impuestos (ITBIS) y las retenciones operan de forma estable.

#### Paso 5: Pruebas de Simulación de Representación Impresa (RI)
* **¿Qué es la Representación Impresa?** Es el documento visual (formato PDF o ticket impreso) que se entrega al cliente final.
* **¿Qué hace VykOne?** Genera las representaciones impresas en PDF de los comprobantes emitidos en el Paso 4. Cada PDF incluye:
  - Logotipo y datos fiscales de tu empresa.
  - Indicador de Comprobante Fiscal Electrónico (e-CF).
  - Código de seguridad oficial de 6 dígitos.
  - **Código QR** estandarizado que redirige a la consulta de validez fiscal en el portal de la DGII.

#### Paso 6: Validación de Representación Impresa
* **Acción:** Se adjuntan los PDFs generados en el portal de certificación de la DGII. Los técnicos de la DGII validan que la disposición visual, el código QR y los importes coincidan exactamente con la normativa técnica.

---

### Fase 3: Conectividad y Recepción de Facturas

#### Paso 7: URL de Servicios de Prueba
* **¿Qué se hace?** Se registran ante la DGII las direcciones web (endpoints) donde tu sistema escuchará y recibirá facturas electrónicas emitidas por terceros en ambiente de prueba.
* **Con VykOne:** No tienes que contratar servidores ni configurar redes. VykOne te proporciona las URLs seguras listas para copiar y pegar en el portal de la DGII.

#### Paso 8: Inicio de Prueba de Recepción e-CF
* **Acción:** Indicar en el portal de la DGII que el sistema de tu empresa está listo para comenzar a recibir comprobantes electrónicos emitidos por otros contribuyentes o simuladores de prueba.

#### Paso 9: Recepción e-CF
* **¿Qué ocurre?** La DGII envía paquetes de facturas electrónicas hacia tu servidor de VykOne.
* **Con VykOne:** El motor de VykOne recibe los XMLs entrantes, valida la firma electrónica del emisor, verifica el RNC y envía automáticamente el mensaje de **Acuse de Recibo** a la DGII.

#### Paso 10: Inicio de Prueba de Recepción de Aprobación Comercial
* **Acción:** Se declara en el portal que tu empresa está disponible para recibir las aprobaciones o rechazos comerciales que tus clientes te envíen.

#### Paso 11: Recepción de Aprobación Comercial
* **Con VykOne:** VykOne recibe los acuses de aprobación o rechazo comercial de prueba enviados por la DGII y actualiza el estatus de las facturas en tu panel.

#### Paso 12: URL de Servicios de Producción
* **¿Qué se hace?** Se registran las URLs definitivas que se usarán en el ambiente en vivo (producción). VykOne provee la infraestructura de alta disponibilidad en la nube para garantizar que nunca pierdas una factura emitida o recibida.

---

### Fase 4: Aprobación Legal y Pase a Producción

#### Paso 13: Declaración Jurada
* **¿En qué consiste?** El representante legal de la empresa declara formalmente bajo fe de juramento que las pruebas se ejecutaron conforme a las normativas técnicas y legales de la DGII.
* **¿Qué hace VykOne?** En el Paso 13 del asistente, ingresas el nombre y cédula del representante legal. VykOne construye el archivo XML de la Declaración Jurada, lo firma con tu certificado digital y lo descarga listo para subir a la DGII.

#### Paso 14: Verificación de Estatus
* **¿Qué evalúa la DGII?** La DGII realiza una verificación final de cumplimiento:
  - RNC con estatus Activo y en Régimen Ordinario.
  - Declaraciones de impuestos al día (IT-1, IR-2 / IR-1).
  - Sin alertas de inconsistencia ni bloqueos de NCF.
  - Representante legal debidamente registrado en los registros de la DGII.

#### Paso 15: Finalizado — Emisor Electrónico Autorizado
* **¡Felicidades!** La DGII emite la **Resolución de Autorización** que certifica formalmente a tu empresa como **Emisor y Receptor Electrónico de e-CF**.

---

## 4. El Día Después: Puesta en Marcha en Producción con VykOne

Una vez alcanzado el Paso 15, tu empresa está legalmente facultada para emitir e-CF. Solo quedan dos pasos operativos sencillos:

### 1. Solicitar tus secuencias electrónicas (e-NCF) en la DGII
Ingresa a tu **Oficina Virtual DGII** y solicita las secuencias que tu negocio necesite:
* **E31** — Factura de Crédito Fiscal Electrónica (B2B / empresas)
* **E32** — Factura de Consumo Electrónica (B2C / clientes finales)
* **E33** — Nota de Débito Electrónica
* **E34** — Nota de Crédito Electrónica
* **E41** — Comprobante de Compras Electrónico
* **E43** — Comprobante para Gastos Menores Electrónico
* **E44** — Comprobante para Regímenes Especiales Electrónico
* **E45** — Comprobante Gubernamental Electrónico

### 2. Registrar los rangos en VykOne
En VykOne, ve a:
> **Configuración** &rarr; **Secuencias Fiscales (e-NCF)** &rarr; **Agregar Rango**

Ingresa el prefijo (ej. `E31`), el rango inicial y final autorizado por la DGII y la fecha de vencimiento. A partir de ese momento:
* Cada factura que emitas desde el módulo de Ventas o Punto de Venta (POS) se firmará, timbrará y enviará en tiempo real a la DGII.
* Tu cliente recibirá el PDF con su código QR fiscal por correo electrónico o WhatsApp.
* La contabilidad, los libros de IVA/ITBIS y los reportes fiscales se actualizarán automáticamente.

---

## 5. Tabla Resumen del Proceso

| Etapa | Pasos | ¿Quién lo hace? | ¿Cómo ayuda VykOne? |
|---|---|---|---|
| **Prerrequisitos** | Previo | Cliente (RNC, OFV, Representante) | Guía inicial y validación de RNC. |
| **Firma Digital** | Previo | Cliente en [DigiFirma](https://digifirma.camarasantodomingo.do/) o [Avansi](https://www.avansi.com.do/) | Se sube el archivo `.p12` y VykOne valida su autenticidad y vigencia. |
| **Postulación** | Paso 1 | Cliente + VykOne | VykOne firma el XML de postulación para subirlo a la DGII. |
| **Pruebas de Datos** | Pasos 2 – 6 | VykOne (Automático) | VykOne procesa el Excel de DGII, genera los XMLs y crea los PDFs con timbre y QR. |
| **Intercambio Web** | Pasos 7 – 12 | VykOne (Infraestructura) | VykOne provee los servidores y URLs de recepción sin configuraciones complejas. |
| **Cierre y Legal** | Pasos 13 – 15 | Cliente + VykOne | VykOne genera la Declaración Jurada firmada y valida el estatus. |
| **Producción** | Go-Live | Cliente + VykOne | Se configuran los rangos de e-NCF y se emiten comprobantes electrónicos válidos. |

---

## 6. Preguntas Frecuentes (FAQ)

### ¿Cuánto tiempo dura el proceso completo de certificación?
Con un sistema sin certificar, el proceso puede tomar de 2 a 3 meses. **Con VykOne, dado que todo el motor ya está programado y probado, el proceso técnico toma entre 2 y 5 días hábiles**, dependiendo principalmente del tiempo de respuesta y revisión de los técnicos de la DGII.

### ¿Qué costo tiene el certificado digital?
El certificado digital es emitido por entidades independientes acreditadas (como DigiFirma de la Cámara de Santo Domingo o Avansi). Su costo oscila habitualmente entre US$ 50 y US$ 100 anuales según la vigencia seleccionada (1 o 2 años).

### ¿Qué ocurre si la DGII rechaza un comprobante durante las pruebas del Paso 2?
La DGII exige que el 100% de los comprobantes del set de pruebas coincidan a la perfección. Si algún caso presentara discrepancia, la DGII reinicia el set de pruebas. VykOne cuenta con un validador estricto que comprueba los datos antes de enviarlos para asegurar una tasa de éxito limpia.

### ¿Puedo probar VykOne antes de tener mi certificado digital?
Sí. VykOne incluye un **Modo Simulación (Sandbox)** que te permite crear productos, emitir facturas de prueba y entrenar a tu personal sin necesidad de un certificado real ni conexión con la DGII. Cuando obtengas tu firma, simplemente la cargas y pasas al modo oficial.

---

## 7. Enlaces y Recursos de Interés

* 🏛️ **[DGII — Portal de Facturación Electrónica](https://dgii.gov.do/cicloContribuyente/facturacion/facturacionElectronica/)**
* 💻 **[DGII — Oficina Virtual (OFV)](https://oficinavirtual.dgii.gov.do/)**
* 🔏 **[DigiFirma — Cámara de Comercio de Santo Domingo](https://digifirma.camarasantodomingo.do/)**
* 🔐 **[Avansi — Certificados Digitales en RD](https://www.avansi.com.do/)**
* ⚖️ **[INDOTEL — Autoridades de Certificación Acreditadas](https://indotel.gob.do/)**
* 🚀 **[VykOne ERP — Asistente de Certificación](https://tu-dominio.vykone.com/certificacion)**
