ALTER TABLE orders
    ALTER COLUMN order_date TYPE TIMESTAMPTZ
    USING (
        CASE
            WHEN created_at IS NOT NULL
                AND order_date = (created_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
                THEN created_at
            ELSE (order_date::timestamp AT TIME ZONE 'Asia/Ho_Chi_Minh')
        END
    );

ALTER TABLE orders
    ALTER COLUMN order_date SET DEFAULT now();
