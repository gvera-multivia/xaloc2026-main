import pytest

from core.xaloc_expediente_utils import fix_format, is_valid_format


@pytest.mark.parametrize(
    "input_val,expected,should_be_valid",
    [
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
        ("2025/219303-SAD", "2025/219303-SAD", True),
        ("2025/733178-APR", "2025/733178-APR", True),
        ("2025-733178-APR", "2025/733178-APR", True),
        ("2020-506165-2", "2020-506165-2", True),
        ("  2026-123-MUL  ", "2026/123-MUL", True),
        # NT no se corrige con fix_format, se corrige con fix_nt_expediente
        ("NT/12345678/2024/000000000", "NT/12345678/2024/000000000", False),
    ],
)
def test_fix_format_and_validation(input_val: str, expected: str, should_be_valid: bool) -> None:
    fixed = fix_format(input_val)
    assert fixed == expected
    assert is_valid_format(fixed) == should_be_valid
