"""Chat router — SSE streaming with Agent/GraphRAG."""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core import rate_limit
from src.core.config import get_settings
from src.core.security import get_current_user
from src.core.audit import log_action
from src.database.models import Conversation, Message
from src.database.session import get_db

import structlog

logger = structlog.get_logger()
settings = get_settings()

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None
    mode: str | None = None  # 'consult' | 'design' | 'analyze'


@router.post("/chat")
def chat(
    req: ChatRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Chat with AI using GraphRAG — returns SSE stream."""
    user_id = int(current_user["sub"])

    # Each question costs 3-4 Gemini calls: cap per user before touching the DB or the LLM
    rate_limit.hit(f"chat:min:{user_id}", settings.chat_rate_limit_per_minute, 60)
    rate_limit.hit(f"chat:day:{user_id}", settings.chat_rate_limit_per_day, 24 * 3600)

    # Get or create conversation
    if req.conversation_id:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == req.conversation_id, Conversation.user_id == user_id)
            .first()
        )
        if not conversation:
            raise HTTPException(404, "Cuộc hội thoại không tồn tại")
    else:
        # Auto-generate title from first message
        title = req.message.strip()[:60]
        if len(req.message.strip()) > 60:
            title = title.rsplit(" ", 1)[0] + "..."
        conversation = Conversation(user_id=user_id, title=title)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    # Save user message
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=req.message,
    )
    db.add(user_msg)
    db.commit()

    # Get conversation history
    history_msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(10)
        .all()
    )
    messages = [{"role": m.role, "content": m.content} for m in reversed(history_msgs)]

    # Query using agent, coordinator, or fallback
    use_langgraph = False
    try:
        if settings.agent_mode == "multi_agent":
            from src.agents.coordinator import ask
            use_langgraph = True  # Same 4-value return signature
            logger.info("using_multi_agent_coordinator")
        elif settings.agent_mode == "langgraph":
            from src.rag.agent import ask
            use_langgraph = True
        else:
            from src.rag.graph_rag import ask
    except ImportError:
        from src.rag.graph_rag import ask
        logger.warning("agent_import_failed_using_fallback")

    # Build kwargs — graph_rag.ask doesn't accept 'mode'
    ask_kwargs = dict(question=req.message, messages=messages, stream=True)
    if use_langgraph:
        ask_kwargs["mode"] = req.mode

    result = ask(**ask_kwargs)

    # agent.ask returns 4 values, graph_rag.ask returns 3
    if len(result) == 4:
        response_stream, documents, entities, tool_results = result
    else:
        response_stream, documents, entities = result
        tool_results = {}

    # Format citations
    citations = []
    for doc in documents[:5]:
        meta = doc.get("metadata", {})
        citations.append({
            "standard_code": meta.get("standard_code", ""),
            "article_number": meta.get("article_number", ""),
            "text_preview": doc["text"][:200],
            "source": meta.get("source", "vector"),
        })

    # Extract design result for frontend
    design_result = None
    if "design" in tool_results:
        dr = tool_results["design"]
        spec_data = dr.get("spec", {})
        # Inject structure_type into spec for frontend detection
        spec_data["structure_type"] = dr.get("structure_type", "building")
        design_result = {
            "filename": dr.get("filename", ""),
            "spec": spec_data,
            "violations": dr.get("violations", []),
            "structure_type": dr.get("structure_type", "building"),
        }

    def event_generator():
        full_response = ""

        # Send metadata first
        meta_data = {
            'type': 'meta',
            'conversation_id': conversation.id,
            'entities': entities,
            'citations': citations,
        }
        if design_result:
            meta_data['design'] = design_result
        yield f"data: {json.dumps(meta_data, ensure_ascii=False)}\n\n"

        # Stream response chunks
        try:
            for chunk in response_stream:
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("stream_error", error=str(e), exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Đã xảy ra lỗi khi tạo phản hồi. Vui lòng thử lại.'}, ensure_ascii=False)}\n\n"
            return

        # Save assistant message — include design metadata for history restore
        try:
            save_citations = citations.copy()
            if design_result:
                save_citations.append({
                    "_type": "design_result",
                    "filename": design_result.get("filename", ""),
                    "spec": design_result.get("spec", {}),
                    "violations": design_result.get("violations", []),
                })
            assistant_msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=full_response,
                citations=json.dumps(save_citations, ensure_ascii=False),
            )
            db.add(assistant_msg)
            db.commit()
            db.refresh(assistant_msg)
            # Audit log
            log_action("chat", user_id=user_id, detail={
                "conversation_id": conversation.id,
                "mode": req.mode or "consult",
                "question_preview": req.message[:100],
                "response_length": len(full_response),
            })
        except Exception as e:
            logger.error("db_save_failed", error=str(e), exc_info=True)
            db.rollback()

        # Self-reflection: evaluate response quality
        reflection = None
        try:
            from src.rag.reflection import evaluate_response, format_confidence_label
            reflection = evaluate_response(
                question=req.message,
                response=full_response,
                documents=documents,
                intent=getattr(req, 'mode', '') or 'consult',
            )
        except Exception as e:
            logger.warning("reflection_failed", error=str(e))

        done_data = {'type': 'done'}
        if assistant_msg and assistant_msg.id:
            done_data['message_id'] = assistant_msg.id
        if reflection:
            done_data['confidence'] = reflection['confidence']
            done_data['confidence_label'] = format_confidence_label(reflection['confidence'])
            done_data['reflection_feedback'] = reflection['feedback']
        yield f"data: {json.dumps(done_data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations")
def list_conversations(
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List user's conversations with pagination."""
    user_id = int(current_user["sub"])
    convos = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(min(limit, 100))  # Cap at 100
        .all()
    )
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
        }
        for c in convos
    ]


