import os
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_tavily import TavilySearch
from langchain_community.tools import DuckDuckGoSearchRun
from langchain.agents import create_agent
from pydantic import BaseModel, Field
from src.services.targetCustomers import list_known_target_customers

class TargetCustomerInfo(BaseModel):
    """Thông tin khách hàng mục tiêu ."""
    name: str = Field(description="Tên của khách hàng mục tiêu")
    phone_number: str = Field(description="Số điện thoại của khách hàng mục tiêu")
    reason_to_choose: str = Field(description="Lý do chọn khách hàng mục tiêu cho công ty của bạn")
    address: str = Field(description="Địa chỉ của khách hàng mục tiêu")
    website: str = Field(description="Website của khách hàng mục tiêu")
    facebook: str = Field(description="Facebook của khách hàng mục tiêu")
    summary_about_the_target_customer: str = Field(description="Tóm tắt về khách hàng mục tiêu")
    customer_url: str = Field(description="URL của khách hàng mục tiêu, để truy cập vào trang web của khách hàng mục tiêu")

class FinalTargetCustomerInfoResponse(BaseModel):
    """Response cuối cùng cho thông tin khách hàng mục tiêu."""
    list_name: str = Field(description="Tên ngắn gọn cho danh sách khách hàng mục tiêu lần tìm kiếm này")
    list_description: str = Field(description="Mô tả danh sách khách hàng mục tiêu lần tìm kiếm này")
    final_target_customer_info: list[TargetCustomerInfo] = Field(description="Danh sách thông tin khách hàng mục tiêu")


def _known_customers_prompt_block(clerk_id: str) -> str:
    try:
        known = list_known_target_customers(clerk_id)
    except Exception:
        return ""

    lines = []
    for row in known:
        name = (row.get("name") or "").strip()
        website = (row.get("website") or "").strip()
        facebook = (row.get("facebook") or "").strip()
        parts = []
        if name:
            parts.append(name)
        if website:
            parts.append(f"website: {website}")
        if facebook:
            parts.append(f"facebook: {facebook}")
        if parts:
            lines.append("- " + " | ".join(parts))

    if not lines:
        return ""

    return (
        "\nCác khách hàng mục tiêu sau đã có trong các danh sách của người dùng hiện tại. "
        "Không tìm lại, không trùng tên/website/facebook, và không trả về các khách hàng này:\n"
        + "\n".join(lines)
        + "\nChỉ trả về khách hàng mục tiêu mới, chưa có trong các danh sách trên.\n"
    )


def create_web_search_agent(
    model: str = "gpt-4o",
    use_tavily: bool = True,
    known_customers_block: str = "",
):
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
        search_tool = TavilySearch(max_results=10, search_depth="advanced")
    else:
        # Use DuckDuckGo as free alternative
        search_tool = DuckDuckGoSearchRun()
    
    tools = [search_tool]

    system_prompt = f"""Bạn là một trợ lý tìm kiếm khách hàng mục tiêu trên internet.
    Bạn cần tìm kiếm khách hàng mục tiêu trên internet và trả về thông tin khách hàng mục tiêu.
    Kết quả sẽ được lưu vào một danh sách mới của người dùng hiện tại.
    {known_customers_block}
   """
    
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        response_format=FinalTargetCustomerInfoResponse
    ).with_config({
        "run_name": "search_target_customers_web_agent",
        "tags": ["search-target-customers", "web-search"],
    })
    
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

def create_supervisor_tools(model: str = "gpt-4o", known_customers_block: str = ""):
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
    web_agent = create_web_search_agent(model, known_customers_block=known_customers_block)

    @tool
    def search_web(query: str, config: RunnableConfig) -> str:
        """Tìm kiếm khách hàng mục tiêu trên internet.
        
        Args:
            query: Từ khóa tìm kiếm
        
        Returns:
            Thông tin khách hàng mục tiêu
        """
        result = web_agent.invoke(
            {"messages": [{"role": "user", "content": query}]},
            config=config,
        )
        
        # Extract the final response
        final_message = result["messages"][-1]
        if hasattr(final_message, 'content'):
            return final_message.content
        return final_message
    
    return [search_web]

def create_supervisor_agent(
    clerk_id: str,
    model: str = "gpt-4o",
):
    """
    Create a supervisor agent that wraps the specialized agents.
    
    This function creates a supervisor agent that wraps the specialized agents.
    The supervisor will use these tools to delegate work to specialized agents.
    
    Args:
        clerk_id: Clerk ID of the signed-in user, used to skip already-saved customers
        model: The OpenAI model to use for both agents (default: "gpt-4o")
    """
    known_customers_block = _known_customers_prompt_block(clerk_id)
    supervisor_tools = create_supervisor_tools(
        model, known_customers_block=known_customers_block
    )

    system_prompt = f"""Bạn là một trợ lý tìm kiếm khách hàng mục tiêu trên internet.
    Bạn cần tìm kiếm khách hàng mục tiêu trên internet và trả về thông tin khách hàng mục tiêu.
    Đặt list_name và list_description cho danh sách kết quả lần tìm kiếm này.
    {known_customers_block}
    """

    base_supervisor = create_agent(
        model=model,
        tools=supervisor_tools,
        system_prompt=system_prompt,
        response_format=FinalTargetCustomerInfoResponse
    ).with_config({
        "recursion_limit": 10,
        "run_name": "search_target_customers_supervisor",
        "tags": ["search-target-customers"],
    })

    return base_supervisor