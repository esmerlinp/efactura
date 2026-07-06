from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.services.i18n_service import I18nService, SUPPORTED_LOCALES


web_i18n_bp = Blueprint("web_i18n", __name__)


@web_i18n_bp.route("/settings/language", methods=["GET", "POST"])
def language_settings():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))

    if request.method == "POST":
        locale = I18nService.normalise_locale(request.form.get("locale", "es"))
        I18nService.set_user_locale(session["user"].get("uid", ""), locale)
        flash("Preferencia de idioma actualizada.", "success")
        return redirect(url_for("web_i18n.language_settings"))

    return render_template(
        "settings/language.html",
        active_page="language_settings",
        supported_locales=SUPPORTED_LOCALES,
        current_locale=I18nService.current_locale(),
    )

