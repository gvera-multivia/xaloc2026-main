import sys
import os

# Añadir el directorio raíz al path para poder importar core
sys.path.append(os.getcwd())

from core.xaloc_expediente_utils import is_valid_format, fix_format

def test_formatting():
    test_cases = [
        # (Entrada, Esperado, EsVálido)
        ("2026-11504-MUL", "2026/11504-MUL", True),
        ("2025-257615-MUL", "2025/257615-MUL", True),
        ("2025/243792-MU", "2025/243792-MUL", True),
        ("2026-103-MUL", "2026/103-MUL", True),
        ("2026/400-MUL", "2026/400-MUL", True),
        ("2026-1531-MUL", "2026/1531-MUL", True),
        ("2025-258060-MUL", "2025/258060-MUL", True),
        ("2025-257608-MUL", "2025/257608-MUL", True),
        ("2025-257339-MUL", "2025/257339-MUL", True),
        ("2025-257939-MUL", "2025/257939-MUL", True),
        # Casos bordes
        ("  2026-123-MUL  ", "2026/123-MUL", True),
        ("NT/12345678/2024/000000000", "NT/12345678/2024/000000000", False), # NT no se corrige con fix_format, se corrige con fix_nt_expediente
    ]
    
    total = len(test_cases)
    passed = 0
    
    print(f"Running {total} test cases...\n")
    
    for input_val, expected, should_be_valid in test_cases:
        fixed = fix_format(input_val)
        is_valid = is_valid_format(fixed)
        
        status = "PASSED" if fixed == expected and is_valid == should_be_valid else "FAILED"
        if status == "PASSED":
            passed += 1
            print(f"[OK] {input_val} -> {fixed} (Valid: {is_valid})")
        else:
            print(f"[FAIL] {input_val} -> Got: {fixed} (Valid: {is_valid}), Expected: {expected} (Valid: {should_be_valid})")
            
    print(f"\nSummary: {passed}/{total} passed")
    
    if passed == total:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    test_formatting()
