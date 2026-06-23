from flask import Blueprint, render_template
from flask import session

web_zentcore_bp = Blueprint('web_zentcore', __name__)


@web_zentcore_bp.route('/zentcore')
def zentcore_landing():
    return render_template('zentcore.html')
