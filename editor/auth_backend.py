from django.contrib.auth.backends import BaseBackend
from django.core.exceptions import ObjectDoesNotExist


class InstitutionalRoleBackend(BaseBackend):
    """Concede permisos administrativos globales al rol Administrador.

    La autenticación de contraseña continúa en ModelBackend; este backend solo
    aporta permisos para mantener una única fuente de verdad en PerfilUsuario.
    """

    @staticmethod
    def _is_admin(user_obj):
        if not user_obj or not user_obj.is_active:
            return False
        try:
            return user_obj.perfil_institucional.rol.clave == "administrador"
        except (AttributeError, ObjectDoesNotExist):
            return False

    def has_perm(self, user_obj, perm, obj=None):
        return self._is_admin(user_obj)

    def has_module_perms(self, user_obj, app_label):
        return self._is_admin(user_obj)
