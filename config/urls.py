from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from editor.forms import InstitutionalAuthenticationForm, InstitutionalPasswordResetForm

urlpatterns = [
    path(
        "cuentas/entrar/",
        auth_views.LoginView.as_view(authentication_form=InstitutionalAuthenticationForm),
        name="login",
    ),
    path(
        "cuentas/recuperar/",
        auth_views.PasswordResetView.as_view(
            form_class=InstitutionalPasswordResetForm,
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.txt",
            subject_template_name="registration/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "cuentas/recuperar/enviado/",
        auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "cuentas/restablecer/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html"),
        name="password_reset_confirm",
    ),
    path(
        "cuentas/restablecer/completo/",
        auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path("cuentas/salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("", include("editor.urls")),
]
