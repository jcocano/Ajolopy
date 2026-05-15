"""Historical home for ``ajolopy deploy`` stub targets.

When ``AJ-37`` shipped the deploy gateway it registered five stub
targets so ``--help`` would list every v0.1 platform from day one.
``AJ-42`` (Fly), ``AJ-43`` (Railway), ``AJ-44`` (Render), and
``AJ-45`` (Vercel) have all since landed their real adapters, so no
stubs remain.

The module is kept (empty) rather than deleted so older revisions of
:mod:`ajolopy.cli.deploy.__init__` that imported the stub classes can
still rebase cleanly. Future stubs (e.g. for an experimental target
that ships in v0.2) should re-introduce the ``_Stub`` base class
here.
"""

__all__: list[str] = []
