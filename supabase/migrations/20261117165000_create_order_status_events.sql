CREATE TABLE IF NOT EXISTS order_status_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    previous_status TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT order_status_events_status_check
        CHECK (status IN ('official', 'cancelled', 'paused')),
    CONSTRAINT order_status_events_previous_status_check
        CHECK (previous_status IN ('', 'official', 'cancelled', 'paused'))
);

CREATE INDEX IF NOT EXISTS order_status_events_order_created_idx
    ON order_status_events (order_id, created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.order_status_events TO service_role;
