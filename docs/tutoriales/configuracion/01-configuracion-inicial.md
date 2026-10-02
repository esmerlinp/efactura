# Tutorial: Configurar el sistema al iniciar sesión por primera vez

Al iniciar sesión por primera vez, el sistema te recibe con un **asistente de
bienvenida** que te guía paso a paso para dejar tu empresa lista. No podrás
avanzar al resto del sistema hasta completarlo.

## Asistente de bienvenida

Sigue las pantallas en orden. Los pasos marcados como opcionales se pueden
saltar y retomar más adelante.

1. **Tipo de contribuyente** — Indica si tu empresa es persona física o
   jurídica.
2. **Régimen fiscal** — Elige entre Ordinario, RST (ingresos o compras),
   Exento o Consumo. Según tu elección, el sistema configura automáticamente
   los impuestos y retenciones correctos para República Dominicana.
3. **Datos de la empresa** — Completa RNC, Razón Social, Nombre Comercial,
   dirección, provincia, municipio, teléfono y correo. Estos datos son
   obligatorios y aparecen en tus comprobantes fiscales.
4. **Firma digital** — Sube tu certificado digital (archivo **P12/PFX**) junto
   con su contraseña. Si todavía no lo tienes, marca la opción **"Usar
   simulación"** para trabajar en un ambiente de pruebas. Sin certificado
   válido no podrás emitir facturas electrónicas.
5. **Carga masiva de clientes** (opcional) — Importa tus clientes desde un
   archivo para no cargarlos uno a uno.
6. **Carga masiva de productos** (opcional) — Importa tu catálogo de productos
   o servicios.
7. **Carga masiva de transacciones** (opcional) — Importa movimientos
   históricos si ya venías trabajando con otro sistema.

Al finalizar, el asistente te lleva al **Panel principal**, ya listo para
empezar.

## Configuración recomendada después del asistente

Una vez dentro, abre el menú de **Configuración** (ícono de engranaje) para
dejar todo listo:

1. **Secuencias Fiscales** — Registra el rango de comprobantes (NCF) que te
   autorizó la DGII: tipo, prefijo, numeración inicial y final, y fecha de
   expiración. Sin una secuencia activa, las facturas quedarán en borrador.
2. **Impuestos** — Revisa ITBIS, ISC, ISR y retenciones. Ya vienen
   preconfigurados con los valores estándar de República Dominicana, pero
   verifica que coincidan con tu régimen.
3. **Usuarios y Permisos** — Invita a tu equipo y asigna un rol a cada persona
   (Administrador, Vendedor, Contador o Consulta).
4. **Empresa** — Ajusta la identidad fiscal, el certificado digital, tus
   sucursales y proyectos, y las pasarelas de pago.
5. **Logo y marca** — Personaliza el logo, los colores y el tema para que tus
   comprobantes tengan tu identidad.

## Puntos a tener en cuenta

- **Modo de prueba (sandbox)**: usa el interruptor de ambiente para practicar
  sin afectar tu operación real. Tus datos de prueba quedan separados de los de
  producción.
- **RNC y Razón Social**: se bloquean una vez emites comprobantes, así que
  verifícalos bien antes de facturar.
- **Estado de facturación**: la pantalla de estado te avisa qué te falta antes
  de emitir (por ejemplo, certificado vencido o datos incompletos).
