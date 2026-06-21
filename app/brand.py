from flask import current_app

def get_product_name():
    try:
        return current_app.config['PRODUCT_NAME']
    except (RuntimeError, KeyError):
        return "KodexOne"
