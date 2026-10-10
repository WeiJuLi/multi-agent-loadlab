import time


class TokenBucket:
    """一個會持續補水的水桶。
    Imagine a bucket that can hold a certain amount of water (capacity). 
    Water is added to the bucket at a constant rate (refill_per_second). 
    Each request consumes a certain amount of water (amount). 
    If there isn't enough water in the bucket, 
    the request must wait until enough water has been added.

    - capacity：最多裝多少（也是一開始允許的突發量）
    - refill_per_second：每秒補多少
    - 每個請求舀走 amount；水不夠就要等，等多久可以算出來
    """

    def __init__(self, capacity: float, refill_per_second: float):
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        # 一開始是滿的：服務剛啟動時允許一波突發流量
        self.tokens = capacity
        self.updated_at = time.monotonic()

    def _refill(self) -> None:
        # 不用背景計時器定期補水：每次被問到時，才依「距離上次經過多久」一次補齊
        now = time.monotonic()
        elapsed = now - self.updated_at
        # 補水但不能溢出桶子
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.updated_at = now

    def seconds_until_available(self, amount: float) -> float:
        """0 = 現在就夠；> 0 = 還要等幾秒才夠。只查詢，不扣水。"""
        self._refill()
        if self.tokens >= amount:
            return 0.0
        # 缺多少 ÷ 每秒補多少 = 要等幾秒
        # 註：amount 比 capacity 還大時，算出來的秒數之後也永遠不會夠（見第 5 課「想一想」第 2 題）
        return (amount - self.tokens) / self.refill_per_second

    def consume(self, amount: float) -> None:
        # 呼叫前要先確認 seconds_until_available(amount) == 0
        self.tokens -= amount

    def reset(self) -> None:
        # 給 /admin/reset 用：桶子立刻補滿，從頭開始計時
        self.tokens = self.capacity
        self.updated_at = time.monotonic()


class RateLimiter:
    """RPM 和 TPM 兩個 token bucket；limit 為 0 代表不限。
    RPM = requests per minute；TPM = tokens per minute（prompt_tokens + max_tokens）。

    不需要加鎖：event loop 只有一條執行緒，而 try_acquire 裡面沒有 await，
    「檢查 + 扣除」不會被其他請求插隊，天生就是 atomic。
    """

    def __init__(self, rpm: int, tpm: int):
        self.buckets: list[tuple[TokenBucket, str]] = []
        if rpm > 0:
            # 容量 = 每分鐘上限；每秒補 rpm / 60
            self.buckets.append((TokenBucket(rpm, rpm / 60), "requests"))
        if tpm > 0:
            self.buckets.append((TokenBucket(tpm, tpm / 60), "tokens"))

    def try_acquire(self, token_cost: int) -> float:
        """0 = 通過（已扣除）；> 0 = 被限流，要等幾秒（什麼都沒扣）。"""
        # 每個請求：RPM 桶舀 1，TPM 桶舀 prompt_tokens + max_tokens
        costs = {"requests": 1, "tokens": token_cost}

        # 第一步：只問、不扣。任何一個桶不夠，就整個拒絕
        waits = [bucket.seconds_until_available(costs[kind]) for bucket, kind in self.buckets]
        # 取「最久」的那個：要等到兩個桶都夠，客戶端重試才會成功
        longest_wait = max(waits, default=0.0)
        if longest_wait > 0:
            return longest_wait

        # 第二步：兩個桶都夠，才一起扣。避免「RPM 扣了、TPM 卻不夠」白白浪費 RPM
        for bucket, kind in self.buckets:
            bucket.consume(costs[kind])
        return 0.0

    def reset(self) -> None:
        for bucket, _ in self.buckets:
            bucket.reset()
