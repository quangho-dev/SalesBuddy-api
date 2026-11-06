CREATE TABLE IF NOT EXISTS delivery_settings (
    clerk_id TEXT PRIMARY KEY REFERENCES users(clerk_id) ON DELETE CASCADE,
    pickup_name TEXT NOT NULL DEFAULT '',
    pickup_phone TEXT NOT NULL DEFAULT '',
    pickup_address TEXT NOT NULL DEFAULT '',
    pickup_lat NUMERIC,
    pickup_lng NUMERIC,
    market TEXT NOT NULL DEFAULT 'VN',
    default_service_type TEXT NOT NULL DEFAULT 'MOTORCYCLE',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT 'lalamove',
    status TEXT NOT NULL DEFAULT 'draft',
    service_type TEXT NOT NULL DEFAULT '',
    schedule_at TIMESTAMPTZ,
    quotation_id TEXT NOT NULL DEFAULT '',
    quotation_expires_at TIMESTAMPTZ,
    provider_order_id TEXT NOT NULL DEFAULT '',
    share_link TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'VND',
    quoted_fee NUMERIC NOT NULL DEFAULT 0,
    driver_name TEXT NOT NULL DEFAULT '',
    driver_phone TEXT NOT NULL DEFAULT '',
    driver_plate TEXT NOT NULL DEFAULT '',
    failure_reason TEXT NOT NULL DEFAULT '',
    quoted_at TIMESTAMPTZ,
    placed_at TIMESTAMPTZ,
    picked_up_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT deliveries_status_check CHECK (
        status IN (
            'draft',
            'quoted',
            'assigning_driver',
            'ongoing',
            'picked_up',
            'completed',
            'canceled',
            'rejected',
            'expired',
            'failed'
        )
    )
);

CREATE INDEX IF NOT EXISTS deliveries_clerk_id_idx
    ON deliveries (clerk_id, created_at DESC);
CREATE INDEX IF NOT EXISTS deliveries_order_id_idx ON deliveries (order_id);
CREATE UNIQUE INDEX IF NOT EXISTS deliveries_provider_order_idx
    ON deliveries (provider, provider_order_id)
    WHERE provider_order_id <> '';
CREATE UNIQUE INDEX IF NOT EXISTS deliveries_one_open_order_idx
    ON deliveries (order_id)
    WHERE order_id IS NOT NULL
      AND status IN ('draft', 'quoted', 'assigning_driver', 'ongoing', 'picked_up');

CREATE TABLE IF NOT EXISTS delivery_stops (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    delivery_id UUID NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    stop_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    contact_name TEXT NOT NULL DEFAULT '',
    contact_phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    lat NUMERIC,
    lng NUMERIC,
    remarks TEXT NOT NULL DEFAULT '',
    provider_stop_id TEXT NOT NULL DEFAULT '',
    CONSTRAINT delivery_stops_role_check CHECK (role IN ('pickup', 'dropoff')),
    CONSTRAINT delivery_stops_index_unique UNIQUE (delivery_id, stop_index)
);

CREATE TABLE IF NOT EXISTS delivery_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    delivery_id UUID NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
    previous_status TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    provider_status TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS delivery_events_delivery_idx
    ON delivery_events (delivery_id, created_at DESC);

CREATE TABLE IF NOT EXISTS delivery_webhook_receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL DEFAULT 'lalamove',
    event_id TEXT NOT NULL,
    delivery_id UUID REFERENCES deliveries(id) ON DELETE SET NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT delivery_webhook_receipts_event_unique UNIQUE (provider, event_id)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.delivery_settings TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.deliveries TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.delivery_stops TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.delivery_events TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.delivery_webhook_receipts TO service_role;
