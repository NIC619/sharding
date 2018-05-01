from sharding.handler.utils.web3_utils import (
    mine,
)
from tests.handler.fixtures import (  # noqa: F401
    smc_handler,
)
from tests.contract.utils.common_utils import (
    batch_register,
    fast_forward,
)
from tests.contract.utils.notary_account import (
    NotaryAccount,
)
from tests.contract.utils.sample_helper import (
    sampling,
    get_committee_list,
    get_sample_result,
)


def test_normal_submit_vote(smc_handler):  # noqa: F811
    web3 = smc_handler.web3
    # We only vote in shard 0 for ease of testing
    shard_id = 0

    # Register notary 0~8 and fast forward to next period
    batch_register(smc_handler, 0, 8)
    fast_forward(smc_handler, 1)
    current_period = web3.eth.blockNumber // smc_handler.config['PERIOD_LENGTH']
    assert current_period == 1

    # Add collation record
    CHUNK_ROOT_1_0 = b'\x10' * 32
    smc_handler.add_header(
        current_period,
        shard_id,
        CHUNK_ROOT_1_0,
        private_key=NotaryAccount(0).private_key
    )
    mine(web3, 1)

    # Get the first notary in the sample list in this period
    sample_index = 0
    pool_index = sampling(smc_handler, shard_id)[sample_index]
    # Check that voting record does not exist prior to voting
    assert smc_handler.get_vote_count(shard_id) == 0
    assert not smc_handler.if_notary_has_vote(shard_id, sample_index)
    # First notary vote
    smc_handler.submit_vote(
        current_period,
        shard_id,
        CHUNK_ROOT_1_0,
        sample_index,
        private_key=NotaryAccount(pool_index).private_key
    )
    mine(web3, 1)
    # Check that vote has been casted successfully 
    assert smc_handler.get_vote_count(shard_id) == 1
    assert smc_handler.if_notary_has_vote(shard_id, sample_index)

    # Check that collation is not elected and forward to next period
    assert not smc_handler.get_collation_is_elected(current_period, shard_id)
    fast_forward(smc_handler, 1)
    current_period = web3.eth.blockNumber // smc_handler.config['PERIOD_LENGTH']
    assert current_period == 2

    # Add collation record
    CHUNK_ROOT_2_0 = b'\x20' * 32
    tx_hash = smc_handler.add_header(
        current_period,
        shard_id,
        CHUNK_ROOT_2_0,
        private_key=NotaryAccount(0).private_key
    )
    mine(web3, 1)
    
    # Check that vote count is zero
    assert smc_handler.get_vote_count(shard_id) == 0
    # Keep voting until the collation is elected.
    for (sample_index, pool_index) in enumerate(sampling(smc_handler, shard_id)):
        if smc_handler.get_collation_is_elected(current_period, shard_id):
            assert smc_handler.get_vote_count(shard_id) == smc_handler.config['QUORUM_SIZE']
            break
        # Check that voting record does not exist prior to voting
        assert not smc_handler.if_notary_has_vote(shard_id, sample_index)
        # Vote
        smc_handler.submit_vote(
            current_period,
            shard_id,
            CHUNK_ROOT_2_0,
            sample_index,
            private_key=NotaryAccount(pool_index).private_key
        )
        mine(web3, 1)
        # Check that vote has been casted successfully 
        assert smc_handler.if_notary_has_vote(shard_id, sample_index)


def test_submit_vote_by_notary_sampled_multiple_times(smc_handler):  #noqa: F811
    web3 = smc_handler.web3
    # We only vote in shard 0 for ease of testing
    shard_id = 0

    # Here we only register 5 notaries so it's guaranteed that at least
    # one notary is going to be sampled twice.
    # Register notary 0~4 and fast forward to next period
    batch_register(smc_handler, 0, 4)
    fast_forward(smc_handler, 1)
    current_period = web3.eth.blockNumber // smc_handler.config['PERIOD_LENGTH']
    assert current_period == 1

    # Add collation record
    CHUNK_ROOT_1_0 = b'\x10' * 32
    smc_handler.add_header(
        current_period,
        shard_id,
        CHUNK_ROOT_1_0,
        private_key=NotaryAccount(0).private_key
    )
    mine(web3, 1)

    # Find the notary that's sampled twice
    for pool_index in range(5):
        sample_index_list = [
            sample_index
            for (_, _shard_id, sample_index) in get_sample_result(smc_handler, pool_index)
            if _shard_id == shard_id
        ]
        if len(sample_index_list) > 1:
            for sample_index in sample_index_list:


def test_double_submit_vote(smc_handler):  # noqa: F811
    pass

