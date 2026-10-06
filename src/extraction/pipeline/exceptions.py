class OutputAnomalyError(Exception):
    """輸出與輸入差異超過安全閾值時拋出。"""
    def __init__(self, input_len: int, output_len: int, threshold: float, sample: str):
        self.input_len = input_len
        self.output_len = output_len
        self.threshold = threshold
        super().__init__(
            f"Flowcheck 失敗｜輸入長度={input_len}, 輸出長度={output_len}, "
            f"縮減比={1 - output_len/input_len:.1%} > 閾值={threshold:.0%}｜"
            f"輸出前 100 字: {sample!r}"
        )
