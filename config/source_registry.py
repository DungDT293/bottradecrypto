from typing import Dict, Optional
from config.policy_defaults import SourcePolicyOverride


class SourceRegistry:
    def __init__(self, sources: Optional[Dict[int, SourcePolicyOverride]] = None):
        self._sources: Dict[int, SourcePolicyOverride] = sources or {}

    def get_source_policy(self, chat_id: int) -> Optional[SourcePolicyOverride]:
        return self._sources.get(chat_id)

    def is_chat_allowed(self, chat_id: int, allowed_list: list[int]) -> bool:
        if not allowed_list:
            # If allowed_list is empty, no chat is allowed until explicitly set
            return False
        return chat_id in allowed_list

    def register_override(self, override: SourcePolicyOverride) -> None:
        self._sources[override.chat_id] = override

