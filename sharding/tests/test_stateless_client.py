import json
import pytest
import logging
import rlp
from rlp.sedes import Serializable

from viper import compiler
from ethereum import utils
from ethereum import trie
from ethereum.slogging import get_logger
from ethereum.tools import tester
from ethereum.tools.stateless_client import (get_merkle_proof,
                                             verify_merkle_proof,
                                             store_merkle_branch_nodes,
                                             mk_account_proof_wrapper,
                                             mk_pending_tx_bundle,
                                             mk_confirmed_tx_bundle,
                                             verify_tx_bundle)


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
        "uncles_hash": '0x' + utils.encode_hex(utils.sha3(rlp.encode([])))
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


test_account_proof_code = """
owner: public(address)
map: public(num[num])
map2: num[num]

@payable
def __init__():
    self.owner = msg.sender

def touch(addrs: address[3]):
    for i in range(3):
        send(addrs[i], 1)

@constant
def read_balance(addrs: address[2]) -> num(wei):
    return(addrs[0].balance + addrs[1].balance)

def change_owner(new_owner: address):
    self.owner = new_owner

def set_map(k: num, v: num):
    self.map[k] = v
    self.map2[v] = k
"""


def test_tx_proof():
    alloc = {}
    alloc[tester.a1] = {'balance': 10}
    c = chain(alloc)

    c.tx(sender=tester.k1, to=tester.a2, value=1, data=b'', read_list=[
         tester.a1, tester.a2], write_list=[tester.a1, tester.a2])
    c.tx(sender=tester.k1, to=tester.a3, value=1, data=b'', read_list=[
         tester.a1, tester.a3], write_list=[tester.a1, tester.a3])
    c.tx(sender=tester.k1, to=tester.a4, value=1, data=b'', read_list=[
         tester.a1, tester.a4], write_list=[tester.a1, tester.a4])

    t = trie.Trie(trie.EphemDB())
    # generates tx trie
    for (i, tx) in enumerate(c.block.transactions):
        t.update(utils.sha3(rlp.encode(i)), rlp.encode(tx))

    # generates proof for each tx
    proofs = {}
    for (i, tx) in enumerate(c.block.transactions):
        proofs[str(i)] = get_merkle_proof(t.db, t.root, rlp.encode(i))

    # verify each tx proof
    for (i, proof) in proofs.items():
        tmp_db = trie.EphemDB()
        store_merkle_branch_nodes(tmp_db, proof)
        assert set(get_merkle_proof(tmp_db, t.root,
                                    rlp.encode(int(i)))) == set(proof)
        assert verify_merkle_proof(
            proof, t.root, utils.sha3(rlp.encode(int(i))), rlp.encode(c.block.transactions[int(i)]))


def test_account_proof():
    alloc = {}
    alloc[tester.a0] = {'balance': 10}
    c = chain(alloc)

    tx_sender_and_to = [tester.a0, utils.mk_contract_address(tester.a0, c.head_state.get_nonce(tester.a0))]
    test_account_proof_contract = c.contract(
        test_account_proof_code, value=10, language='viper',
        read_list=tx_sender_and_to,
        write_list=tx_sender_and_to)
    c.mine(1)

    addrs = [tester.a1, tester.a2, tester.a3]
    assert c.head_state.get_balance(test_account_proof_contract.address) == 10
    # send 1 wei to each of the accounts in addrs
    test_account_proof_contract.touch(
        addrs,
        read_list=addrs + tx_sender_and_to,
        write_list=addrs + tx_sender_and_to
    )
    assert c.head_state.get_balance(test_account_proof_contract.address) == 7
    # Can't get latest db update on head state, need to commit/mine it first
    c.mine(1)
    # for each account in addrs, generate and verify merkle proof
    for addr in addrs:
        proof = get_merkle_proof(c.head_state.trie.db,
                                 c.head_state.trie.root_hash, addr)
        acct_rlpdata = c.head_state.trie.get(addr)
        assert verify_merkle_proof(
            proof, c.head_state.trie.root_hash, utils.sha3(addr), acct_rlpdata)
    # try verifying proofs against wrong value
    try:
        verify_merkle_proof(proof, c.head_state.trie.root_hash, utils.sha3(addr),
                            bytes("wrong_value", encoding='utf-8'))
    except AssertionError:
        print("Can not verify proofs against wrong value")


