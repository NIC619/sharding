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


data_feed_code = """
creator: address
values: num[num]

def __init__():
    self.creator = msg.sender

def set(k: num, v: num) -> num:
    if msg.sender == self.creator:
        self.values[k] = v
        return(1)
    else:
        return(0)

def get(k: num) -> num:
    return(self.values[k])
"""

example1 = t.contract(data_feed_code, language='viper')
output1 = example1.get(500, read_list=[example1.address])
assert output1 == 0

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

def f3() -> num:
    return(self.storage[0])
"""

example2 = t.contract(arither_code, language='viper')
example2.f2(read_list=[example2.address], write_list=[example2.address])
assert example2.f3(read_list=[example2.address]) == 1010

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
"""

example3 = t.contract(test_read_access_code, language='viper')
assert example3.read_balance(tester.a1, 10, read_list=[tester.a1])
assert example3.read_code_size(example2.address, read_list=[example2.address])
assert example3.read_write_storage(read_list=[example3.address], write_list=[example3.address])

t.tx(sender=tester.k1, to=tester.a2, value=1, data=b'', read_list=[example1.address, example2.address], write_list=[example3.address])
