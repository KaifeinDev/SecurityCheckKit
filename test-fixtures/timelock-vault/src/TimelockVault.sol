// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title TimelockVault
/// @notice A fixed-term ETH savings vault: deposits are locked for seven
///         days, withdrawals pay out the full balance minus a flat protocol
///         fee, and the owner can pause new activity and sweep accrued fees.
contract TimelockVault {
    address public immutable owner;
    uint256 public constant LOCK_PERIOD = 7 days;
    uint256 public constant FEE_BPS = 30; // 0.30%

    mapping(address => uint256) public balances;
    mapping(address => uint256) public unlockAt;
    uint256 public accruedFees;
    bool public paused;

    event Deposited(address indexed user, uint256 amount, uint256 unlockAt);
    event Withdrawn(address indexed user, uint256 payout, uint256 fee);
    event FeesSwept(address indexed to, uint256 amount);
    event PausedSet(bool paused);

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    modifier whenNotPaused() {
        require(!paused, "paused");
        _;
    }

    /// @notice Deposit ETH; the entire balance is (re)locked for LOCK_PERIOD.
    function deposit() external payable whenNotPaused {
        require(msg.value > 0, "zero deposit");
        balances[msg.sender] += msg.value;
        unlockAt[msg.sender] = block.timestamp + LOCK_PERIOD;
        emit Deposited(msg.sender, msg.value, unlockAt[msg.sender]);
    }

    /// @notice Withdraw your full balance once the lock has expired.
    // slither-disable-start timestamp,reentrancy-events,low-level-calls
    // Dev Note: 鎖倉判斷依賴 block.timestamp，出塊者秒級誤差對 7 天定存無實質影響（可接受風險）。
    //           狀態（balances/accruedFees）皆於外部呼叫前更新（CEI），僅事件在呼叫後發出；
    //           call{value:} 為建議寫法且回傳值有檢查。
    function withdraw() external whenNotPaused {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "no balance");
        require(block.timestamp >= unlockAt[msg.sender], "still locked");
        uint256 fee = (amount * FEE_BPS) / 10_000;
        uint256 payout = amount - fee;
        balances[msg.sender] = 0;
        accruedFees += fee;
        (bool ok, ) = msg.sender.call{value: payout}("");
        require(ok, "transfer failed");
        emit Withdrawn(msg.sender, payout, fee);
    }
    // slither-disable-end timestamp,reentrancy-events,low-level-calls

    /// @notice Pause or resume deposits and withdrawals during incident response.
    function setPaused(bool value) external onlyOwner {
        paused = value;
        emit PausedSet(value);
    }

    /// @notice Send accrued protocol fees to the treasury address.
    // slither-disable-start reentrancy-events,low-level-calls
    // Dev Note: accruedFees 於外部呼叫前歸零（CEI）且函式有 onlyOwner 保護，僅事件順序問題；
    //           call{value:} 為建議寫法（國庫可能是多簽合約）且回傳值有檢查。
    function sweepFees(address payable to) external onlyOwner {
        require(to != address(0), "zero address");
        uint256 amount = accruedFees;
        require(amount > 0, "no fees");
        accruedFees = 0;
        (bool ok, ) = to.call{value: amount}("");
        require(ok, "transfer failed");
        emit FeesSwept(to, amount);
    }
    // slither-disable-end reentrancy-events,low-level-calls
}