def test_transaction_bundle():
    alloc = {}
    alloc[tester.a0] = {'balance': 10}
    c = chain(alloc)

    tx_sender_and_to = [
        tester.a0,
        utils.mk_contract_address(tester.a0, c.head_state.get_nonce(tester.a0))]
    test_account_proof_contract = c.contract(
        test_account_proof_code, value=10, language='viper',
        read_list=tx_sender_and_to,
        write_list=tx_sender_and_to)
    c.mine(1)

    # Take state snapshot
    ephem_state = c.chain.state.ephemeral_clone()

    # Block #2, first touch of the accounts
    not_yet_exits_accts = [tester.a4, tester.a5, tester.a6]
    assert c.head_state.get_balance(test_account_proof_contract.address) == 10
    # send 1 wei to each of the accounts in not_yet_exits_accts
    test_account_proof_contract.touch(
        not_yet_exits_accts,
        read_list=not_yet_exits_accts + tx_sender_and_to,
        write_list=not_yet_exits_accts + tx_sender_and_to)
    assert c.head_state.get_balance(test_account_proof_contract.address) == 7
    c.mine(1)

    # Make proofs for the accounts touched. Since they are touched
    # in block #3, proofs will be made based on storage root of
    # block #2
    block_2 = c.chain.get_block_by_number(2)
    block_3 = c.chain.get_block_by_number(3)
    tx_bundle_list = []
    for tx in block_3.transactions:
        tx_bundle_list.append(
            mk_confirmed_tx_bundle(
                c.chain.state,
                tx,
                block_2.header,
                block_3.header,
                ephem_state
            )
        )
    # Since touched accounts do not exist yet in block #1
    # there should be no proofs generated for them and
    
    # for bundle in tx_bundle_list:
    #     for k,v in bundle.items():
    #         print(k,":",v)
    
    # Foward 5 blocks
    c.mine(5)

    # Test tx bundle of pending tx
    from ethereum.transactions import Transaction
    pending_tx = Transaction(
        nonce=c.chain.state.get_nonce(tester.a0),
        gasprice=0,
        startgas=3141592,
        to=tester.a4,
        value=1,
        data=b'',
        read_list=[tester.a0, tester.a4],
        write_list=[tester.a0, tester.a4]
    ).sign(tester.k0)
    tx_bundle = mk_pending_tx_bundle(
        c.chain.state,
        pending_tx,
        c.chain.get_block_by_number(8).header
    )
    # Since tester.a4 is touched in block #2, there
    # should be proof of tester.a4
    for proof in tx_bundle["read_list_proof"]:
        for acct, wrapper in proof.items():
            if acct == tester.a4:
                assert wrapper["acct_rlpdata"]
    
    # Verify the tx bundle
    try:
        verify_tx_bundle(
            c.chain.env,
            c.chain.get_block_by_number(8).header.state_root,
            tester.a1,
            tx_bundle
        )
        print("This should not have happened")
    except KeyError:
        print("Shouldn't be able to verify since there's no proof of coinbase account in the tx bundle")
    # but first we need to add proof of coinbase account into the proof
    # Assume our account is tester.a1
    tx_bundle["read_list_proof"].append(
        {tester.a1: 
            mk_account_proof_wrapper(
                c.chain.state,
                c.chain.get_block_by_number(8).header,
                tester.a1
            )
        }
    )
    tx_bundle["write_list_proof"].append(
        {tester.a1: 
            mk_account_proof_wrapper(
                c.chain.state,
                c.chain.get_block_by_number(8).header,
                tester.a1
            )
        }
    )
    verify_tx_bundle(
        c.chain.env,
        c.chain.get_block_by_number(8).header.state_root,
        tester.a1,
        tx_bundle
    )


