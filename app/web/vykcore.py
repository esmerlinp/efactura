from flask import Blueprint, render_template
from flask import session

web_vykcore_bp = Blueprint('web_vykcore', __name__)


@web_vykcore_bp.route('/vykcore')
def vykcore_landing():
    return render_template('vykcore.html')
