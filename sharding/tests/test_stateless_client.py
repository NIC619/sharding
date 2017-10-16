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
                                             mk_tx_bundle)


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
creator: public(address)

@payable
def __init__():
    self.creator = msg.sender

def touch(addrs: address[3]):
    for i in range(3):
        send(addrs[i], 1)

def read_balance(addrs: address[2]) -> num(wei):
    return(addrs[0].balance + addrs[1].balance)
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
            proof, t.root, rlp.encode(c.block.transactions[int(i)]))


def test_account_proof():
    alloc = {}
    alloc[tester.a0] = {'balance': 10}
    c = chain(alloc)

    test_account_proof_contract = c.contract(
        test_account_proof_code, value=10, language='viper')

    addrs = [tester.a1, tester.a2, tester.a3]
    # try getting merkle proof of non-exist account
    try:
        get_merkle_proof(c.head_state.trie.db,
                         c.head_state.trie.root_hash, addrs[0])
    except AssertionError:
        print("Account does not exist yet, can not generate merkle proof")
    else:
        raise Exception(
            "Shouldn't be able to generate merkle proof of non-exist account")

    assert c.head_state.get_balance(test_account_proof_contract.address) == 10
    # send 1 wei to each of the accounts in addrs
    test_account_proof_contract.touch(addrs, read_list=addrs, write_list=addrs)
    assert c.head_state.get_balance(test_account_proof_contract.address) == 7
    # Can't get latest db update on head state, need to commit/mine it first
    c.mine(1)
    # for each account in addrs, generate and verify merkle proof
    for addr in addrs:
        proof = get_merkle_proof(c.head_state.trie.db,
                                 c.head_state.trie.root_hash, addr)
        acct_rlpdata = c.head_state.trie.get(addr)
        assert verify_merkle_proof(
            proof, c.head_state.trie.root_hash, acct_rlpdata)
    # try verifying proofs against wrong value
    try:
        verify_merkle_proof(proof, c.head_state.trie.root_hash,
                            bytes("wrong_value", encoding='utf-8'))
    except AssertionError:
        print("Can not verify proofs against wrong value")
    else:
        raise Exception(
            "Shouldn't be able to verify proofs against wrong value")


def test_transaction_bundle():
    alloc = {}
    alloc[tester.a0] = {'balance': 10}
    c = chain(alloc)

    tx_sender_and_to = [tester.a0, utils.mk_contract_address(tester.a0, c.head_state.get_nonce(tester.a0))]
    test_account_proof_contract = c.contract(
        test_account_proof_code, value=10, language='viper',
        read_list=tx_sender_and_to,
        write_list=tx_sender_and_to)
    c.mine(1)
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
        tx_bundle_list.append(mk_tx_bundle(c.chain.state.trie.db, tx, block_2.header, block_3.header))
    # Since touched accounts do not exist yet in block #1
    # there should be no proofs generated for them and
    # `exist_yet` should be True to indicate their non-existence
    # tx.sender and tx.to are exceptions since they already
    # exist in block #1
    
    c.mine(5)

    # Block #9, revisit the touched accounts.
    existing_accts = [tester.a4, tester.a5]
    assert test_account_proof_contract.read_balance(
        existing_accts,
        read_list=existing_accts + tx_sender_and_to,
        write_list=existing_accts + tx_sender_and_to) == 2
    c.mine(1)

    # Make proofs for the accounts touched. Since they are touched
    # in block #9, proofs will be made based on storage root of
    # block #8(or even earlier blocks)
    block_8 = c.chain.get_block_by_number(8)
    block_9 = c.chain.get_block_by_number(9)
    tx_bundle_list = []
    for tx in block_9.transactions:
        tx_bundle_list.append(mk_tx_bundle(c.chain.state.trie.db, tx, block_8.header, block_9.header))
    # Proofs should be generated for the existing accounts
    # for bundle in tx_bundle_list:
    #     for k,v in bundle.items():
    #         print(k,":",v)

