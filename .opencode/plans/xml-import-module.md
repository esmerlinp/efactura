# Plan: Módulo de Importación de e-CF XML con Clasificación IA

## Resumen

Implementar funcionalidad para importar XML de comprobantes fiscales (e-CF) de proveedores,
parsear la estructura fiscal, clasificar con IA (GPT-4o-mini), y registrar el gasto automáticamente.

## Archivos

### 1. NUEVO: `app/services/xml_import_service.py`

**Clase:** `XMLImportService`

```python
import xml.etree.ElementTree as ET

class XMLImportService:
    NS = {"ecf": "http://dgii.gov.do/CF"}

    @classmethod
    def parse_ecf_xml(cls, xml_bytes):
        """Parsea XML de e-CF y extrae datos fiscales."""
        ...

    @classmethod
    def validate_fiscal_structure(cls, parsed):
        """Valida campos obligatorios. Retorna lista de errores."""
        ...

    @classmethod
    def items_to_text(cls, parsed):
        """Convierte items del XML a texto plano para IA."""
        ...
```

### 2. NUEVO: `app/services/supplier_service.py`

**Clase:** `SupplierService`

```python
class SupplierService:
    @classmethod
    def get_or_create_supplier(cls, owner_uid, rnc, name, address="", sandbox=True):
        """Busca proveedor por RNC; si no existe, lo crea en Firestore."""
        ...

    @classmethod
    def supplier_exists(cls, owner_uid, rnc, sandbox=True):
        """Verifica si ya existe un proveedor con ese RNC."""
        ...
```

Colección: `users/{owner_uid}/suppliers/`

### 3. NUEVO: `app/services/ai_classifier_service.py`

**Clase:** `AIExpenseClassifier`

```python
class AIExpenseClassifier:
    CATEGORIES = [
        "Comida y Restaurantes", "Transporte y Combustible",
        "Servicios Básicos", "Software y Tecnología",
        "Materiales de Oficina", "Alquileres",
        "Impuestos y Tasas", "Otros Gastos",
    ]

    @classmethod
    def classify_expense_from_import(cls, owner_uid, supplier_name, supplier_rnc,
                                     items_text, total, date, ecf_type):
        """
        Envía datos estructurados a GPT-4o-mini.
        Retorna {category, tipoGastoDGII, suggestedAccount, confidence,
                 isRecurring, recurrenceInterval, isDeductible, anomalies}
        """
        ...

    @classmethod
    def detect_duplicate(cls, owner_uid, supplier_rnc, total, date, sandbox=True):
        """Busca gastos existentes con mismo RNC + monto similar + fecha cercana."""
        ...

    @classmethod
    def _fallback_classify(cls, supplier_name, items_text):
        """Keyword-based fallback cuando no hay API key."""
        ...
```

### 4. MODIFICAR: `app/services/db_service.py`

Agregar campo `supplierId` en:
- `get_expense()`: `data["supplierId"] = data.get("supplierId", "")`
- `get_expenses()`: `"supplierId": data.get("supplierId", "")`
- `save_expense()`: `exp_dict["supplierId"] = exp_dict.get("supplierId", "")`

### 5. MODIFICAR: `app/web/invoices.py`

Agregar 3 rutas nuevas:

```python
@web_invoices_bp.route('/expenses/import')
def expense_import_page():
    """GET: Muestra formulario de importación."""

@web_invoices_bp.route('/expenses/import/preview', methods=['POST'])
def expense_import_preview():
    """POST: Recibe XML (+PDF opcional), parsea, clasifica con IA, renderiza preview."""

@web_invoices_bp.route('/expenses/import/confirm', methods=['POST'])
def expense_import_confirm():
    """POST: Confirma y crea el gasto con datos opcionalmente corregidos."""
```

### 6. NUEVO: `templates/expenses/import.html`

Template con:
- Zona drag & drop para XML (obligatorio) + PDF (opcional)
- Sección de datos extraídos del XML (readonly)
- Sección de clasificación IA con badges de confianza
- Alertas (duplicado, anomalía, recurrencia)
- Campos editables para corrección
- Botón confirmar

### 7. MODIFICAR: `templates/expenses/list.html`

Agregar botón "Importar XML" junto al botón "Registrar Gasto".

---

## Flujo completo

```
1. GET /expenses/import → formulario drag & drop
2. Usuario sube XML (obligatorio) + PDF (opcional)
3. POST /expenses/import/preview
   a. XMLImportService.parse_ecf_xml() → datos fiscales
   b. XMLImportService.validate_fiscal_structure() → validación
   c. SupplierService.get_or_create_supplier() → auto-crear proveedor
   d. AIExpenseClassifier.classify_expense_from_import() → clasificación IA
   e. AIExpenseClassifier.detect_duplicate() → alerta duplicado
   f. Renderizar preview con datos + IA + alertas
4. Usuario revisa, corrige si desea, confirma
5. POST /expenses/import/confirm
   a. DatabaseService.save_expense()
   b. Redirect a expense_detail
```

## Dependencias

- No requiere nuevas dependencias Python (usa xml.etree.ElementTree nativo, requests ya instalado)
- Usa OpenAI GPT-4o-mini (mismo modelo existente)
- Firestore collection nueva: `suppliers`

## Tiempo estimado

- ~4-6 horas de implementación
- 2-3 horas de pruebas