def test_stateless_client_on_bytearray_storage():
    alloc = {}
    alloc[tester.a1] = {'balance': 10}
    c = chain(alloc)
    
    # Skip a few blocks
    current_block_number = 1
    for i in range(3):
        c.mine(1)
        current_block_number += 1

    # Take state snapshot
    ephem_state = c.chain.state.ephemeral_clone()

    # Target transaction
    c.tx(sender=tester.k1, to=tester.a2, value=1, data=b'', read_list=[
         tester.a1, tester.a2], write_list=[tester.a1, tester.a2])
    c.mine(1)
    current_block_number += 1

    # Get the block that includes the target transaction
    current_block = c.chain.get_block_by_number(current_block_number)
    tx = current_block.transactions[0]
    # Get the block to build the proof on
    prev_block = c.chain.get_block_by_number(current_block_number-1)
    # Get the tx bundle of the target transaction
    tx_bundle = mk_confirmed_tx_bundle(c.chain.state, tx, prev_block.header, current_block.header, ephem_state)
    # Verify tx bundle
    assert verify_tx_bundle(c.chain.env, prev_block.header.state_root, prev_block.header.coinbase, tx_bundle)


    # Next test tx which modifies account storage
    tx_sender_and_to = [tester.a1, utils.mk_contract_address(tester.a1, c.head_state.get_nonce(tester.a1))]
    test_account_proof_contract = c.contract(
        test_account_proof_code, sender=tester.k1, value=5, language='viper',
        read_list=tx_sender_and_to,
        write_list=tx_sender_and_to)
    c.mine(1)
    current_block_number += 1
    assert c.chain.state.get_balance(tester.a1) == 4
    assert test_account_proof_contract.get_owner() == '0x' + utils.encode_hex(tester.a1)

    # Take state snapshot
    ephem_state = c.chain.state.ephemeral_clone()

    test_account_proof_contract.change_owner(tester.a2, sender=tester.k1, read_list=tx_sender_and_to, write_list=tx_sender_and_to)
    assert test_account_proof_contract.get_owner() == '0x' + utils.encode_hex(tester.a2)
    c.mine(1)
    current_block_number += 1

    # Get the block that includes the target transaction
    current_block = c.chain.get_block_by_number(current_block_number)
    tx = current_block.transactions[0]
    # Get the block to build the proof on
    prev_block = c.chain.get_block_by_number(current_block_number-1)
    # Get the tx bundle of the target transaction
    tx_bundle = mk_confirmed_tx_bundle(c.chain.state, tx, prev_block.header, current_block.header, ephem_state)
    # Verify tx bundle, set coinbase
    assert verify_tx_bundle(c.chain.env, prev_block.header.state_root, prev_block.header.coinbase, tx_bundle)

def test_stateless_client_on_trie_storage():
    alloc = {}
    alloc[tester.a0] = {'balance': 10}
    c = chain(alloc)
    current_block_number = 1

    contract_addr = utils.mk_contract_address(tester.a0, c.head_state.get_nonce(tester.a0))
    test_account_proof_contract = c.contract(
        test_account_proof_code, value=10, language='viper',
        read_list=[tester.a0, contract_addr], write_list=[tester.a0, contract_addr],
        accessible_storage_key_list=[(contract_addr + utils.encode_int32(0))])
    c.mine(1)
    current_block_number += 1
    # Take state snapshot
    ephem_state = c.chain.state.ephemeral_clone()

    arg = utils.sha3("set_map(int128,int128)")[:4] + utils.encode_int32(1) + utils.encode_int32(3)
    _, r_list, w_list, accessed_key_list = c.call(to=test_account_proof_contract.address, data=arg)
    test_account_proof_contract.set_map(1, 3, read_list=r_list, write_list=r_list, accessible_storage_key_list=list(accessed_key_list))
    c.mine(1)
    current_block_number += 1

    # Get the block that includes the target transaction
    current_block = c.chain.get_block_by_number(current_block_number)
    tx = current_block.transactions[0]
    # print(tx.accessible_storage_key_list)
    # Get the block to build the proof on
    prev_block = c.chain.get_block_by_number(current_block_number-1)
    # Get the tx bundle of the target transaction
    tx_bundle = mk_confirmed_tx_bundle(c.chain.state, tx, prev_block.header, current_block.header, ephem_state)
    # print(tx_bundle["read_list_proof"])
    # Verify tx bundle, set coinbase
    assert verify_tx_bundle(c.chain.env, prev_block.header.state_root, prev_block.header.coinbase, tx_bundle)