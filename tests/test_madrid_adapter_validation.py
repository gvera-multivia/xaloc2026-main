
import pytest
from sites.adapters.madrid import MadridAdapter

def test_madrid_adapter_validation_allows_missing_surname2():
    adapter = MadridAdapter()
    
    # Valid payload with missing notif_surname2
    payload = {
        "idRecurso": 12345,
        "expediente_tipo": "opcion1",
        "naturaleza": "A",
        "expone": "Some expone",
        "solicita": "Some solicita",
        "rep_tipo_via": "CL",
        "rep_tipo_numeracion": "NUM",
        "rep_cp": "28001",
        "rep_municipio": "MADRID",
        "rep_provincia": "MADRID",
        "rep_pais": "ESPAÑA",
        "notif_tipo_documento": "NIF",
        "notif_numero_documento": "12345678Z",
        "notif_name": "JOAN",
        "notif_surname1": "PUJOL",
        # "notif_surname2" is missing
        "notif_pais": "ESPAÑA",
        "notif_provincia": "MADRID",
        "notif_municipio": "MADRID",
        "notif_tipo_via": "CL",
        "notif_nombre_via": "ALCALA",
        "notif_tipo_numeracion": "NUM",
        "notif_numero": "1",
        "notif_codigo_postal": "28001",
    }
    
    # Should not raise ValueError
    adapter._prevalidate_required_fields(payload)

def test_madrid_adapter_validation_fails_on_missing_name():
    adapter = MadridAdapter()
    
    # Invalid payload missing notif_name
    payload = {
        "idRecurso": 12345,
        "expediente_tipo": "opcion1",
        "naturaleza": "A",
        "expone": "Some expone",
        "solicita": "Some solicita",
        "rep_tipo_via": "CL",
        "notif_tipo_documento": "NIF",
        "notif_numero_documento": "12345678Z",
        "notif_surname1": "PUJOL",
        "notif_name": "", # Empty name
    }
    
    with pytest.raises(ValueError, match="faltan campos:.*notif_name"):
        adapter._prevalidate_required_fields(payload)
