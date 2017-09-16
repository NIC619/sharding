import rlp
# import serpent
from viper import compiler
from ethereum.slogging import get_logger
from ethereum import utils
from ethereum.tools import tester

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


alloc = {}
alloc[tester.a1] = {'balance': 10}
t = chain(alloc)


test_storage_code = """
creator: address
value: num
value2: bytes32
value3: bytes <= 160

def __init__():
    self.creator = msg.sender

def set_num(v: num):
    if msg.sender == self.creator:
        self.value = v

def get_num() -> num:
    return(self.value)

def set_bt(v: bytes32):
    if msg.sender == self.creator:
        self.value2 = v

def get_bt() -> bytes32:
    return(self.value2)

# def set_bts(v: bytes <= 160):
#     if msg.sender == self.creator:
#         self.value3 = v

# def get_bts() -> bytes <= 160:
#     return(self.value3)
"""

# NOTE: tx.sender and tx.to and new contract address will be added to read/write list automatically
nonce = utils.encode_int(t.head_state.get_nonce(tester.a0))
addr_example1 = utils.mk_contract_address(tester.a0, nonce)
# example1 = t.contract(test_storage_code, language='viper', read_list=[tester.a0, addr_example1], write_list=[addr_example1])
example1 = t.contract(test_storage_code, language='viper')
assert addr_example1 == example1.address
example1.set_bt(utils.encode_int32(499))
assert example1.get_bt() == utils.encode_int32(499)
example1.set_num(399)
assert example1.get_num() == 399
bts = bytes([i for i in range(120)])
# example1.set_bts(bts)
# assert example1.get_bts() == bts
assert False

arither_code = """
storage: num[num]

def __init__():
    self.storage[0] = 10

def f1():
    self.storage[0] += 1

def f2():
    self.storage[0] *= 10
    self.f1()
    self.storage[0] *= 10
@constant
def f3() -> num:
    return(self.storage[0])
"""

nonce = utils.encode_int(t.head_state.get_nonce(tester.a0))
addr_example2 = utils.mk_contract_address(tester.a0, nonce)
example2 = t.contract(arither_code, language='viper')
assert addr_example2 == example2.address
example2.f2()
assert example2.f3() == 1010

test_read_access_code = """
storage: num[num]

def read_balance(addr: address, v: wei_value) -> num:
    if addr.balance == v:
        return(1)
    else:
        return(0)
def read_code_size(addr: address) -> num:
    if addr.codesize > 0:
        return(1)
    else:
        return(0)
def read_write_storage() -> num:
    self.storage[3] = 99
    if self.storage[3] == 99:
        return(1)
    else:
        return(0)
def track_storage_modified(addr: address, raw_call_data: bytes <= 8):
    self.storage[1] = 111
    raw_call(addr, raw_call_data, gas=50000, outsize=0)
"""
nonce = utils.encode_int(t.head_state.get_nonce(tester.a0))
addr_example3 = utils.mk_contract_address(tester.a0, nonce)
example3 = t.contract(test_read_access_code, language='viper')
assert example3.read_balance(tester.a1, 10, read_list=[tester.a1])
assert example3.read_code_size(example2.address, read_list=[example2.address])
assert example3.read_write_storage()
example3.track_storage_modified(example2.address, utils.sha3("f1()")[:8], read_list=[example2.address], write_list=[example2.address])
assert example2.f3() == 1011

t.tx(sender=tester.k1, to=tester.a2, value=1, data=b'', read_list=[example1.address, example2.address], write_list=[example3.address])
# t.mine(1)