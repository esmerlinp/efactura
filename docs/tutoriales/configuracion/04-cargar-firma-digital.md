# Tutorial: Cargar tu firma digital

La firma digital (certificado `.p12` o `.pfx`) es necesaria para emitir
comprobantes fiscales electrónicos ante la DGII. Puedes cargarla de tres
formas.

## Durante la bienvenida (recomendado)

1. En el asistente de bienvenida, avanza hasta el paso **"Firma Digital"**.
2. Elige una de las dos opciones:
   - **Subir certificado digital**: selecciona tu archivo `.p12` / `.pfx` y
     escribe la **Contraseña del Certificado**.
   - **"Usar firma simulada (modo pruebas)"**: activa esta casilla si aún no
     tienes certificado y quieres practicar. *Recuerda que para producción
     necesitarás un certificado real.*
3. Continúa con **"Siguiente"** hasta finalizar.

## Cambiarla después desde Configuración

1. Abre el menú de **Configuración** (engranaje) y entra a **"Configuración de
   Empresa"**.
2. Busca la sección **"Certificado de Firma Digital"**.
3. Selecciona el nuevo archivo `.p12` / `.pfx`.
4. Escribe la nueva contraseña (déjala en blanco si solo quieres conservar la
   que ya está guardada).
5. Haz clic en **"Guardar Cambios"**.

Cuando el sistema reconoce el archivo, verás *"✓ Certificado cargado"* con el
nombre del archivo.

## Cargarla al intentar facturar

Si intentas emitir una factura sin certificado, el sistema te mostrará la
ventana **"Configurar Firma Digital"**:

1. Selecciona tu archivo `.p12` / `.pfx`.
2. Escribe la **Contraseña**.
3. Haz clic en **"Vincular Certificado"**.

## Posibles mensajes de error

- *"La contraseña del certificado es incorrecta"* — verifica la contraseña.
- *"El certificado digital ha expirado"* — renueva tu certificado y súbelo de
  nuevo.
- *"No existe un certificado digital configurado"* — aún no has subido ninguno.

## Ambiente de pruebas vs. producción

Puedes trabajar en **modo de prueba** con firma simulada. Antes de operar en
producción, asegúrate de subir un **certificado real válido**.
