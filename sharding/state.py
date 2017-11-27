import rlp
from ethereum.utils import normalize_address, hash32, trie_root, \
    big_endian_int, address, int256, encode_hex, encode_int, \
    big_endian_to_int, int_to_addr, zpad, parse_as_bin, parse_as_int, \
    decode_hex, sha3, is_string, is_numeric
from rlp.sedes import big_endian_int, Binary, binary, CountableList
from ethereum import utils
from sharding import trie
from sharding.trie import Trie
from sharding.securetrie import SecureTrie
from ethereum.config import default_config, Env
from ethereum.block import FakeHeader
from ethereum.db import BaseDB, EphemDB, OverlayDB, RefcountDB
from ethereum.specials import specials as default_specials
import copy
import sys
if sys.version_info.major == 2:
    from repoze.lru import lru_cache
else:
    from functools import lru_cache


BLANK_HASH = utils.sha3(b'')
BLANK_ROOT = utils.sha3rlp(b'')


def snapshot_form(val):
    if is_numeric(val):
        return str(val)
    elif is_string(val):
        return '0x' + encode_hex(val)


STATE_DEFAULTS = {
    "txindex": 0,
    "gas_used": 0,
    "gas_limit": 3141592,
    "block_number": 0,
    "block_coinbase": '\x00' * 20,
    "block_difficulty": 1,
    "timestamp": 0,
    "logs": [],
    "receipts": [],
    "bloom": 0,
    "suicides": [],
    "recent_uncles": {},
    "prev_headers": [],
    "refunds": 0,
}


