"""Monkey-patch tushare SDK to use the official stable domain.

The PyPI SDK (v1.4.29) hard-codes ``api.waditu.com`` — a legacy domain whose
Clash fake-IP routing is unreliable (~20 % success).  The official domain
``api.tushare.pro`` resolves to the same backend IPs but routes stably
through Clash TUN (100 % success, verified 2026-06-12).

Importing this module **or** calling :func:`patch_tushare_sdk_url` once is
sufficient — the class-level attribute change persists for the process
lifetime.

Refs: docs/push2-root-cause-analysis-2026-06-11.md §八
"""

from __future__ import annotations

_OFFICIAL_URL = "http://api.tushare.pro/dataapi"
_patched = False


def patch_tushare_sdk_url() -> None:
    """Patch ``DataApi.__http_url`` to the official stable domain.

    Idempotent — safe to call multiple times.
    """
    global _patched
    if _patched:
        return
    try:
        from tushare.pro.client import DataApi

        DataApi._DataApi__http_url = _OFFICIAL_URL  # type: ignore[attr-defined]
        _patched = True
    except ImportError:
        pass  # tushare not installed — nothing to patch


# Auto-patch on import so a bare ``import src.tushare_patch`` is enough.
patch_tushare_sdk_url()
