from reachsocial.buyer_wallet import DERIVATION_PATH, recover_buyer_wallet


def test_recovery_derives_the_standard_first_evm_address() -> None:
    mnemonic = "test test test test test test test test test test test junk"

    assert DERIVATION_PATH == "m/44'/60'/0'/0/0"
    assert recover_buyer_wallet(mnemonic) == "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
