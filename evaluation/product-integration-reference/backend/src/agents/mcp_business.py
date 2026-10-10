"""Role-scoped local MCP boundary around the existing business-tool worker."""
import asyncio

from fastmcp import Client, FastMCP


class LocalMCPBusinessBus:
    GROUPS={
        "catalog":{"catalog.search","pricing.get_quote","inventory.check"},
        "crm":{"crm.get_customer","order.create","order.status","order.update","schedule.callback","handoff.transfer"},
    }

    def __init__(self, invoke):
        self.servers={}
        self.group_by_tool={name:group for group,names in self.GROUPS.items() for name in names}
        for group,names in self.GROUPS.items():
            server=FastMCP("sudo-"+group)
            def register(bound_server,allowed):
                @bound_server.tool(name="execute")
                def execute(name:str,args:dict):
                    if name not in allowed:
                        raise ValueError("Tool is unavailable to this MCP server")
                    return invoke(name,args)
            register(server,names)
            self.servers[group]=server

    def call_tool(self,name,args):
        group=self.group_by_tool.get(name)
        if group is None:
            raise ValueError("Unknown business MCP tool")
        async def call():
            async with Client(self.servers[group]) as client:
                result=await client.call_tool("execute",{"name":name,"args":args})
                value=result.data if result.data is not None else result.structured_content
                if isinstance(value,dict) and set(value)=={"result"}:
                    value=value["result"]
                if not isinstance(value,dict):
                    raise ValueError("MCP business result must be an object")
                return value
        return asyncio.run(call())