def test_stateless_client_tx_processing_simulation():
    alloc = {}
    alloc[tester.a1] = {'balance': 10}
    c = chain(alloc)

    # Put the blocks in, assume pow is verified
    stateless_client = {"blocks": []}
    
    # Skip a few blocks
    current_block_number = 1
    for i in range(3):
        c.mine(1)
        current_block_number += 1
        current_block = c.chain.get_block_by_number(current_block_number)
        stateless_client["blocks"].append({"number": current_block.number,
            "state_root": current_block.header.state_root,
            "root_node": c.chain.state.trie.db.get(current_block.header.state_root)})
    # print(c.chain.state.trie.trie.get(utils.sha3(tester.a1)))
    # print("--------------------------------------------")
    # Target transaction
    c.tx(sender=tester.k1, to=tester.a2, value=1, data=b'', read_list=[
         tester.a1, tester.a2], write_list=[tester.a1, tester.a2])
    c.mine(1)
    # Get the block that includes the target transaction
    current_block_number += 1
    current_block = c.chain.get_block_by_number(current_block_number)
    stateless_client["blocks"].append({"number": current_block.number,
        "state_root": current_block.header.state_root,
        "root_node": c.chain.state.trie.db.get(current_block.header.state_root)})
    # Get the tx bundle of the target transaction
    prev_block = c.chain.get_block_by_number(current_block_number-1)
    tx = current_block.transactions[0]
    tx_bundle = mk_tx_bundle(c.chain.state.trie.db, tx, prev_block.header, current_block.header)
    # Store the root node of each block into db
    from ethereum.db import EphemDB, RefcountDB
    stateless_client_db = EphemDB()
    stateless_client_trie = trie.Trie(RefcountDB(stateless_client_db), prev_block.header.state_root)
    for blk in stateless_client["blocks"]:
        stateless_client_trie.db.put(key=blk["state_root"], value=blk["root_node"])
    
    # Verify the read list proof and store the nodes of the merkle branch in db
    for acct_proof_wrapper in tx_bundle["read_list_proof"]:
        for acct, wrapper in acct_proof_wrapper.items():
            blk_number = wrapper["blk_number"]
            state_root = b''
            # Find the matched block in state less client's block data
            for blk in stateless_client["blocks"]:
                if blk["number"] == blk_number:
                    state_root = blk["state_root"] 
            assert state_root == wrapper["state_root"]
            # If account exist, proof verified
            if wrapper["exist_yet"]:
                assert verify_merkle_proof(wrapper["merkle_proof"], wrapper["state_root"], wrapper["rlpdata"])
                # If account data does not stored yet, store it
                store_merkle_branch_nodes(stateless_client_trie.db, wrapper["merkle_proof"])
    # Do the same to write list proof
    for acct_proof_wrapper in tx_bundle["write_list_proof"]:
        for acct, wrapper in acct_proof_wrapper.items():
            blk_number = wrapper["blk_number"]
            state_root = b''
            # Find the matched block in state less client's block data
            for blk in stateless_client["blocks"]:
                if blk["number"] == blk_number:
                    state_root = blk["state_root"] 
            assert state_root == wrapper["state_root"]
            # If account exist and proof verified, store the nodes of the merkle branch in db
            if wrapper["exist_yet"]:
                assert verify_merkle_proof(wrapper["merkle_proof"], wrapper["state_root"], wrapper["rlpdata"])
                store_merkle_branch_nodes(stateless_client_trie.db, wrapper["merkle_proof"])
                # if stateless_client_trie.get(utils.sha3(acct)) != wrapper["rlpdata"]:
                #     store_merkle_branch_nodes(stateless_client_trie.db, wrapper["merkle_proof"])

    # Apply the transaction
    # Make ephemeral state
    from ethereum.state import State
    from ethereum.config import Env 
    from ethereum.messages import apply_transaction
    stateless_client_state = State(
        prev_block.header.state_root, Env(stateless_client_db,
        c.chain.env.config, c.chain.env.global_config))
    snapshot = stateless_client_state.snapshot()
    # Apply and verify the transaction
    success, _ = apply_transaction(stateless_client_state, tx)
    assert success
    assert stateless_client_state.get_balance(tester.a2) == 1
    stateless_client_state.revert(snapshot)
    # Store new nodes
    for updated_acct_data in tx_bundle["updated_acct_proof"]:
        for acct, wrapper in updated_acct_data.items():
            blk_number = wrapper["blk_number"]
            state_root = b''
            # Find the matched block in state less client's block data
            for blk in stateless_client["blocks"]:
                if blk["number"] == blk_number:
                    state_root = blk["state_root"] 
            assert state_root == wrapper["state_root"]
            assert verify_merkle_proof(wrapper["merkle_proof"], wrapper["state_root"], wrapper["rlpdata"])
            # Store the new account data after verifying the proof
            store_merkle_branch_nodes(stateless_client_trie.db, wrapper["merkle_proof"])
    # TODO:
    # Reject block prior to log on 
    