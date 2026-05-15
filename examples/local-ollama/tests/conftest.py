"""Test-suite preamble for the local-ollama example.

Unlike the AJ-50 ``support-agent`` and the AJ-54 ``docsbot`` (both of
which set ``ANTHROPIC_API_KEY=test-dummy`` here), this example does NOT
need any API key: the universal provider's ``ollama`` prefix has
``api_key_env=None`` and the SDK is given the literal ``"ollama"``
placeholder at request time. Decoration-time validation only checks
that the provider class is registered — which the side-effect import in
``local_ollama.__init__`` already guarantees.

The file stays so pytest discovers the package consistently with the
other examples; nothing has to run here for the smoke test to pass.
"""
