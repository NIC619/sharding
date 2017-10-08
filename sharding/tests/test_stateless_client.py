import pytest
import logging
import rlp

from viper import compiler
from ethereum import utils
from ethereum import trie
from ethereum.slogging import get_logger
from ethereum.tools import tester
from ethereum.securetrie import SecureTrie


@pytest.fixture(scope='function')
def chain(alloc={}, genesis_gas_limit=4712388,
            min_gas_limit=5000, startgas=3141592,
            enable_constantipole=False):
    # alloc
    for i in range(9):
        alloc[utils.int_to_addr(i)] = {'balance': 1}
    # genesis
    from ethereum.genesis_helpers import mk_basic_state
    header = {
        "number": 0, "gas_limit": genesis_gas_limit,
        "gas_used": 0, "timestamp": 1467446877, "difficulty": 1,
        "uncles_hash": '0x'+utils.encode_hex(utils.sha3(rlp.encode([])))
    }
    genesis = mk_basic_state(alloc, header, tester.get_env(None))
    # tester
    tester.languages['viper'] = compiler.Compiler()
    tester.STARTGAS = startgas
    c = tester.Chain(alloc=alloc, genesis=genesis)
    c.chain.env.config['MIN_GAS_LIMIT'] = min_gas_limit
    if enable_constantipole:
        c.chain.env.config['CONSTANTINOPLE_FORK_BLKNUM'] = 0
    c.mine(1)
    return c

@pytest.fixture(scope='function')
def getMerkleProof(db, root, value):
    assert db and root and value
    print("key:", value)
    key = utils.sha3(value)
    # make sure the value exist in the trie 
    assert trie._get(db, root, trie.encode_bin(key))
    print("value:", trie._get(db, root, trie.encode_bin(key)))
    proof = trie._get_branch(db, root, trie.encode_bin(key))
    print("proof:", proof)
    print("")
    return proof

@pytest.fixture(scope='function')
def verifyMerkleProof(branch, root, value):
    assert branch and root and value
    return trie._verify_branch(branch, root, value)



test_account_proof_code = """
creator: public(address)

@payable
def __init__():
    self.creator = msg.sender

def touch(addrs: address[3]):
    for i in range(3):
        send(addrs[i], 1)
"""

def test_tx_proof():
    alloc = {}
    alloc[tester.a1] = {'balance': 10}
    c = chain(alloc)

    c.tx(sender=tester.k1, to=tester.a2, value=1, data=b'')
    c.tx(sender=tester.k1, to=tester.a3, value=1, data=b'')
    c.tx(sender=tester.k1, to=tester.a4, value=1, data=b'')

    t = trie.Trie(trie.EphemDB())
    # generates tx trie
    for (i, tx) in enumerate(c.block.transactions):
        t.update(utils.sha3(rlp.encode(i)), rlp.encode(tx))

    # generates proof for each tx
    proofs = {}
    for (i, tx) in enumerate(c.block.transactions):
        proofs[str(i)] = getMerkleProof(t.db, t.root, rlp.encode(i))

    # verify each tx proof
    for (i, proof) in proofs.items():
        assert verifyMerkleProof(proof, t.root, rlp.encode(c.block.transactions[int(i)]))

def test_account_proof():
    alloc = {}
    alloc[tester.a0] = {'balance': 10}
    c = chain(alloc)
    
    contract_addr = utils.mk_contract_address(tester.a0, c.head_state.get_nonce(tester.a0))
    test_account_proof_contract = c.contract(test_account_proof_code, value=10, language='viper')

    addrs = [tester.a1, tester.a2, tester.a3]
    # try getting merkle proof of non-exist account
    try:
        getMerkleProof(c.head_state.trie.db, c.head_state.trie.root_hash, addrs[0])
    except AssertionError:
        print("Account does not exist yet, can not make merkle proof")

    assert c.head_state.get_balance(test_account_proof_contract.address) == 10
    # send 1 wei to each of the accounts in addrs
    test_account_proof_contract.touch(addrs)
    assert c.head_state.get_balance(test_account_proof_contract.address) == 7
    # for each account in addrs, generate and verify merkle proof
    for addr in addrs:
        proof = getMerkleProof(c.head_state.trie.db, c.head_state.trie.root_hash, addr)
        acct_rlpdata = c.head_state.trie.get(addr)
        assert verifyMerkleProof(proof, c.head_state.trie.root_hash, acct_rlpdata)
    # try verify proof against wrong value
    try:
        verifyMerkleProof(proof, c.head_state.trie.root_hash, bytes("wrong_value", encoding='utf-8'))
    except AssertionError:
        print("Can not verify proofs against wrong value")