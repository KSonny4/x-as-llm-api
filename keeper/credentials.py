"""Runtime-only credential lookup. Never serialize this object or seed routes.

credential_ref includes the secret-store generation (Bao KV metadata.version).
A new generation has independent availability proof; old rows remain disabled
for history. Route aliases for one generation resolve to one credential.
"""


class RuntimeCredentials:
    def __init__(self, routes):
        self._values = {}
        for r in routes:
            ref = r.get('credential_ref') or r.get('env_var')
            if not ref:
                continue
            key = (r['provider'], ref)
            value = r.get('api_key') or None
            if key in self._values and self._values[key] != value:
                raise ValueError('conflicting credential generation')
            self._values[key] = value

    def resolve(self, provider, reference):
        return self._values.get((provider, reference))