def test_submit_vote_without_add_header_first(smc_handler):  # noqa: F811
    web3 = smc_handler.web3
    default_gas = smc_handler.config['DEFAULT_GAS']

    # Register notary 0~8 and fast forward to next period
    batch_register(smc_handler, 0, 8)
    fast_forward(smc_handler, 1)
    current_period = web3.eth.blockNumber // smc_handler.config['PERIOD_LENGTH']
    assert current_period == 1

    BLANK_CHUNK_ROOT = b'\x00' * 32
    CHUNK_ROOT_1_0 = b'\x10' * 32
    # Attempt to add collation record with wrong period specified
    tx_hash = smc_handler.add_header(0, 0, CHUNK_ROOT_1_0, private_key=NotaryAccount(0).private_key)
    mine(web3, 1)
    # Check that collation record of shard 0 has not been updated and transaction consume all gas
    assert smc_handler.records_updated_period(0) == 0
    assert smc_handler.get_collation_chunk_root(1, 0) == BLANK_CHUNK_ROOT
    assert web3.eth.getTransactionReceipt(tx_hash)['gasUsed'] == default_gas

    # Second attempt to add collation record with wrong period specified
    tx_hash = smc_handler.add_header(2, 0, CHUNK_ROOT_1_0, private_key=NotaryAccount(0).private_key)
    mine(web3, 1)
    # Check that collation record of shard 0 has not been updated and transaction consume all gas
    assert smc_handler.records_updated_period(0) == 0
    assert smc_handler.get_collation_chunk_root(1, 0) == BLANK_CHUNK_ROOT
    assert web3.eth.getTransactionReceipt(tx_hash)['gasUsed'] == default_gas

    # Add correct collation record
    smc_handler.add_header(1, 0, CHUNK_ROOT_1_0, private_key=NotaryAccount(0).private_key)
    mine(web3, 1)
    # Check that collation record of shard 0 has been updated
    assert smc_handler.records_updated_period(0) == 1
    assert smc_handler.get_collation_chunk_root(1, 0) == CHUNK_ROOT_1_0



def test_submit_vote_with_wrong_arguments(smc_handler):  # noqa: F811
    web3 = smc_handler.web3
    default_gas = smc_handler.config['DEFAULT_GAS']
    shard_count = smc_handler.config['SHARD_COUNT']

    # Register notary 0~8 and fast forward to next period
    batch_register(smc_handler, 0, 8)
    fast_forward(smc_handler, 1)
    current_period = web3.eth.blockNumber // smc_handler.config['PERIOD_LENGTH']
    assert current_period == 1

    BLANK_CHUNK_ROOT = b'\x00' * 32
    CHUNK_ROOT_1_0 = b'\x10' * 32
    # Attempt to add collation record with illegal shard_id specified
    tx_hash = smc_handler.add_header(1, shard_count+1, CHUNK_ROOT_1_0, private_key=NotaryAccount(0).private_key)
    mine(web3, 1)
    # Check that collation record of shard 0 has not been updated and transaction consume all gas
    assert smc_handler.records_updated_period(0) == 0
    assert smc_handler.get_collation_chunk_root(1, 0) == BLANK_CHUNK_ROOT
    assert web3.eth.getTransactionReceipt(tx_hash)['gasUsed'] == default_gas

    # Second attempt to add collation record with illegal shard_id specified
    tx_hash = smc_handler.add_header(1, -1, CHUNK_ROOT_1_0, private_key=NotaryAccount(0).private_key)
    mine(web3, 1)
    # Check that collation record of shard 0 has not been updated and transaction consume all gas
    assert smc_handler.records_updated_period(0) == 0
    assert smc_handler.get_collation_chunk_root(1, 0) == BLANK_CHUNK_ROOT
    assert web3.eth.getTransactionReceipt(tx_hash)['gasUsed'] == default_gas

    # Add correct collation record
    smc_handler.add_header(1, 0, CHUNK_ROOT_1_0, private_key=NotaryAccount(0).private_key)
    mine(web3, 1)
    # Check that collation record of shard 0 has been updated
    assert smc_handler.records_updated_period(0) == 1
    assert smc_handler.get_collation_chunk_root(1, 0) == CHUNK_ROOT_1_0


def test_submit_vote_then_deregister(smc_handler):  # noqa: F811
    web3 = smc_handler.web3
    default_gas = smc_handler.config['DEFAULT_GAS']

    # Register notary 0~8 and fast forward to next period
    batch_register(smc_handler, 0, 8)
    fast_forward(smc_handler, 1)
    current_period = web3.eth.blockNumber // smc_handler.config['PERIOD_LENGTH']
    assert current_period == 1

    CHUNK_ROOT_1_0 = b'\x10' * 32
    smc_handler.add_header(1, 0, CHUNK_ROOT_1_0, private_key=NotaryAccount(0).private_key)
    mine(web3, 1)
    # Check that collation record of shard 0 has been updated
    assert smc_handler.records_updated_period(0) == 1
    assert smc_handler.get_collation_chunk_root(1, 0) == CHUNK_ROOT_1_0

    # Attempt to add collation record again with same collation record
    tx_hash = smc_handler.add_header(1, 0, CHUNK_ROOT_1_0, private_key=NotaryAccount(0).private_key)
    mine(web3, 1)
    # Check that transaction consume all gas
    assert web3.eth.getTransactionReceipt(tx_hash)['gasUsed'] == default_gas

    # Attempt to add collation record again with different chunk root
    tx_hash = smc_handler.add_header(1, 0, b'\x56' * 32, private_key=NotaryAccount(0).private_key)
    mine(web3, 1)
    # Check that collation record of shard 0 remains the same and transaction consume all gas
    assert smc_handler.records_updated_period(0) == 1
    assert smc_handler.get_collation_chunk_root(1, 0) == CHUNK_ROOT_1_0
    assert web3.eth.getTransactionReceipt(tx_hash)['gasUsed'] == default_gas
