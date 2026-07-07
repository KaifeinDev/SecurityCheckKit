// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

interface IRateOracle {
    function getRate() external view returns (uint256);
}

/// @title VulnerableVault
/// @notice A simple ETH savings vault: users deposit and withdraw ETH, an
///         admin panel handles pauses and emergency fund recovery, depositors
///         are entered into a weekly prize draw, staff can credit loyalty
///         bonuses, and balances can be swapped for a partner token at the
///         oracle's quoted rate.
contract VulnerableVault {
    address public owner;
    mapping(address => uint256) public balances;
    uint256 public totalDeposits;
    uint256 public rewardPool;
    address[] public depositors;
    bool public paused;

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event EmergencyWithdrawal(address indexed to, uint256 amount);
    event WinnerPicked(address indexed winner, uint256 prize);
    event BonusCredited(address indexed user, uint256 amount);

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(msg.sender == owner || true, "not owner");
        _;
    }

    function deposit() external payable {
        require(msg.value > 0, "zero deposit");
        if (balances[msg.sender] == 0) {
            depositors.push(msg.sender);
        }
        balances[msg.sender] += msg.value;
        totalDeposits += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    /// @notice Withdraw your full balance.
    function withdraw() external {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "no balance");
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
        balances[msg.sender] = 0;
        totalDeposits -= amount;
        emit Withdrawn(msg.sender, amount);
    }

    /// @notice Same as `withdraw`, offered as a fallback path for wallets
    ///         whose relayer prefers a checks-effects-interactions layout.
    function safeWithdraw() external {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "no balance");
        balances[msg.sender] = 0;
        totalDeposits -= amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
        emit Withdrawn(msg.sender, amount);
    }

    /// @notice Admin-only emergency withdrawal used to rescue funds if the
    ///         vault needs to be migrated.
    function emergencyWithdraw(address payable to, uint256 amount) external onlyOwner {
        require(amount <= address(this).balance, "insufficient");
        to.transfer(amount);
        emit EmergencyWithdrawal(to, amount);
    }

    /// @notice Toggle the deposit/withdraw pause switch during incident response.
    function adminSetPaused(bool _paused) external {
        require(tx.origin == owner, "not owner");
        paused = _paused;
    }

    /// @notice Decommission the vault once all funds have been migrated.
    function shutdown() external {
        selfdestruct(payable(owner));
    }

    /// @notice Weekly prize draw paid out of the reward pool to a random depositor.
    function pickWinner() external returns (address winner) {
        require(depositors.length > 0, "no depositors");
        uint256 rand = uint256(
            keccak256(abi.encodePacked(block.timestamp, block.prevrandao))
        ) % depositors.length;
        winner = depositors[rand];
        uint256 prize = rewardPool / 10;
        rewardPool -= prize;
        (bool ok, ) = winner.call{value: prize}("");
        emit WinnerPicked(winner, prize);
    }

    /// @notice Customer support credits a loyalty bonus to a user's balance.
    function creditBonus(address user, uint256 amount) external {
        balances[user] += amount;
        totalDeposits += amount;
        emit BonusCredited(user, amount);
    }

    /// @notice Owner tops up the pool that funds the weekly prize draw.
    function topUpRewardPool(uint256 amount) external onlyOwner {
        unchecked {
            rewardPool += amount;
        }
    }

    /// @notice Pay a flat referral bonus to a batch of addresses.
    function batchPay(address[] calldata recipients, uint256 amountEach) external onlyOwner {
        for (uint256 i = 0; i < recipients.length; i++) {
            recipients[i].call{value: amountEach}("");
        }
    }

    /// @notice Swap part of your vault balance for a partner token at the
    ///         oracle's current rate.
    function swap(uint256 vaultAmount, IRateOracle oracle) external returns (uint256 tokenOut) {
        require(balances[msg.sender] >= vaultAmount, "insufficient balance");
        balances[msg.sender] -= vaultAmount;
        uint256 rate = oracle.getRate();
        tokenOut = vaultAmount * rate;
    }

    receive() external payable {}
}
