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

test_mcopy_rawcode = bytes(bytearray([
    0x60, 0x17,
    0x56, # JUMP 23
    0x60, 0x20, 0x60, 0x00, 0x60, 0x40,
    0x37, # CALLDATACOPY 64 0 32
    0x60, 0x60, 0x60, 0x20, 0x60, 0x40,
    0x5c, # MCOPY 64 32 96
    0x60, 0x20, 0x60, 0x60,
    0xf3, # RETURN 96 32
    0x00, # STOP
    0x5b, # JUMPDEST
    0x60, 0x13, 0x60, 0x03, 0x61, 0x01, 0x40,
    0x39, # CODECOPY 320 3 20
    0x60, 0x13, 0x61, 0x01, 0x40,
    0xf3, # RETURN 320 20
]))

test_scopy_rawcode = bytes(bytearray([
    0x60, 0x1a,
    0x56, # JUMP 26
    0x60, 0x20, 0x60, 0x00, 0x60, 0x40,
    0x37, # CALLDATACOPY 64 0 32 --> CD1
    0x60, 0x20, 0x60, 0x20, 0x60, 0x60,
    0x37, # CALLDATACOPY 96 32 32 --> CD2
    0x60, 0x40,
    0x51, # MLOAD 64
    0x60, 0x20, 0x60, 0x60,
    0x5d, # SCOPY 96 32 CD1
    0x00, # STOP
    0x5b, # JUMPDEST
    0x60, 0x17, 0x60, 0x03, 0x61, 0x01, 0x40,
    0x39, # CODECOPY 320 3 23
    0x60, 0x17, 0x61, 0x01, 0x40,
    0xf3, # RETURN 320 23
]))

def test_read_write_access():
    # NOTE: tx.sender and tx.to and new contract address will be added to read/write list automatically
    alloc = {}
    alloc[tester.a1] = {'balance': 10}
    t = chain(alloc)

    # Deploy test storage layout contract
    storage_layout_contract = t.contract(test_new_storage_layout_code, language='viper')
    # Deploy test read write access contract
    read_write_access_contract = t.contract(test_read_write_access_code, language='viper')
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

    # storage_layout_contract = t.contract(test_new_storage_layout_code, language='viper', read_list=[tester.a0, addr_storage_layout_contract], write_list=[addr_storage_layout_contract])
    storage_layout_contract = t.contract(test_new_storage_layout_code, language='viper')
    storage_layout_contract.set_bt32(utils.encode_int32(499))
    assert storage_layout_contract.get_bt32() == utils.encode_int32(499)
    assert storage_layout_contract.get_number() == 9
    storage_layout_contract.set_num()
    assert storage_layout_contract.get_number() == 25
    # bts = bytes([i for i in range(120)])
    # storage_layout_contract.set_bts(bts)
    # assert storage_layout_contract.get_bts() == bts

def test_mcopy_opcode():
    alloc = {}
    t = chain(alloc)
    
    mcopy_contract_addr = t.contract(test_mcopy_rawcode, language='evm')
    # import binascii
    # print( binascii.hexlify(t.head_state.get_code(mcopy_contract_addr)))
    assert t.call(to=mcopy_contract_addr, data=utils.encode_int32(255)) == utils.encode_int32(255)
    t.mine(1)

def test_scopy_opcode():
    alloc = {}
    t = chain(alloc)
    
    scopy_contract_addr = t.contract(test_scopy_rawcode, language='evm')
    # import binascii
    # print( binascii.hexlify(t.head_state.get_code(scopy_contract_addr)))
    assert len(t.head_state.get_storage_data(scopy_contract_addr)) == 0
    # first arg specify storage slot to store, second arg is the data to be stored
    args = utils.encode_int32(2) + utils.encode_int32(281474976710655)
    t.tx(to=scopy_contract_addr, data=args)
    assert len(t.head_state.get_storage_data(scopy_contract_addr)) > 0
    t.mine(1)

def test_create2():
    alloc = {}
    t = chain(alloc, enable_constantipole=True)

    pre_addr = utils.mk_metropolis_contract_address(tester.a0, 3, test_scopy_rawcode)
    deployed_addr = t.contract(test_scopy_rawcode, language='evm', salt=3)
    assert pre_addr == deployed_addr
    import binascii
    print( binascii.hexlify(t.head_state.get_code(pre_addr)))
