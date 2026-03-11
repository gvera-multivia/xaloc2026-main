def split_full_name(full_name: str):
    """
    Divide un nombre completo en Nombre, Apellido1, Apellido2.
    Las partículas (de, del, de la, y, van, von, ...) se incluyen en el
    apellido al que preceden, tanto Apellido1 como Apellido2.
    """
    if not full_name or not full_name.strip():
        return "", "", ""

    tokens = full_name.strip().split()
    n = len(tokens)

    if n == 1:
        return tokens[0], "", ""
    if n == 2:
        return tokens[0], tokens[1], ""

    particulas = {
        "de",
        "del",
        "la",
        "las",
        "los",
        "y",
        "van",
        "von",
        "mc",
        "mac",
        "san",
        "santa",
    }

    # Último token siempre entra en Apellido2; retrocedemos si hay partículas
    apellido2_tokens = [tokens[-1]]
    i = n - 2
    while i >= 0 and tokens[i].lower() in particulas:
        apellido2_tokens.insert(0, tokens[i])
        i -= 1

    apellido2 = " ".join(apellido2_tokens)

    # El token en i es la palabra principal de Apellido1
    if i < 0:
        return "", "", apellido2

    apellido1_tokens = [tokens[i]]
    i -= 1

    # Retrocedemos también para recoger partículas que preceden a Apellido1
    while i >= 0 and tokens[i].lower() in particulas:
        apellido1_tokens.insert(0, tokens[i])
        i -= 1

    apellido1 = " ".join(apellido1_tokens)
    nombre = " ".join(tokens[: i + 1])

    return nombre, apellido1, apellido2
