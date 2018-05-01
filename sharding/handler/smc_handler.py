import logging

from web3.contract import (
    Contract,
)

from eth_utils import (
    is_canonical_address,
    to_checksum_address,
    to_dict,
)


# Basic call context helper functions
@to_dict
def make_call_context(sender_address,
                      gas,
                      value=None,
                      gas_price=None,
                      data=None):
    if not is_canonical_address(sender_address):
        raise ValueError('sender_address should be provided in the canonical format')
    if not (isinstance(gas, int) and gas > 0):
        raise ValueError('gas should be provided as positive integer')
    # Both 'from' and 'gas' are required in eth_tester
    yield 'from', to_checksum_address(sender_address)
    yield 'gas', gas
    if value is not None:
        yield 'value', value
    if gas_price is not None:
        yield 'gas_price', gas_price
    if data is not None:
        yield 'data', data


# Basic transaction context helper functions
@to_dict
def make_transaction_context(nonce,
                             gas,
                             chain_id=None,
                             value=None,
                             gas_price=None,
                             data=None):
    if not (isinstance(nonce, int) and nonce >= 0):
        raise ValueError('nonce should be provided as non-negative integer')
    if not (isinstance(gas, int) and gas > 0):
        raise ValueError('gas should be provided as positive integer')
    yield 'nonce', nonce
    yield 'gas', gas
    yield 'chainId', chain_id
    if value is not None:
        yield 'value', value
    if gas_price is not None:
        yield 'gasPrice', gas_price
    if data is not None:
        yield 'data', data


class SMCHandler(Contract):

    logger = logging.getLogger("evm.chain.sharding.SMCHandler")

    _privkey = None
    _sender_address = None
    _config = None

    def __init__(self, *args, default_privkey, config, **kwargs):
        self._privkey = default_privkey
        self._sender_address = default_privkey.public_key.to_canonical_address()
        self._config = config

        super().__init__(*args, **kwargs)

    #
    # property
    #
    @property
    def private_key(self):
        return self._privkey

    @property
    def sender_address(self):
        return self._sender_address

    @property
    def config(self):
        return self._config

    @property
    def basic_call_context(self):
        return make_call_context(
            sender_address=self.sender_address,
            gas=self.config["DEFAULT_GAS"]
        )
    #
    # Public variable getter functions
    #

    def does_notary_exist(self, notary_address):
        return self.functions.does_notary_exist(notary_address).call(self.basic_call_context)

    def get_notary_info(self, notary_address):
        return self.functions.get_notary_info(notary_address).call(self.basic_call_context)

    def notary_pool_len(self):
        return self.functions.notary_pool_len().call(self.basic_call_context)

    def notary_pool(self, pool_index):
        return self.functions.notary_pool(pool_index).call(self.basic_call_context)

    def empty_slots_stack_top(self):
        return self.functions.empty_slots_stack_top().call(self.basic_call_context)

    def empty_slots_stack(self, stack_index):
        return self.functions.empty_slots_stack(stack_index).call(self.basic_call_context)

    def current_period_notary_sample_size(self):
        return self.functions.current_period_notary_sample_size().call(self.basic_call_context)

    def next_period_notary_sample_size(self):
        return self.functions.next_period_notary_sample_size().call(self.basic_call_context)

    def notary_sample_size_updated_period(self):
        return self.functions.notary_sample_size_updated_period().call(self.basic_call_context)

    def records_updated_period(self, shard_id):
        return self.functions.records_updated_period(shard_id).call(self.basic_call_context)

    def head_collation_period(self, shard_id):
        return self.functions.head_collation_period(shard_id).call(self.basic_call_context)

    def get_member_of_committee(self, shard_id, index):
        return self.functions.get_member_of_committee(
            shard_id,
            index,
        ).call(self.basic_call_context)

    def get_collation_chunk_root(self, period, shard_id):
        return self.functions.get_collation_chunk_root(
            period,
            shard_id,
        ).call(self.basic_call_context)

    def get_collation_proposer(self, period, shard_id):
        return self.functions.get_collation_proposer(
            period,
            shard_id,
        ).call(self.basic_call_context)

    def get_collation_is_elected(self, period, shard_id):
        return self.functions.get_collation_is_elected(
            period,
            shard_id,
        ).call(self.basic_call_context)

    def _send_transaction(self,
                          func_name,
                          args,
                          private_key=None,
                          nonce=None,
                          chain_id=None,
                          gas=None,
                          value=0,
                          gas_price=None,
                          data=None):
        if gas is None:
            gas = self.config['DEFAULT_GAS']
        if gas_price is None:
            gas_price = self.config['GAS_PRICE']
        if private_key is None:
            private_key = self.private_key
        if nonce is None:
            nonce = self.web3.eth.getTransactionCount(private_key.public_key.to_checksum_address())
        build_transaction_detail = make_transaction_context(
            nonce=nonce,
            gas=gas,
            chain_id=chain_id,
            value=value,
            gas_price=gas_price,
            data=data,
        )
        func_instance = getattr(self.functions, func_name)
        unsigned_transaction = func_instance(*args).buildTransaction(
            transaction=build_transaction_detail,
        )
        signed_transaction_dict = self.web3.eth.account.signTransaction(
            unsigned_transaction,
            private_key.to_hex(),
        )
        tx_hash = self.web3.eth.sendRawTransaction(signed_transaction_dict['rawTransaction'])
        return tx_hash

    #
    # Transactions
    #
    def register_notary(self, private_key=None, gas=None, gas_price=None):
        tx_hash = self._send_transaction(
            'register_notary',
            [],
            private_key=private_key,
            value=self.config['NOTARY_DEPOSIT'],
            gas=gas,
            gas_price=gas_price,
        )
        return tx_hash

    def deregister_notary(self, private_key=None, gas=None, gas_price=None):
        tx_hash = self._send_transaction(
            'deregister_notary',
            [],
            private_key=private_key,
            gas=gas,
            gas_price=gas_price,
        )
        return tx_hash

    def release_notary(self, private_key=None, gas=None, gas_price=None):
        tx_hash = self._send_transaction(
            'release_notary',
            [],
            private_key=private_key,
            gas=gas,
            gas_price=gas_price,
        )
        return tx_hash

    def add_header(
            self,
            period,
            shard_id,
            chunk_root,
            private_key=None,
            gas=None,
            gas_price=None,):
        tx_hash = self._send_transaction(
            'add_header',
            [
                period,
                shard_id,
                chunk_root,
            ],
            private_key=private_key,
            gas=gas,
            gas_price=gas_price,
        )
        return tx_hash
