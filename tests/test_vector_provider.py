# SPDX-License-Identifier: CPAL-1.0

import asyncio
import socket
import urllib.request

from remember_me.search.vectors import NullVectorProvider, VectorProvider


def test_vector_provider_protocol_shape():
    assert "enabled" in VectorProvider.__dict__
    assert "model_id" in VectorProvider.__dict__
    assert "embed" in VectorProvider.__dict__


def test_null_vector_provider_is_network_free_keyword_fallback(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("NullVectorProvider attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)
    provider = NullVectorProvider()
    assert provider.enabled is False
    assert provider.model_id == "remember-me/null-vector-provider-v1"
    assert asyncio.run(provider.embed("keyword search remains available")) == []
