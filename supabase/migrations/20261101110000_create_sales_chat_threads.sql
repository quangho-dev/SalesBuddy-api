CREATE TABLE sales_chat_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX sales_chat_threads_clerk_updated_idx
    ON sales_chat_threads (clerk_id, updated_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.sales_chat_threads TO service_role;

ALTER TABLE sales_chat_messages
    ADD COLUMN thread_id UUID;

CREATE TEMP TABLE sales_chat_thread_backfill AS
SELECT
    gen_random_uuid() AS id,
    clerk_id,
    min(created_at) AS created_at,
    max(created_at) AS updated_at
FROM sales_chat_messages
GROUP BY clerk_id;

INSERT INTO sales_chat_threads (id, clerk_id, title, created_at, updated_at)
SELECT id, clerk_id, 'Cuộc trò chuyện', created_at, updated_at
FROM sales_chat_thread_backfill;

UPDATE sales_chat_messages AS message
SET thread_id = backfill.id
FROM sales_chat_thread_backfill AS backfill
WHERE message.clerk_id = backfill.clerk_id;

UPDATE sales_chat_threads AS thread
SET title = left(btrim(regexp_replace(first_message.content, '\s+', ' ', 'g')), 72)
FROM sales_chat_messages AS first_message
WHERE first_message.thread_id = thread.id
  AND first_message.role = 'user'
  AND btrim(first_message.content) <> ''
  AND first_message.created_at = (
      SELECT min(created_at)
      FROM sales_chat_messages
      WHERE thread_id = thread.id
        AND role = 'user'
  );

ALTER TABLE sales_chat_messages
    ALTER COLUMN thread_id SET NOT NULL;

ALTER TABLE sales_chat_messages
    ADD CONSTRAINT sales_chat_messages_thread_id_fkey
    FOREIGN KEY (thread_id) REFERENCES sales_chat_threads(id) ON DELETE CASCADE;

CREATE INDEX sales_chat_messages_thread_created_idx
    ON sales_chat_messages (thread_id, created_at);
