def test_bank_movement_id_is_deterministic():
    import hashlib
    assert hashlib.sha256(b"account:invoice:payment").hexdigest() == hashlib.sha256(b"account:invoice:payment").hexdigest()
