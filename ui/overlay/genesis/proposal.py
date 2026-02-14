class GenesisProposal:
    """A Genesis improvement proposal."""
    def __init__(self, data: dict):
        self.id = data.get("id", 0)
        self.timestamp = data.get("timestamp", "")
        self.category = data.get("category", "unknown")
        self.description = data.get("description", "")[:200]
        self.confidence = data.get("confidence", 0.0)
        self.risk = data.get("risk", 0.0)
        self.status = data.get("status", "pending")
        self.code_snippet = data.get("code_snippet", "")
