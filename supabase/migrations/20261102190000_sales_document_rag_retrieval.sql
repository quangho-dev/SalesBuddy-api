ALTER TABLE sales_documents
    ADD COLUMN source_type TEXT NOT NULL DEFAULT 'file',
    ADD COLUMN processing_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN processing_details JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE sales_document_chunks
    ADD COLUMN original_content JSONB NOT NULL DEFAULT '{"text":"","images":[],"tables":[]}'::jsonb,
    ADD COLUMN page_number INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN element_types JSONB NOT NULL DEFAULT '["text"]'::jsonb,
    ADD COLUMN char_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX sales_document_chunks_content_fts_idx
    ON sales_document_chunks
    USING gin (to_tsvector('simple', content));

CREATE TABLE sales_rag_settings (
    clerk_id TEXT PRIMARY KEY REFERENCES users(clerk_id) ON DELETE CASCADE,
    rag_strategy TEXT NOT NULL DEFAULT 'hybrid'
        CHECK (rag_strategy IN ('basic', 'hybrid', 'multi-query-vector', 'multi-query-hybrid')),
    final_context_size INTEGER NOT NULL DEFAULT 8 CHECK (final_context_size > 0),
    similarity_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.25,
    chunks_per_search INTEGER NOT NULL DEFAULT 8 CHECK (chunks_per_search > 0),
    vector_weight DOUBLE PRECISION NOT NULL DEFAULT 0.7,
    keyword_weight DOUBLE PRECISION NOT NULL DEFAULT 0.3,
    number_of_queries INTEGER NOT NULL DEFAULT 3 CHECK (number_of_queries > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.sales_rag_settings TO service_role;

DROP FUNCTION IF EXISTS match_sales_document_chunks(vector(1536), text, integer);

CREATE OR REPLACE FUNCTION vector_search_document_chunks(
    query_embedding vector(1536),
    filter_document_ids uuid[],
    match_threshold double precision,
    chunks_per_search integer
)
RETURNS TABLE (
    id uuid,
    document_id uuid,
    original_content jsonb,
    page_number integer,
    similarity double precision
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        chunk.id,
        chunk.document_id,
        chunk.original_content,
        chunk.page_number,
        1 - (chunk.embedding <=> query_embedding) AS similarity
    FROM sales_document_chunks AS chunk
    WHERE cardinality(filter_document_ids) > 0
      AND chunk.document_id = ANY(filter_document_ids)
      AND 1 - (chunk.embedding <=> query_embedding) >= match_threshold
    ORDER BY chunk.embedding <=> query_embedding
    LIMIT GREATEST(chunks_per_search, 0);
$$;

CREATE OR REPLACE FUNCTION keyword_search_document_chunks(
    query_text text,
    filter_document_ids uuid[],
    chunks_per_search integer
)
RETURNS TABLE (
    id uuid,
    document_id uuid,
    original_content jsonb,
    page_number integer
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        chunk.id,
        chunk.document_id,
        chunk.original_content,
        chunk.page_number
    FROM sales_document_chunks AS chunk
    WHERE cardinality(filter_document_ids) > 0
      AND chunk.document_id = ANY(filter_document_ids)
      AND to_tsvector('simple', chunk.content) @@ plainto_tsquery('simple', query_text)
    ORDER BY ts_rank(
        to_tsvector('simple', chunk.content),
        plainto_tsquery('simple', query_text)
    ) DESC
    LIMIT GREATEST(chunks_per_search, 0);
$$;

REVOKE ALL ON FUNCTION vector_search_document_chunks(vector(1536), uuid[], double precision, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION keyword_search_document_chunks(text, uuid[], integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION vector_search_document_chunks(vector(1536), uuid[], double precision, integer) TO service_role;
GRANT EXECUTE ON FUNCTION keyword_search_document_chunks(text, uuid[], integer) TO service_role;
