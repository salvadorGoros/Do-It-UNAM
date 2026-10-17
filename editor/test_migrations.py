from copy import deepcopy

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class AnimacionMigrationTests(TransactionTestCase):
    def test_convertir_objetos_sin_perder_datos(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("editor", "0003_cuadros_de_texto")])
        try:
            apps = executor.loader.project_state([("editor", "0003_cuadros_de_texto")]).apps
            user = apps.get_model("auth", "User").objects.create(username="migracion")
            obj = dict(id="anterior", texto="Texto\noriginal", x=15, y=25, ancho=300, alto=100,
                fuente="Arial", tamano=24, color="#ffffff", negrita=False, cursiva=True, subrayado=False, alineacion="left")
            proyecto = apps.get_model("editor", "Proyecto").objects.create(nombre="Anterior", propietario_id=user.pk, objetos=[obj])
            executor = MigrationExecutor(connection)
            executor.migrate([("editor", "0006_proyecto_diapositivas")])
            apps = executor.loader.project_state([("editor", "0006_proyecto_diapositivas")]).apps
            actualizado = apps.get_model("editor", "Proyecto").objects.get(pk=proyecto.pk)
            expected = deepcopy(obj)
            expected["fotogramas"] = [dict(frame=0, x=15, y=25, giro=0, opacidad=1, interpolacion="lineal")]
            self.assertEqual(actualizado.objetos, [expected])
            self.assertEqual(actualizado.duracion_frames, 300)
            self.assertEqual(actualizado.diapositivas[0]["objetos"], [expected])
            self.assertEqual(actualizado.diapositivas[0]["duracion_frames"], 300)
            self.assertEqual(actualizado.propietario_id, user.pk)
        finally:
            MigrationExecutor(connection).migrate([("editor", "0006_proyecto_diapositivas")])
