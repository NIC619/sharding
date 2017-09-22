import pytest
import logging

import rlp
# import serpent
from viper import compiler
from ethereum.slogging import get_logger
from ethereum import utils
from ethereum.tools import tester

# from sharding.tools import tester
# from sharding import validator_manager_utils

# log = get_logger('test.account_redesign')
# log.setLevel(logging.DEBUG)


@pytest.fixture(scope='function')
def chain(alloc={}, genesis_gas_limit=4712388, min_gas_limit=5000, startgas=3141592):
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
    c.mine(1)
    return c

# List of contract code to test
test_read_write_access_code = """
number: public(num)

@constant
def read_balance(addr: address, v: wei_value) -> num:
    if addr.balance == v:
        return(1)
    else:
        return(0)

@constant
def read_code_size(addr: address) -> num:
    if addr.codesize > 0:
        return(1)
    else:
        return(0)

def write_storage():
    self.number = 99

def cross_contract_read_write_storage(addr: address, raw_call_data: bytes <= 4):
    self.number = 1111
    raw_call(addr, raw_call_data, gas=50000, outsize=0)
"""

test_new_storage_layout_code = """
creator: public(address)
number: public(num)
bt32: public(bytes32)
bts: public(bytes <= 160)
mp: public(num[num])

def __init__():
    self.creator = msg.sender
    self.number = 9

def set_creator(addr: address):
    if msg.sender == self.creator:
        self.creator = addr

def set_num():
    self.number = 25

def set_bt32(v: bytes32):
    if msg.sender == self.creator:
        self.bt32 = v

# def set_bts(v: bytes <= 160):
#     if msg.sender == self.creator:
#         self.bts = v
# 
# def set_mp(k:num, v:num):
#     if msg.sender == self.creator
#     mp[k] = v
"""

test_scopy_opcode_code = """
number: public(num)
bt32: public(bytes32)
bts: public(bytes <= 160)

def set_num(v: num):
    self.number = v

def set_bt32(v: bytes32):
    self.bt32 = v

# def set_bts(v: bytes <= 160):
#     self.bts = v
"""

def test_read_write_access():
    alloc = {}
    alloc[tester.a1] = {'balance': 10}
    t = chain(alloc)

    # Deploy test storage layout contract
    nonce = utils.encode_int(t.head_state.get_nonce(tester.a0))
    addr_storage_layout_contract = utils.mk_contract_address(tester.a0, nonce)
    storage_layout_contract = t.contract(test_new_storage_layout_code, language='viper')
    assert addr_storage_layout_contract == storage_layout_contract.address
    # Deploy test read write access contract
    nonce = utils.encode_int(t.head_state.get_nonce(tester.a0))
    addr_read_write_access_contract = utils.mk_contract_address(tester.a0, nonce)
    read_write_access_contract = t.contract(test_read_write_access_code, language='viper')
    assert addr_read_write_access_contract == read_write_access_contract.address
    # Test read balance
    assert read_write_access_contract.read_balance(tester.a1, 10, read_list=[tester.a1])
    # Test read code size
    assert read_write_access_contract.read_code_size(storage_layout_contract.address, read_list=[storage_layout_contract.address])
    # Test write then read storage
    read_write_access_contract.write_storage()
    assert read_write_access_contract.get_number() == 99
    # Test cross contract read and write storage
    assert storage_layout_contract.get_number() == 9
    read_write_access_contract.cross_contract_read_write_storage(storage_layout_contract.address, utils.sha3("set_num()")[:4], read_list=[storage_layout_contract.address], write_list=[storage_layout_contract.address])
    assert read_write_access_contract.get_number() == 1111
    assert storage_layout_contract.get_number() == 25
    # Test value transfer
    t.tx(sender=tester.k1, to=tester.a2, value=1, data=b'', read_list=[], write_list=[])
    # log.info('CURRENT HEAD:{}'.format(encode_hex(t.chain.shards[shard_id].head_hash)))

def test_storage_layout():
    alloc = {}
    t = chain(alloc)

    # NOTE: tx.sender and tx.to and new contract address will be added to read/write list automatically
    nonce = utils.encode_int(t.head_state.get_nonce(tester.a0))
    addr_storage_layout_contract = utils.mk_contract_address(tester.a0, nonce)
    # storage_layout_contract = t.contract(test_new_storage_layout_code, language='viper', read_list=[tester.a0, addr_storage_layout_contract], write_list=[addr_storage_layout_contract])
    storage_layout_contract = t.contract(test_new_storage_layout_code, language='viper')
    assert addr_storage_layout_contract == storage_layout_contract.address
    storage_layout_contract.set_bt32(utils.encode_int32(499))
    assert storage_layout_contract.get_bt32() == utils.encode_int32(499)
    assert storage_layout_contract.get_number() == 9
    storage_layout_contract.set_num()
    assert storage_layout_contract.get_number() == 25
    # bts = bytes([i for i in range(120)])
    # storage_layout_contract.set_bts(bts)
    # assert storage_layout_contract.get_bts() == bts

def test_scopy_opcode():
    alloc = {}
    t = chain(alloc)
    
    # nonce = utils.encode_int(t.head_state.get_nonce(tester.a0))
    # addr_scopy_opcode_contract = utils.mk_contract_address(tester.a0, nonce)
    # scopy_opcode_contract = t.contract(test_scopy_opcode_code, language='viper')
    # scopy_opcode_contract.set_num(7440)
    # scopy_opcode_contract.set_bt32(utils.encode_int32(7440))
    rawcode = bytearray([0x61, 0x01, 0x40, 0x61, 0x01, 0x40, 0x52, 0x61, 0x01, 0x41, 0x61, 0x01, 0x60, 0x52, 0x60, 0x02, 0x60, 0x40, 0x61, 0x01, 0x40, 0x5d, 0x00])
    nonce = utils.encode_int(t.head_state.get_nonce(tester.a0))
    addr_rawcode = utils.mk_contract_address(tester.a0, nonce)
    # addr_rawcode = t.contract(bytes(rawcode), language='evm')
    assert len(t.head_state.get_storage_data(addr_rawcode)) == 0
    t.head_state.set_code(addr_rawcode, bytes(rawcode))
    t.tx(to=addr_rawcode)
    assert len(t.head_state.get_storage_data(addr_rawcode)) > 0
