-- 002: Single-user migration
-- Removes RLS, Supabase Auth dependencies, adds tags + extraction + pgvector

-- ── 1. Drop all RLS policies ──────────────────────────────────────────

DROP POLICY IF EXISTS users_select ON users;
DROP POLICY IF EXISTS users_update ON users;
DROP POLICY IF EXISTS api_keys_select ON api_keys;
DROP POLICY IF EXISTS knowledge_bases_select ON knowledge_bases;
DROP POLICY IF EXISTS documents_select ON documents;
DROP POLICY IF EXISTS document_pages_select ON document_pages;
DROP POLICY IF EXISTS document_chunks_select ON document_chunks;

-- ── 2. Disable RLS on all tables ──────────────────────────────────────

ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys DISABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_bases DISABLE ROW LEVEL SECURITY;
ALTER TABLE documents DISABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks DISABLE ROW LEVEL SECURITY;
ALTER TABLE document_pages DISABLE ROW LEVEL SECURITY;

-- ── 3. Drop auth-dependent objects ─────────────────────────────────────

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
DROP FUNCTION IF EXISTS handle_new_user();

-- ── 4. Modify generate_slug (remove user_id dependency) ────────────────

DROP TRIGGER IF EXISTS set_knowledge_base_slug ON knowledge_bases;
DROP FUNCTION IF EXISTS generate_slug(TEXT, UUID);

CREATE OR REPLACE FUNCTION generate_slug(name TEXT)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    base_slug TEXT;
    candidate TEXT;
    counter INTEGER := 0;
BEGIN
    base_slug := lower(regexp_replace(trim(name), '[^a-zA-Z0-9]+', '-', 'g'));
    base_slug := trim(both '-' from base_slug);

    IF base_slug = '' THEN
        base_slug := 'untitled';
    END IF;

    candidate := base_slug;

    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM knowledge_bases WHERE slug = candidate
        ) THEN
            RETURN candidate;
        END IF;
        counter := counter + 1;
        candidate := base_slug || '-' || counter;
    END LOOP;
END;
$$;

-- Re-create the trigger with the new function signature
CREATE OR REPLACE FUNCTION set_knowledge_base_slug()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.slug IS NULL OR NEW.slug = '' THEN
        NEW.slug := generate_slug(NEW.name);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER set_knowledge_base_slug
    BEFORE INSERT ON knowledge_bases
    FOR EACH ROW
    EXECUTE FUNCTION set_knowledge_base_slug();

-- ── 5. Relax knowledge_bases uniqueness (global instead of per-user) ──

ALTER TABLE knowledge_bases DROP CONSTRAINT IF EXISTS knowledge_bases_user_id_slug_key;
ALTER TABLE knowledge_bases DROP CONSTRAINT IF EXISTS knowledge_bases_user_id_name_key;
-- Add global uniqueness if not already present
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'knowledge_bases_slug_key'
    ) THEN
        ALTER TABLE knowledge_bases ADD CONSTRAINT knowledge_bases_slug_key UNIQUE(slug);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'knowledge_bases_name_key'
    ) THEN
        ALTER TABLE knowledge_bases ADD CONSTRAINT knowledge_bases_name_key UNIQUE(name);
    END IF;
END;
$$;

-- ── 6. Tags system ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tags (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS document_tags (
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(document_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_document_tags_tag ON document_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_document_tags_doc ON document_tags(document_id);

-- ── 7. Knowledge extraction queue ──────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'extract_status') THEN
        CREATE TYPE extract_status AS ENUM ('pending', 'approved', 'rejected');
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS extraction_tasks (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status extract_status DEFAULT 'pending' NOT NULL,
    proposed_content TEXT,
    proposed_tags TEXT[],
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_extraction_status ON extraction_tasks(status);

-- ── 8. pgvector for RAG ────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'document_chunks' AND column_name = 'embedding'
    ) THEN
        ALTER TABLE document_chunks ADD COLUMN embedding vector(768);
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON document_chunks USING hnsw (embedding vector_cosine_ops);
