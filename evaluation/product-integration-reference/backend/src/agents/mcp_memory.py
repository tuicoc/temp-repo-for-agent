"""Customer-bound MCP read surface; models cannot select another profile."""
import asyncio
import json

from fastmcp import Client, FastMCP


class LocalMCPMemoryReader:
    def __init__(self, store, customer):
        self.server=FastMCP("sudo-memory-reader")
        @self.server.tool(name="get_profile")
        def get_profile():
            return store.facts(customer)
        @self.server.tool(name="get_episodes")
        def get_episodes(limit:int=3):
            if not 1<=limit<=10:
                raise ValueError("Episode limit must be bounded")
            return store.sessions(customer)[-limit:]

    def _call(self,name,args=None):
        async def call():
            async with Client(self.server) as client:
                result=await client.call_tool(name,args or {})
                value=result.data if result.data is not None else result.structured_content
                if isinstance(value,dict) and set(value)=={"result"}:
                    value=value["result"]
                if value is None and not result.content:
                    value=[]
                elif value is None and len(result.content)==1 and getattr(result.content[0],"type",None)=="text":
                    value=json.loads(result.content[0].text)
                if not isinstance(value,list):
                    raise ValueError("MCP memory result must be a list")
                return value
        return asyncio.run(call())

    def facts(self):
        return self._call("get_profile")

    def sessions(self,limit=3):
        return self._call("get_episodes",{"limit":limit})
