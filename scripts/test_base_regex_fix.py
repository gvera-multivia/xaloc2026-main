import re

def test_parse_expediente(expediente):
    exp = str(expediente).strip().upper()
    # Updated regex
    m_gim = re.match(r"^(?P<id_ens>\d{5})-(?P<any>\d{4})[/\-](?P<num>\d{1,5})-GIM$", exp)
    if m_gim:
        return {
            "expediente_id_ens": m_gim.group("id_ens"),
            "expediente_any": m_gim.group("any"),
            "expediente_num": m_gim.group("num"),
            "num_butlleti": exp,
        }
    return None

test_cases = [
    "43157-2026/800-GIM",
    "43157-2026/1234-GIM",
    "43157-2026/12345-GIM",
    "12345-2023-1-GIM",
]

print("Starting Regex Verification...")
all_passed = True
for tc in test_cases:
    result = test_parse_expediente(tc)
    if result:
        print(f"PASS: {tc} -> {result}")
    else:
        print(f"FAIL: {tc}")
        all_passed = False

if all_passed:
    print("\nVerification SUCCESSFUL. All test cases matched.")
else:
    print("\nVerification FAILED. Some test cases did not match.")
    exit(1)