# from ethereum.state import State
class State():

    def __init__(self, root=b'', env=Env(), executing_on_head=False, **kwargs):
        self.env = env
        self.trie = SecureTrie(Trie(RefcountDB(self.db), root))
        for k, v in STATE_DEFAULTS.items():
            setattr(self, k, kwargs.get(k, copy.copy(v)))
        self.journal = []
        self.cache = {}
        self.log_listeners = []
        self.deletes = []
        self.changed = {}
        self.executing_on_head = executing_on_head

    @property
    def db(self):
        return self.env.db

    @property
    def config(self):
        return self.env.config

    def get_block_hash(self, n):
        if self.block_number < n or n > 256 or n < 0:
            o = b'\x00' * 32
        else:
            o = self.prev_headers[n].hash if self.prev_headers[n] else b'\x00' * 32
        return o

    def add_block_header(self, block_header):
        self.prev_headers = [block_header] + self.prev_headers

    def get_balance(self, address):
        return self.trie.get(utils.normalize_address(address) + b'\x01')

    def get_code(self, address):
        return self.trie.get(utils.normalize_address(address) + b'\x02')

    def get_nonce(self, address):
        return self.trie.get(utils.normalize_address(address) + b'\x00')

    def set_balance(self, address, value):
        address = utils.normalize_address(address)
        old_value = self.get_balance(address)
        self.journal.append(lambda: self.trie.update(address + b'\x01', old_value))
        self.cache[address + b'\x01'] = value

    def set_code(self, address, value):
        address = utils.normalize_address(address)
        old_value = self.get_code(address)
        self.journal.append(lambda: self.trie.update(address + b'\x02', old_value))
        self.cache[address + b'\x02'] = value

    def set_nonce(self, address, value):
        address = utils.normalize_address(address)
        old_value = self.get_nonce(address)
        self.journal.append(lambda: self.trie.update(address + b'\x00', old_value))
        self.cache[address + b'\x00'] = value

    def delta_balance(self, address, value):
        address = utils.normalize_address(address)
        old_value = self.get_balance(address)
        self.journal.append(lambda: self.trie.update(address + b'\x01', old_value))
        self.cache[address + b'\x01'] = old_value + value

    def increment_nonce(self, address):
        address = utils.normalize_address(address)
        old_nonce = self.get_nonce(address)
        self.journal.append(lambda: self.trie.update(address + b'\x00', old_nonce))
        self.cache[address + b'\x00'] = old_nonce + 1

    def get_storage_data(self, address, key):
        return self.trie.get(utils.normalize_address(address) + b'\x03' + utils.sha3(key))

    def set_storage_data(self, address, key, value):
        address = utils.normalize_address(address)
        old_value = self.get_storage_data(address, key)
        self.journal.append(lambda: self.set_storage_data(address + b'\x03' + utils.sha3(key), old_value))
        self.cache[address + b'\x03' + utils.sha3(key)] = value

    def add_suicide(self, address):
        self.suicides.append(address)
        self.journal.append(lambda: self.suicides.pop())

    def add_log(self, log):
        for listener in self.log_listeners:
            listener(log)
        self.logs.append(log)
        self.journal.append(lambda: self.logs.pop())

    def add_receipt(self, receipt):
        self.receipts.append(receipt)
        self.journal.append(lambda: self.receipts.pop())

    def add_refund(self, value):
        preval = self.refunds
        self.refunds += value
        self.journal.append(lambda: setattr(self.refunds, preval))

    def snapshot(self):
        return (self.trie.root_hash, len(self.journal), {
                k: copy.copy(getattr(self, k)) for k in STATE_DEFAULTS})

    def revert(self, snapshot):
        h, L, auxvars = snapshot
        while len(self.journal) > L:
            try:
                lastitem = self.journal.pop()
                lastitem()
            except Exception as e:
                print(e)
        if h != self.trie.root_hash:
            assert L == 0
            self.trie.root_hash = h
            self.cache = {}
        for k in STATE_DEFAULTS:
            setattr(self, k, copy.copy(auxvars[k]))

    def set_param(self, k, v):
        preval = getattr(self, k)
        self.journal.append(lambda: setattr(self, k, preval))
        setattr(self, k, v)

    def is_SERENITY(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['SERENITY_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['SERENITY_FORK_BLKNUM']

    def is_HOMESTEAD(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['HOMESTEAD_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['HOMESTEAD_FORK_BLKNUM']

    def is_METROPOLIS(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['METROPOLIS_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['METROPOLIS_FORK_BLKNUM']

    def is_CONSTANTINOPLE(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['CONSTANTINOPLE_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['CONSTANTINOPLE_FORK_BLKNUM']

    def is_ANTI_DOS(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['ANTI_DOS_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['ANTI_DOS_FORK_BLKNUM']

    def is_SPURIOUS_DRAGON(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['SPURIOUS_DRAGON_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['SPURIOUS_DRAGON_FORK_BLKNUM']

    def is_DAO(self, at_fork_height=False):
        if at_fork_height:
            return self.block_number == self.config['DAO_FORK_BLKNUM']
        else:
            return self.block_number >= self.config['DAO_FORK_BLKNUM']

    def transfer_value(self, from_addr, to_addr, value):
        assert value >= 0
        if self.get_balance(from_addr) >= value:
            self.delta_balance(from_addr, -value)
            self.delta_balance(to_addr, value)
            return True
        return False

    def account_to_dict(self, address):
        address = utils.normalize_address(address)
        return {'balance': str(self.get_balance(address)), 'nonce': str(self.get_nonce(address)), 'code': '0x' + encode_hex(self.get_code(address))}

    def commit(self, allow_empties=False):
        for key, value in self.cache.items():
            addr = key[:20]
            self.trie.update(key, value)
            self.changed[addr] = True
        self.cache = {}
        self.journal = []

    def to_dict(self):
        return self.trie.to_dict()

    # Creates a snapshot from a state
    def to_snapshot(self, root_only=False, no_prevblocks=False):
        snapshot = {}
        if root_only:
            # Smaller snapshot format that only includes the state root
            # (requires original DB to re-initialize)
            snapshot["state_root"] = '0x' + encode_hex(self.trie.root_hash)
        else:
            # "Full" snapshot
            snapshot["full_trie"] = self.to_dict()
        # Save non-state-root variables
        for k, default in STATE_DEFAULTS.items():
            default = copy.copy(default)
            v = getattr(self, k)
            if is_numeric(default):
                snapshot[k] = str(v)
            elif isinstance(default, (str, bytes)):
                snapshot[k] = '0x' + encode_hex(v)
            elif k == 'prev_headers' and not no_prevblocks:
                snapshot[k] = [prev_header_to_dict(
                    h) for h in v[:self.config['PREV_HEADER_DEPTH']]]
            elif k == 'recent_uncles' and not no_prevblocks:
                snapshot[k] = {str(n): ['0x' + encode_hex(h)
                                        for h in headers] for n, headers in v.items()}
        return snapshot

    # Creates a state from a snapshot
    @classmethod
    def from_snapshot(cls, snapshot_data, env, executing_on_head=False):
        state = State(env=env)
        if "full_trie" in snapshot_data:
            for key, data in snapshot_data["full_trie"].items():
                addr = key[:20]
                if key[20] == b'\x00':
                    state.set_nonce(key, data))
                if key[20] == b'\x01':
                    state.set_balance(key, data))
                if key[20] == b'\x02':
                    state.set_code(key, data))
                if key[20] == b'\x03':
                    state.set_storage_data(key, data))
        elif "state_root" in snapshot_data:
            state.trie.root_hash = parse_as_bin(snapshot_data["state_root"])
        else:
            raise Exception(
                "Must specify either alloc or state root parameter")
        for k, default in STATE_DEFAULTS.items():
            default = copy.copy(default)
            v = snapshot_data[k] if k in snapshot_data else None
            if is_numeric(default):
                setattr(state, k, parse_as_int(v)
                        if k in snapshot_data else default)
            elif is_string(default):
                setattr(state, k, parse_as_bin(v)
                        if k in snapshot_data else default)
            elif k == 'prev_headers':
                if k in snapshot_data:
                    headers = [dict_to_prev_header(h) for h in v]
                else:
                    headers = default
                setattr(state, k, headers)
            elif k == 'recent_uncles':
                if k in snapshot_data:
                    uncles = {}
                    for height, _uncles in v.items():
                        uncles[int(height)] = []
                        for uncle in _uncles:
                            uncles[int(height)].append(parse_as_bin(uncle))
                else:
                    uncles = default
                setattr(state, k, uncles)
        if executing_on_head:
            state.executing_on_head = True
        state.commit()
        state.changed = {}
        return state

    def ephemeral_clone(self):
        snapshot = self.to_snapshot(root_only=True, no_prevblocks=True)
        env2 = Env(OverlayDB(self.env.db), self.env.config)
        s = State.from_snapshot(snapshot, env2)
        for param in STATE_DEFAULTS:
            setattr(s, param, getattr(self, param))
        s.recent_uncles = self.recent_uncles
        s.prev_headers = self.prev_headers
        s.journal = copy.copy(self.journal)
        s.cache = {}
        return s


def prev_header_to_dict(h):
    return {
        "hash": '0x' + encode_hex(h.hash),
        "number": str(h.number),
        "timestamp": str(h.timestamp),
        "difficulty": str(h.difficulty),
        "gas_used": str(h.gas_used),
        "gas_limit": str(h.gas_limit),
        "uncles_hash": '0x' + encode_hex(h.uncles_hash)
    }


BLANK_UNCLES_HASH = sha3(rlp.encode([]))


def dict_to_prev_header(h):
    return FakeHeader(hash=parse_as_bin(h['hash']),
                      number=parse_as_int(h['number']),
                      timestamp=parse_as_int(h['timestamp']),
                      difficulty=parse_as_int(h['difficulty']),
                      gas_used=parse_as_int(h.get('gas_used', '0')),
                      gas_limit=parse_as_int(h['gas_limit']),
                      uncles_hash=parse_as_bin(h.get('uncles_hash', '0x' + encode_hex(BLANK_UNCLES_HASH))))
