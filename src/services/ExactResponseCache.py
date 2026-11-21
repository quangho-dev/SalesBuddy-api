import hashlib


class ExactResponseCache:
    """Minimal exact-match response cache."""

    def __init__(self):
        self._store = {}
        self.hits = 0
        self.misses = 0
        self.saved_input_tokens = 0
        self.saved_output_tokens = 0
        self.saved_cost = 0.0
        self.model_cost = 0.0

    def _key(self, system_prompt: str, user_message: str) -> str:
        """
        Create a unique hash from the exact full input.

        Same system prompt + same user message = same key.
        Any small change = different key.
        """
        raw = f"{system_prompt}||{user_message}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, system_prompt: str, user_message: str):
        key = self._key(system_prompt, user_message)

        if key in self._store:
            self.hits += 1

            cached = self._store[key]

            # These are tokens/cost we avoided by not calling the API.
            self.saved_input_tokens += cached["input_tokens"]
            self.saved_output_tokens += cached["output_tokens"]
            self.saved_cost += cached["cost"]

            return cached

        self.misses += 1
        return None

    def set(
        self,
        system_prompt: str,
        user_message: str,
        response_text: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ):
        key = self._key(system_prompt, user_message)

        self._store[key] = {
            "text": response_text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
        }