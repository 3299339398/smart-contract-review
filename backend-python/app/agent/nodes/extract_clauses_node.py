from app.agent.state import AgentState, Clause
from app.parser.chunker import ClauseLevelChunker


async def extract_clauses_node(state: AgentState) -> AgentState:
    """条款拆分节点：委托 ClauseLevelChunker 做两级拆分（主策略 + 次级长条款拆分），
    产出 Clause TypedDict 列表写入 state["clauses"]。"""
    text = state["parsed_text"]

    chunker = ClauseLevelChunker()
    clause_texts = chunker.split_clauses(text)

    clause_objects = []
    for i, clause_text in enumerate(clause_texts):
        if len(clause_text.strip()) < 10:
            continue
        clause_objects.append(Clause(
            index=i + 1,
            text=clause_text.strip()
        ))

    state["clauses"] = clause_objects
    state["total_clauses"] = len(clause_objects)
    state["current_clause_index"] = -1

    return state
