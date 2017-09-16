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


def test_transaction_format():
    alloc = {}
    alloc[tester.a1] = {'balance': 10}
    t = chain(alloc)

    t.tx(sender=tester.k1, to=tester.a2, value=1, data=b'')
    # log.info('CURRENT HEAD:{}'.format(encode_hex(t.chain.shards[shard_id].head_hash)))
