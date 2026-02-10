
import pytest
from sites.madrid.controller import MadridController
from sites.madrid.data_models import TipoExpediente

def test_madrid_controller_allows_missing_apellido2():
    controller = MadridController()
    
    # Minimal valid data for MadridController.map_data/create_target
    data = {
        "idRecurso": 12345,
        "exp_tipo": "opcion1",
        "exp_nnn": "123",
        "exp_eeeeeeeee": "123456789",
        "exp_d": "0",
        "inter_telefono": "911223344",
        "inter_email_check": True,
        "rep_tipo_via": "CL",
        "rep_nombre_via": "ALCALA",
        "rep_tipo_numeracion": "NUM",
        "rep_numero": "1",
        "rep_cp": "28001",
        "rep_municipio": "MADRID",
        "rep_provincia": "MADRID",
        "rep_pais": "ESPAÑA",
        "rep_email": "rep@example.com",
        "rep_movil": "666777888",
        "rep_telefono": "911223344",
        "notif_tipo_documento": "NIF",
        "notif_numero_documento": "12345678Z",
        "notif_nombre": "JOAN",
        "notif_apellido1": "PUJOL",
        # "notif_apellido2" is MISSING
        "notif_pais": "ESPAÑA",
        "notif_provincia": "MADRID",
        "notif_municipio": "MADRID",
        "notif_tipo_via": "CL",
        "notif_nombre_via": "ALCALA",
        "notif_codigo_postal": "28001",
        "notif_email": "notif@example.com",
        "naturaleza": "A",
        "expone": "Some expone",
        "solicita": "Some solicita",
        "archivos": ["doc1.pdf"],
    }
    
    # This should not raise ValueError
    params = controller.map_data(data)
    target = controller.create_target(**params)
    
    assert target.form_data.notificacion.identificacion.apellido2 == ""
    assert target.form_data.notificacion.identificacion.nombre == "JOAN"

def test_madrid_controller_fails_on_missing_apellido1():
    controller = MadridController()
    data = {
        "exp_tipo": "opcion1",
        "exp_nnn": "123",
        "exp_eeeeeeeee": "123456789",
        "exp_d": "0",
        "inter_telefono": "911223344",
        "inter_email_check": True,
        "rep_tipo_via": "CL",
        "rep_nombre_via": "ALCALA",
        "rep_tipo_numeracion": "NUM",
        "rep_numero": "1",
        "rep_cp": "28001",
        "rep_municipio": "MADRID",
        "rep_provincia": "MADRID",
        "rep_pais": "ESPAÑA",
        "rep_email": "rep@example.com",
        "rep_movil": "666777888",
        "rep_telefono": "911223344",
        "notif_tipo_documento": "NIF",
        "notif_numero_documento": "12345678Z",
        "notif_nombre": "JOAN",
        # "notif_apellido1" is missing
        "notif_pais": "ESPAÑA",
        "notif_provincia": "MADRID",
        "notif_municipio": "MADRID",
        "notif_tipo_via": "CL",
        "notif_nombre_via": "ALCALA",
        "notif_codigo_postal": "28001",
        "notif_email": "notif@example.com",
        "naturaleza": "A",
        "expone": "Some expone",
        "solicita": "Some solicita",
        "archivos": ["doc1.pdf"],
    }
    
    params = controller.map_data(data)
    with pytest.raises(ValueError, match="falta 'notif_apellido1'"):
        controller.create_target(**params)
