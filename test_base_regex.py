import re

def valida_expediente_base(expediente: str) -> bool:
    exp = expediente.strip().upper()
    if re.match(r'^\d{5}-\d{4}/\d{5}-GIM$', exp): return True
    if re.match(r'^\d{2}-\d{3}-\d{3}-\d{4}-\d{2}-\d{7}$', exp): return True
    if re.match(r'^\d-\d{4}/\d{5}-(EXE|ECC)$', exp): return True
    return False

def parse_expediente_base(expediente: str) -> dict:
    exp = expediente.strip().upper()
    m_a = re.match(r'^(?P<id_ens>\d{5})-(?P<any>\d{4})/(?P<num>\d{5})-GIM$', exp)
    if m_a:
        return {"id_ens": m_a.group("id_ens"), "any": m_a.group("any"), "num": m_a.group("num"), "butlleti": ""}
    m_exe = re.match(r'^(?P<id_ens>\d)-(?P<any>\d{4})/(?P<num>\d{5})-(EXE|ECC)$', exp)
    if m_exe:
        return {"id_ens": m_exe.group("id_ens"), "any": m_exe.group("any"), "num": m_exe.group("num"), "butlleti": ""}
    return {"id_ens": "", "any": "", "num": "", "butlleti": exp}

test_cases = [
    ("43185-2025/40818-GIM", True),
    ("43-558-779-2018-11-0005780", True),
    ("1-2025/27474-EXE", True),
    ("1-2025/27474-ECC", True),
    ("9999-999-GIM", False),
    ("INVALID-FORMAT", False)
]

for exp, expected in test_cases:
    valid = valida_expediente_base(exp)
    print(f"Exp: {exp:30} | Valid: {str(valid):5} | Expected: {str(expected):5} | {'OK' if valid == expected else 'FAIL'}")
    if valid:
        print(f"  Parsed: {parse_expediente_base(exp)}")
