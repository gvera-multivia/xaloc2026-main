from db_helper import DBHelper


def get_recurso_data(id_recurso):
    """
    Obtiene los datos combinados de RecursosExp, expedientes, clientes y pubexp
    para un idRecurso dado.
    """
    db = DBHelper()  # Usa los valores por defecto de conexión

    query = """
    SELECT
        r.idRecurso,
        r.Expedient,
        r.Matricula,
        r.Organisme,
        r.numclient,
        r.IdExp,
        r.IdPublic,
        r.TExp,
        r.ConducNom,
        r.Conducdni,
        r.ConducCodpost,
        r.ConducAdr,
        e.matricula AS Matricula2,
        c.tipodecliente,
        c.Nombre,
        c.Apellido1,
        c.Apellido2,
        c.Nombrefiscal,
        c.nif,
        c.nifempresa,
        p.matricula AS Matricula3,
        d.ConducNom AS ConducNom2,
        d.ConducDni AS Conducdni2,
        d.ConducCodpost AS ConducCodpost2,
        d.ConducAdr AS ConducAdr2
        
    FROM Recursos.RecursosExp r
    LEFT JOIN expedientes e ON r.IdExp = e.idexpediente
    LEFT JOIN clientes c ON r.numclient = c.numerocliente
    LEFT JOIN pubexp p ON r.IdPublic = p.idpublic
    LEFT JOIN DadesIdentif d ON r.IdExp = d.idExp
    WHERE r.idRecurso = :id_recurso
    """

    # Ejecuta la query con parámetro seguro
    df = db.run_query(query, params={"id_recurso": id_recurso})
    return df
