"""Root ``@Module`` for the web-research example.

Wires the ``Researcher`` ``@Agent`` into the DI container. Importing the
agents module also registers its ``@Stream("/chat")`` route with the
HTTP layer at decoration time.
"""

from ajolopy import Module
from web_research.agents.researcher import Researcher


@Module(agents=[Researcher])
class AppModule:
    """The example's root module — one agent, one ``@Stream("/chat")``."""


__all__ = ["AppModule"]