@router.get("/conversations/{conversation_id}/messages")
def get_messages(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get messages in a conversation."""
    user_id = int(current_user["sub"])
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .first()
    )
    if not conversation:
        raise HTTPException(404, "Cuộc hội thoại không tồn tại")

    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "citations": json.loads(m.citations) if m.citations else [],
            "feedback": m.feedback,
            "created_at": m.created_at.isoformat(),
        }
        for m in conversation.messages
    ]


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a conversation and all its messages."""
    user_id = int(current_user["sub"])
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .first()
    )
    if not conversation:
        raise HTTPException(404, "Cuộc hội thoại không tồn tại")

    # Delete messages first
    db.query(Message).filter(Message.conversation_id == conversation_id).delete()
    db.delete(conversation)
    db.commit()

    return {"message": "Đã xóa cuộc hội thoại"}


class FeedbackRequest(BaseModel):
    feedback: str  # "like" | "dislike"


@router.put("/messages/{message_id}/feedback")
def set_message_feedback(
    message_id: int,
    req: FeedbackRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set thumbs up/down feedback on an assistant message."""
    if req.feedback not in ("like", "dislike"):
        raise HTTPException(400, "Feedback phải là 'like' hoặc 'dislike'")

    user_id = int(current_user["sub"])

    # Verify message belongs to user's conversation
    msg = (
        db.query(Message)
        .join(Conversation)
        .filter(
            Message.id == message_id,
            Message.role == "assistant",
            Conversation.user_id == user_id,
        )
        .first()
    )
    if not msg:
        raise HTTPException(404, "Tin nhắn không tồn tại")

    # Toggle: if same feedback already set, clear it
    if msg.feedback == req.feedback:
        msg.feedback = None
    else:
        msg.feedback = req.feedback
    db.commit()

    log_action("feedback", user_id=user_id, detail={
        "message_id": message_id,
        "feedback": msg.feedback,
    })

    return {"message_id": message_id, "feedback": msg.feedback}
