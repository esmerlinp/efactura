from flask import Blueprint

api_bp = Blueprint('api', __name__)

# Importar las rutas para registrarlas en el Blueprint
from . import routes
