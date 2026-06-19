from flask import Blueprint, jsonify
from app.api.auth import require_api_key
from app.utils.cache_utils import http_cache

metadata_bp = Blueprint('metadata', __name__)

@metadata_bp.route('/metadata/catalogs', methods=['GET'])
@require_api_key
@http_cache(timeout=3600, private=False)
def get_catalogs():
    """
    Retorna todos los catálogos oficiales requeridos por los clientes móviles.
    Garantiza la centralización de datos impositivos regulados por la DGII.
    """
    measurement_units = [
        "Unidad", "Servicio", "Barril", "Bolsa", "Bote", "Bultos", "Botella",
        "Caja/Cajón", "Cajetilla", "Centímetro", "Cilindro", "Conjunto",
        "Contenedor", "Día", "Docena", "Fardo", "Galones", "Grado", "Gramo",
        "Granel", "Hora", "Huacal", "Kilogramo", "Kilovatio Hora", "Libra",
        "Litro", "Lote", "Metro", "Metro Cuadrado", "Metro Cúbico",
        "Millones de Unidades Térmicas", "Minuto", "Paquete", "Par", "Pie",
        "Pieza", "Rollo", "Sobre", "Segundo", "Tanque", "Tonelada", "Tubo",
        "Yarda", "Yarda cuadrada"
    ]
    
    currencies = [
        {"code": "DOP", "label": "Peso Dominicano"},
        {"code": "USD", "label": "Dólar Americano"},
        {"code": "EUR", "label": "Euro"}
    ]
    
    payment_types = ["Contado", "Crédito", "Gratuito (Regalo)"]
    
    payment_methods = [
        "Efectivo", "Cheque / Transferencia",
        "Tarjeta de Crédito / Débito", "Crédito", "Mixto"
    ]
    
    income_types = [
        {"code": "01", "label": "01 - Ingresos por operaciones"},
        {"code": "02", "label": "02 - Ingresos financieros"},
        {"code": "03", "label": "03 - Ingresos extraordinarios"},
        {"code": "04", "label": "04 - Arrendamientos"},
        {"code": "05", "label": "05 - Depreciables"},
        {"code": "06", "label": "06 - Otros ingresos"}
    ]
    
    itbis_rates = [
        {"rate": 0.18, "label": "18% (ITBIS General)"},
        {"rate": 0.16, "label": "16% (ITBIS Reducido)"},
        {"rate": 0.00, "label": "Exento (0%)"}
    ]
    
    ecf_types = [
        {"code": "E31", "label": "Crédito Fiscal (E31)", "description": "Factura de Crédito Fiscal (E31)"},
        {"code": "E32", "label": "Consumo (E32)", "description": "Factura de Consumo (E32)"},
        {"code": "E33", "label": "Nota de Débito (E33)", "description": "Nota de Débito (E33)"},
        {"code": "E34", "label": "Nota de Crédito (E34)", "description": "Nota de Crédito (E34)"},
        {"code": "E41", "label": "Comprobante de Compras (E41)", "description": "Comprobante de Compras (E41)"},
        {"code": "E43", "label": "Gastos Menores (E43)", "description": "Gastos Menores (E43)"},
        {"code": "E44", "label": "Regímenes Especiales (E44)", "description": "Regímenes Especiales (E44)"},
        {"code": "E45", "label": "Gubernamental (E45)", "description": "Gubernamental (E45)"},
        {"code": "E46", "label": "Exportación (E46)", "description": "Comprobante de Exportación (E46)"},
        {"code": "E47", "label": "Pagos al Exterior (E47)", "description": "Pagos al Exterior (E47)"}
    ]
    
    return jsonify({
        "measurement_units": measurement_units,
        "currencies": currencies,
        "payment_types": payment_types,
        "payment_methods": payment_methods,
        "income_types": income_types,
        "itbis_rates": itbis_rates,
        "ecf_types": ecf_types
    }), 200
