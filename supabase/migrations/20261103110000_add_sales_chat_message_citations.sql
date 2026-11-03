ALTER TABLE sales_chat_messages
    ADD COLUMN IF NOT EXISTS citations JSONB NOT NULL DEFAULT '[]'::jsonb;
