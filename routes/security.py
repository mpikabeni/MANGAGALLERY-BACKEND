"""Routes called by the "Sécurité" buttons of Admin -> Paramètres.

The sessions are stateless JWT tokens: the server keeps no list of them, so it cannot honestly "disconnect everybody" without
changing JWT_SECRET_KEY. These answer with a clear French message instead of a 404, and say how to do it.
"""
from flask import Blueprint

from utils.authz import require_admin
from utils.http import fail

security_bp = Blueprint("security", __name__)


@security_bp.post("/logout-all")
@require_admin
def logout_all():
    return fail("Non disponible : les sessions ne sont pas suivies côté serveur. Pour déconnecter tout le monde, change JWT_SECRET_KEY sur Render puis redémarre.", 501)


@security_bp.post("/reset")
@require_admin
def reset():
    return fail("Non disponible : aucun réglage de sécurité n'est stocké à réinitialiser.", 501)
