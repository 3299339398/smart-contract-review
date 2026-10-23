from app.agent.state import AgentState


async def parse_document_node(state: AgentState) -> AgentState:
    """文档规范化节点：作为最后一道安全网，统一换行符。

    主清洗已在上传时（clean_document_text）和安全管线（filter_text）中完成，
    这里只做换行符兜底，防止中间链路引入 \r 字符。"""
    text = state["document_text"]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    state["parsed_text"] = text
    state["should_continue"] = True
    return state
