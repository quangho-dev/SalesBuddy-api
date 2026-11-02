CREATE TABLE sales_chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX sales_chat_messages_clerk_created_idx
    ON sales_chat_messages (clerk_id, created_at);

GRANT SELECT, INSERT, DELETE ON TABLE public.sales_chat_messages TO service_role;
