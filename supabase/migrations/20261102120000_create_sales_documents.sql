CREATE TABLE sales_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    storage_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
    error TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX sales_documents_clerk_created_idx
    ON sales_documents (clerk_id, created_at DESC);

CREATE TABLE sales_document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES sales_documents(id) ON DELETE CASCADE,
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX sales_document_chunks_document_idx
    ON sales_document_chunks (document_id, chunk_index);

CREATE INDEX sales_document_chunks_embedding_idx
    ON sales_document_chunks
    USING hnsw (embedding vector_cosine_ops);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.sales_documents TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.sales_document_chunks TO service_role;

CREATE OR REPLACE FUNCTION match_sales_document_chunks(
    query_embedding vector(1536),
    match_clerk_id text,
    match_count integer DEFAULT 8
)
RETURNS TABLE (
    id uuid,
    document_id uuid,
    filename text,
    chunk_index integer,
    content text,
    similarity double precision
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        chunk.id,
        chunk.document_id,
        document.filename,
        chunk.chunk_index,
        chunk.content,
        1 - (chunk.embedding <=> query_embedding) AS similarity
    FROM sales_document_chunks AS chunk
    JOIN sales_documents AS document ON document.id = chunk.document_id
    WHERE chunk.clerk_id = match_clerk_id
      AND document.status = 'ready'
    ORDER BY chunk.embedding <=> query_embedding
    LIMIT GREATEST(match_count, 0);
$$;

REVOKE ALL ON FUNCTION match_sales_document_chunks(vector(1536), text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION match_sales_document_chunks(vector(1536), text, integer) TO service_role;
