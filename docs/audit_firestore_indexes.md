# Índices de Auditoría Firestore

Las consultas del panel de auditoría ordenan por `timestamp` descendente y
pueden combinar filtros exactos. Firestore puede solicitar índices compuestos
adicionales al ejecutar una combinación que no exista todavía.

Índices recomendados:

- `module ASC, timestamp DESC`
- `action ASC, timestamp DESC`
- `isSandbox ASC, timestamp DESC`
- `performedByUID ASC, timestamp DESC`
- `entityId ASC, timestamp DESC`
- `module ASC, action ASC, timestamp DESC`
- `isSandbox ASC, module ASC, timestamp DESC`
- `isSandbox ASC, action ASC, timestamp DESC`

No se recomienda crear índices para búsquedas parciales por nombre, email o
descripción: esas búsquedas continúan filtrándose en Python y tienen un límite
de lectura por consulta web.

Los índices deben crearse en cada colección usada por la aplicación, incluida
la variante de sandbox cuando Firestore lo requiera. Validar el índice exacto
que indique el error de Firestore antes de desplegarlo en producción.
