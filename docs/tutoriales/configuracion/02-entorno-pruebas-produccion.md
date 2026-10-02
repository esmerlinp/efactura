# Tutorial: Entorno de pruebas (sandbox) y producción

VykOne tiene dos entornos separados: **Sandbox (pruebas)** y **Producción
(real)**. Cambiar entre ellos te permite practicar sin afectar tu operación
fiscal.

## ¿Qué es cada entorno?

- **Sandbox (pruebas)**: se conecta a los servicios de prueba de la DGII. Los
  comprobantes que emitas **no tienen validez fiscal** y no cuentan como reales.
- **Producción (real)**: se conecta a los servicios reales de la DGII. Los
  comprobantes tienen validez fiscal y requieren certificado digital real y
  secuencias fiscales autorizadas.

## Cómo saber en qué entorno estás

- Si estás en Sandbox, verás la etiqueta **"Sandbox"** junto al nombre del
  producto en el menú lateral.
- En un entorno de prueba, también aparece un aviso naranja indicando que los
  datos son de prueba.
- Los documentos emitidos en Sandbox muestran la marca de agua
  **"SIN VALOR COMERCIAL"**.

## Entrar en modo de pruebas

1. Durante la bienvenida o la configuración, busca el banner **"¿Solo deseas
   probar el sistema?"**.
2. Haz clic en **"Omitir y entrar en Modo Pruebas"**.
3. El sistema te llevará al panel operando con un RNC de simulación, sin
   necesidad de certificado real.

## Pasar a producción

1. Verifica que tengas listo:
   - Un **certificado digital real** válido.
   - Tus **secuencias fiscales** autorizadas por la DGII.
2. Cambia al entorno de producción desde la configuración de empresa
   (**Configuración → General → Entorno DGII**).

## Consejos

- Mantén **Sandbox activo** mientras configuras y haces pruebas.
- No emitas documentos reales hasta confirmar que tus datos fiscales y tu
  certificado están correctos.
- Los datos de Sandbox y de producción se guardan **por separado**.
