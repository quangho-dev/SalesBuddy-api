import logging

from src.services.llm import openAI
from fastapi import HTTPException
from src.services.settings import get_rag_settings
from src.services.supabase import supabase
from src.rag.retrieval.utils import (
    get_ready_document_ids,
    build_context_from_retrieved_chunks,
    generate_query_variations,
    rrf_rank_and_fuse,
)
from typing import List, Dict

logger = logging.getLogger(__name__)


def retrieve_context(
    clerk_id,
    user_query,
    limit: int | None = None,
    document_ids: list[str] | None = None,
):
    try:
        """
        RAG Retrieval Pipeline Steps:
        * Step 1: Get the signed-in user's RAG settings from the database.
        * Step 2: Retrieve the ready document IDs for that user.
        * Step 3: Perform a vector search using the RPC function to find the most relevant chunks.
        * Step 4: Perform a hybrid search (combines vector + keyword search) using RPC function.
        * Step 5: Perform multi-query vector search (generate multiple query variations and search)
        * Step 6: Perform multi-query hybrid search (multiple queries with hybrid strategy)
        * Step 7: Build the context from the retrieved chunks and format them into a structured context with citations.
        """
        # Step 1: Get the signed-in user's RAG settings from the database.
        rag_settings = get_rag_settings(clerk_id)
        strategy = rag_settings["rag_strategy"]
        logger.info(
            "rag_settings_retrieved strategy=%s final_context_size=%s",
            strategy,
            rag_settings["final_context_size"],
        )

        # Step 2: Retrieve the ready document IDs for that user.
        # A provided list is limited to documents that user owns and that are ready.
        ready_ids = get_ready_document_ids(clerk_id)
        if document_ids is not None:
            allowed = set(ready_ids)
            ready_ids = [doc_id for doc_id in document_ids if doc_id in allowed]
        document_ids = ready_ids
        logger.info("documents_found count=%s", len(document_ids))

        chunks = []
        if not document_ids:
            return [], [], [], []
        if strategy == "basic":
            # Basic RAG Strategy: Vector search only
            chunks = vector_search(user_query, document_ids, rag_settings)
            logger.info("vector_search_completed chunks=%s", len(chunks))
        elif strategy == "hybrid":
            # Hybrid RAG Strategy: Combines vector + keyword search with RRF ranking
            chunks = hybrid_search(user_query, document_ids, rag_settings)
            logger.info("hybrid_search_completed chunks=%s", len(chunks))
        elif strategy == "multi-query-vector":
            chunks = multi_query_vector_search(user_query, document_ids, rag_settings)
            logger.info("multi_query_vector_search_completed chunks=%s", len(chunks))
        elif strategy == "multi-query-hybrid":
            chunks = multi_query_hybrid_search(user_query, document_ids, rag_settings)
            logger.info("multi_query_hybrid_search_completed chunks=%s", len(chunks))
        else:
            raise ValueError(f"Unknown RAG strategy: {strategy}")

        # Step 8: Selecting top k chunks
        context_size = limit or rag_settings["final_context_size"]
        chunks = chunks[:context_size]
        logger.info("chunks_limited count=%s", len(chunks))

        texts, images, tables, citations = build_context_from_retrieved_chunks(chunks)
        logger.info(
            "retrieval_completed texts=%s images=%s tables=%s citations=%s",
            len(texts),
            len(images),
            len(tables),
            len(citations),
        )

        return texts, images, tables, citations
    except Exception as e:
        logger.error("retrieval_failed error=%s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed in RAG's Retrieval: {str(e)}")


def vector_search(user_query, document_ids, rag_settings):
    user_query_embedding = openAI["embeddings"].embed_documents([user_query])[0]
    vector_search_result_chunks = supabase.rpc(
        "vector_search_document_chunks",
        {
            "query_embedding": user_query_embedding,
            "filter_document_ids": document_ids,
            "match_threshold": rag_settings["similarity_threshold"],
            "chunks_per_search": rag_settings["chunks_per_search"],
        },
    ).execute()
    return vector_search_result_chunks.data if vector_search_result_chunks.data else []


def keyword_search(query, document_ids, settings):
    keyword_search_result_chunks = supabase.rpc(
        "keyword_search_document_chunks",
        {
            "query_text": query,
            "filter_document_ids": document_ids,
            "chunks_per_search": settings["chunks_per_search"],
        },
    ).execute()

    return (
        keyword_search_result_chunks.data if keyword_search_result_chunks.data else []
    )


def hybrid_search(query: str, document_ids: List[str], settings: dict) -> List[Dict]:
    """Execute hybrid search by combining vector and keyword results"""
    # Get results from both search methods
    vector_results = vector_search(query, document_ids, settings)
    keyword_results = keyword_search(query, document_ids, settings)
    logger.info(
        "hybrid_search_results vector=%s keyword=%s",
        len(vector_results),
        len(keyword_results),
    )
    return rrf_rank_and_fuse([vector_results, keyword_results], [settings["vector_weight"], settings["keyword_weight"]])


def multi_query_vector_search(user_query, document_ids, rag_settings):
    """Execute multi-query vector search using query variations"""
    queries = generate_query_variations(user_query, rag_settings["number_of_queries"])
    logger.info("query_variations_generated count=%s", len(queries))

    all_chunks = []
    for index, query in enumerate(queries):
        chunks = vector_search(query, document_ids, rag_settings)
        all_chunks.append(chunks)
        logger.info(
            "query_variation_search %s/%s query=%s chunks=%s",
            index + 1,
            len(queries),
            query,
            len(chunks),
        )

    final_chunks = rrf_rank_and_fuse(all_chunks)
    logger.info("rrf_fusion_completed count=%s", len(final_chunks))
    return final_chunks


def multi_query_hybrid_search(user_query, document_ids, rag_settings):
    """Execute multi-query hybrid search using query variations"""
    queries = generate_query_variations(user_query, rag_settings["number_of_queries"])
    logger.info("query_variations_generated_hybrid count=%s", len(queries))

    all_chunks = []
    for index, query in enumerate(queries):
        chunks = hybrid_search(query, document_ids, rag_settings)
        all_chunks.append(chunks)
        logger.info(
            "hybrid_query_variation_search %s/%s query=%s chunks=%s",
            index + 1,
            len(queries),
            query,
            len(chunks),
        )

    final_chunks = rrf_rank_and_fuse(all_chunks)
    logger.info("rrf_fusion_completed_hybrid count=%s", len(final_chunks))
    return final_chunks
