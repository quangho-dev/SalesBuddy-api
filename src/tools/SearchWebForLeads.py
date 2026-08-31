import os
from typing import Optional, List, Dict
from langchain.tools import tool
from langchain_tavily import TavilySearch
from langchain_community.tools import DuckDuckGoSearchRun
from langchain.agents import create_agent
from pydantic import BaseModel, Field

class TargetCustomerInfo(BaseModel):
    """Thông tin khách hàng mục tiêu ."""
    name: str = Field(description="Tên của khách hàng mục tiêu")
    phone_number: str = Field(description="Số điện thoại của khách hàng mục tiêu")
    reason_to_choose: str = Field(description="Lý do chọn khách hàng mục tiêu cho công ty của bạn")
    address: str = Field(description="Địa chỉ của khách hàng mục tiêu")
    website: str = Field(description="Website của khách hàng mục tiêu")
    facebook: str = Field(description="Facebook của khách hàng mục tiêu")

class FinalTargetCustomerInfoResponse(BaseModel):
    """Response cuối cùng cho thông tin khách hàng mục tiêu."""
    final_target_customer_info: list[TargetCustomerInfo] = Field(description="Danh sách thông tin khách hàng mục tiêu")

def create_web_search_agent(model: str = "gpt-4o", use_tavily: bool = True):
    """
    Tạo một agent có nhiệm vụ tìm kiếm khách hàng mục tiêu trên internet.
    
    Args:
        model: Mô hình OpenAI
        use_tavily: Sử dụng Tavily search (nếu có API key) hoặc DuckDuckGo (mặc định)
    
    Returns:
        Một agent có nhiệm vụ tìm kiếm khách hàng mục tiêu trên internet.
    """
    # Choose search tool based on availability
    if use_tavily and os.getenv("TAVILY_API_KEY"):
        search_tool = TavilySearch(max_results=5, search_depth="advanced")
    else:
        # Use DuckDuckGo as free alternative
        search_tool = DuckDuckGoSearchRun()
    
    tools = [search_tool]

    system_prompt = f"""Bạn là một trợ lý tìm kiếm khách hàng mục tiêu trên internet.
    Bạn cần tìm kiếm khách hàng mục tiêu trên internet và trả về thông tin khách hàng mục tiêu.
   """
    
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        response_format=FinalTargetCustomerInfoResponse
    )
    
    return agent

@tool
def search_web_for_target_customers(query: str) -> str:
     """Tìm kiếm khách hàng mục tiêu trên internet.
    
    Args:
        query: Từ khóa tìm kiếm
    
    Returns:
        Thông tin khách hàng mục tiêu
    """
     return "I found a target_customer!"

def create_supervisor_tools(model: str = "gpt-4o"):
    """
    Create supervisor tools that wrap the specialized agents.
    
    This function creates two tools for the supervisor:
    1. search_web: Wraps the web search agent for internet queries
    
    The supervisor will use these tools to delegate work to specialized agents.
    
    Args:
        model: The OpenAI model to use for both agents (default: "gpt-4o")
        
    Returns:
        List of tools (search_web) for the supervisor
    """
    # Create the specialized agents
    web_agent = create_web_search_agent(model)

    @tool
    def search_web(query: str) -> str:
        """Tìm kiếm khách hàng mục tiêu trên internet.
        
        Args:
            query: Từ khóa tìm kiếm
        
        Returns:
            Thông tin khách hàng mục tiêu
        """
        result = web_agent.invoke({
            "messages": [{"role": "user", "content": query}]
        })
        
        # Extract the final response
        final_message = result["messages"][-1]
        if hasattr(final_message, 'content'):
            return final_message.content
        return final_message
    
    return [search_web]

def create_supervisor_agent(
    model: str = "gpt-4o",
):
    """
    Create a supervisor agent that wraps the specialized agents.
    
    This function creates a supervisor agent that wraps the specialized agents.
    The supervisor will use these tools to delegate work to specialized agents.
    
    Args:
        model: The OpenAI model to use for both agents (default: "gpt-4o")
    """
    supervisor_tools = create_supervisor_tools(model)

    system_prompt = f"""Bạn là một trợ lý tìm kiếm khách hàng mục tiêu trên internet.
    Bạn cần tìm kiếm khách hàng mục tiêu trên internet và trả về thông tin khách hàng mục tiêu.
    """

    base_supervisor = create_agent(
        model=model,
        tools=supervisor_tools,
        system_prompt=system_prompt,
        response_format=FinalTargetCustomerInfoResponse
    ).with_config({"recursion_limit": 10})

    return base_supervisor