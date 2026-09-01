-- 001_initial_schema.sql
-- PostgreSQL migration for RAG application with vector search and full-text search

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Target customer list table
CREATE TABLE target_customer_list (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE
);

-- Target customers table
CREATE TABLE target_customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    summary_about_the_target_customer TEXT NOT NULL,
    website TEXT NOT NULL,
    address TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    facebook TEXT NOT NULL,
    reason_to_choose TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    target_customer_list_id UUID NOT NULL REFERENCES target_customer_list(id) ON DELETE CASCADE
);
