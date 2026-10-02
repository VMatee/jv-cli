"""Explicit execution authority; never infer full access from sandbox failure."""
import os

from .safety import JvError


class UnsupportedCapability(JvError):
    pass


NETWORK_UNSUPPORTED = (
    "Windows Codex 0.149.1 cannot guarantee network isolation in restricted-token mode. "
    "Use trusted-host only when unrestricted access is intentional."
)
TRUSTED_STATUS = (
    "Execution mode: trusted-host; sandbox: disabled/full access; "
    "network: allowed; approvals: never"
)


def resolve(mode=None, *, read_only=False, allow_network=None):
    if mode not in (None, 'trusted-host'):
        raise JvError('Unknown execution mode')
    if mode == 'trusted-host':
        if os.name != 'nt':
            raise UnsupportedCapability('trusted-host is supported only on Windows')
        if read_only or allow_network is False:
            raise UnsupportedCapability('trusted-host requires writes and network access; restrictive requests are rejected')
        return 'danger-full-access', True
    network = not read_only if allow_network is None else allow_network
    if os.name == 'nt' and not network:
        raise UnsupportedCapability(NETWORK_UNSUPPORTED)
    if read_only and network:
        raise JvError('--allow-network is available only in workspace-write mode')
    return 'read-only' if read_only else 'workspace-write', network
