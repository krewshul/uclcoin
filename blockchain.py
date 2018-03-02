import time
import coincurve

from uclcoin import logger
from uclcoin.block import Block
from uclcoin.exceptions import (BlockchainException, ChainContinuityError,
                         GenesisBlockMismatch, InvalidHash,
                         InvalidTransactions)
from uclcoin.transaction import Transaction


class BlockChain(object):
    COINS_PER_BLOCK = 10
    MAX_TRANSACTIONS_PER_BLOCK = 50
    MINIMUM_HASH_DIFFICULTY = 6

    def __init__(self, blocks=None):
        self.blocks = []
        self.pending_transactions = []
        if not blocks:
            genesis_block = self._get_genesis_block()
            self.add_block(genesis_block)
        else:
            for block in blocks:
                self.add_block(block)

    def add_block(self, block):
        if self.validate_block(block):
            self.blocks.append(block)
            return True
        return False

    def calculate_hash_dificulty(self, index=None):
        return self.MINIMUM_HASH_DIFFICULTY

    def find_duplicate_transactions(self, transaction_hash):
        for block in self.blocks:
            for transaction in block.transactions:
                if transaction.tx_hash == transaction_hash:
                    return block.index
        return False

    def get_balance_pending(self, address):
        balance = self.get_balance(address)
        for transaction in self.pending_transactions:
            if transaction.source == address:
                balance -= transaction.amount + transaction.fee
            if transaction.destination == address:
                balance += transaction.amount
        return balance

    def get_balance(self, address):
        balance = 0
        for block in self.blocks:
            for transaction in block.transactions:
                if transaction.source == address:
                    balance -= transaction.amount + transaction.fee
                if transaction.destination == address:
                    balance += transaction.amount
        return balance

    def get_block_by_index(self, index):
        if index > len(self.blocks) - 1:
            return None
        return self.blocks[index]

    def get_latest_block(self):
        return self.blocks[-1]

    def get_minable_block(self, reward_address):
        transactions = []
        latest_block = self.get_latest_block()
        new_block_id = latest_block.index + 1
        previous_hash = latest_block.current_hash
        fees = 0

        for pending_transaction in self.pending_transactions:
            if pending_transaction is None:
                break
            if pending_transaction.tx_hash in [transaction.tx_hash for transaction in transactions]:
                continue
            if self.find_duplicate_transactions(pending_transaction.tx_hash):
                continue
            if not pending_transaction.verify():
                continue
            transactions.append(pending_transaction)
            fees += pending_transaction.fee
            if len(transactions) >= self.MAX_TRANSACTIONS_PER_BLOCK:
                break

        timestamp = int(time.time())

        reward_transaction = Transaction(
            "0",
            reward_address,
            self.get_reward(new_block_id) + fees,
            0,
            timestamp,
            "0"
        )
        transactions.append(reward_transaction)

        return Block(new_block_id, transactions, previous_hash, timestamp)

    def get_reward(self, index):
        return self.COINS_PER_BLOCK

    def remove_pending_transaction(self, transaction_hash):
        for i, t in enumerate(self.pending_transactions):
            if t.tx_hash == transaction_hash:
                self.pending_transactions.pop(i)
                return True
        return False

    def validate_block(self, block):
        try:
            # if genesis block, check if block is correct
            if block.index == 0:
                self._check_genesis_block(block)
                return True
            # current hash of data is correct and hash satisfies pattern
            self._check_hash_and_hash_pattern(block)
            # block index is correct and previous hash is correct
            self._check_index_and_previous_hash(block)
            # block reward is correct based on block index and halving formula
            self._check_transactions_and_block_reward(block)
        except BlockchainException as bce:
            logger.warning(f'Validation Error (block id: {bce.index}): {bce}')
            return False
        return True

    def validate_transaction(self, transaction):
        if transaction in self.pending_transactions:
            logger.warn(f'Transaction not valid.  Duplicate transaction detected: {transaction.tx_hash}')
            return False
        if self.find_duplicate_transactions(transaction.tx_hash):
            logger.warn(f'Transaction not valid.  Replay transaction detected: {transaction.tx_hash}')
            return False
        if not transaction.verify():
            logger.warn(f'Transaction not valid.  Invalid transaction signature: {transaction.tx_hash}')
            return False
        balance = self.get_balance(transaction.source)
        if transaction.amount + transaction.fee > balance:
            logger.warn(f'Transaction not valid.  Insufficient funds: {transaction.tx_hash}')
            return False
        return True

    def add_transaction(self, transaction):
        return self.push_pending_transaction(transaction)

    def push_pending_transaction(self, transaction):
        if self.validate_transaction(transaction):
            self.pending_transactions.append(transaction)
            return True
        return False

    def _check_genesis_block(self, block):
        if block != self._get_genesis_block():
            raise GenesisBlockMismatch(block.index, f'Genesis Block Mismatch: {block}')
        return

    def _check_hash_and_hash_pattern(self, block):
        hash_difficulty = self.calculate_hash_dificulty()
        if block.current_hash[:hash_difficulty].count('0') < hash_difficulty:
            raise InvalidHash(block.index, f'Incompatible Block Hash: {block.current_hash}')
        return

    def _check_index_and_previous_hash(self, block):
        latest_block = self.get_latest_block()
        if latest_block.index != block.index - 1:
            raise ChainContinuityError(block.index, f'Incompatible block index: {block.index-1}')
        if latest_block.current_hash != block.previous_hash:
            raise ChainContinuityError(block.index, f'Incompatible block hash: {block.index-1} and hash: {block.previous_hash}')
        return

    def _check_transactions_and_block_reward(self, block):
        reward_amount = self.get_reward(block.index)
        payers = dict()
        for transaction in block.transactions[:-1]:
            if self.find_duplicate_transactions(transaction.tx_hash):
                raise InvalidTransactions(block.index, "Transactions not valid.  Duplicate transaction detected")
            if not transaction.verify():
                raise InvalidTransactions(block.index, "Transactions not valid.  Invalid Transaction signature")
            if transaction.source in payers:
                payers[transaction.source] += transaction.amount  + transaction.fee
            else:
                payers[transaction.source] = transaction.amount  + transaction.fee
            reward_amount += transaction.fee
        for key in payers:
            balance = self.get_balance(key)
            if payers[key] > balance:
                raise InvalidTransactions(block.index, "Transactions not valid.  Insufficient funds")
        # last transaction is block reward
        reward_transaction = block.transactions[-1]
        if reward_transaction.amount != reward_amount or reward_transaction.source != "0":
            raise InvalidTransactions(block.index, "Transactions not valid.  Incorrect block reward")
        return

    def _get_genesis_block(self):
        genesis_transaction_one = Transaction(
            '0',
            '032b72046d335b5318a672763338b08b9642225189ab3f0cba777622cfee0fc07b',
            10,
            0,
            0,
            ''
        )
        genesis_transaction_two = Transaction(
            '0',
            '02f846677f65911f140a42af8fe7c1e5cbc7d148c44057ce49ee0cd0a72b21df4f',
            10,
            0,
            0,
            ''
        )
        genesis_transactions = [genesis_transaction_one, genesis_transaction_two]
        genesis_block = Block(0, genesis_transactions, '000000000000000000000000000000000000000000000000000000000000000000', 0, 27118821)
        return genesis_block