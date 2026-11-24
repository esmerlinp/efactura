import hashlib


def test_bank_movement_key_is_stable_per_source():
    key_a = hashlib.sha256("account:cxp_payment:payment-1".encode()).hexdigest()
    key_b = hashlib.sha256("account:cxp_payment:payment-1".encode()).hexdigest()
    key_c = hashlib.sha256("account:cxp_payment:payment-2".encode()).hexdigest()
    assert key_a == key_b
    assert key_a != key_c
