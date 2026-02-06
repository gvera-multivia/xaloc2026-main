
import re

def resolve_plate_number_current(text):
    if not text:
        return None
    # Current logic in brain.py
    m = re.search(r"\b([0-9]{4}[A-Z]{3}|[A-Z]{1,2}[0-9]{4}[A-Z]{1,2})\b", text.replace(" ", "").upper())
    if m:
        return m.group(1)
    return None

def resolve_plate_number_proposed(text):
    if not text:
        return None
    # Proposed logic: handle optional spaces in regex, don't strip global spaces
    # Spanish plates: 1234-BBB or 1234 BBB or 1234BBB
    # Old: M-1234-AB or M 1234 AB or M1234AB
    
    # Regex explanations:
    # (?:\b|(?<=\W)) : Look for word boundary or non-word character preceding
    # [0-9]{4} : 4 digits
    # [\s-]* : optional separator
    # [A-Z]{3} : 3 letters
    
    # Note: \b is tricky with dashes. 
    
    # Let's try to match the sequence and clean it up later.
    
    pattern = r"\b([0-9]{4}[\s-]*[A-Z]{3}|[A-Z]{1,2}[\s-]*[0-9]{4}(?:[\s-]*[A-Z]{1,2})?)\b"
    # Note: Old plates might have 0 trailing letters (rare/very old?) usually 1-2. User regex enforced 1-2.
    # User regex: [A-Z]{1,2}[0-9]{4}[A-Z]{1,2}  <- Requires trailing letters.
    
    # Let's stick close to user regex but allow spaces/dashes.
    
    regex = r"\b([0-9]{4}[\s-]*[A-Z]{3}|[A-Z]{1,2}[\s-]*[0-9]{4}[\s-]*[A-Z]{1,2})\b"
    
    m = re.search(regex, text.upper())
    if m:
        return m.group(1).replace(" ", "").replace("-", "")
    return None

test_cases = [
    ("Vehiculo con matricula 1234BBB estacionado", "1234BBB"),
    ("Vehiculo con matricula 1234 BBB estacionado", "1234BBB"),
    ("Sancion:1234BBB", "1234BBB"),
    ("Text1234BBBText", None), # Should not match
    ("M 1234 YZ", "M1234YZ"),
    ("M-1234-YZ", "M1234YZ"),
]

print("Testing Current Logic:")
for text, expected in test_cases:
    result = resolve_plate_number_current(text)
    print(f"'{text}' -> '{result}' (Expected: {expected}) - {'PASS' if result == expected else 'FAIL'}")

print("\nTesting Proposed Logic:")
for text, expected in test_cases:
    result = resolve_plate_number_proposed(text)
    print(f"'{text}' -> '{result}' (Expected: {expected}) - {'PASS' if result == expected else 'FAIL'}")
