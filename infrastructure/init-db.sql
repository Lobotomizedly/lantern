-- =============================================================================
-- Lantern Database Initialization Script
-- PostgreSQL with pgvector extension
-- =============================================================================

-- Enable required extensions
-- -----------------------------------------------------------------------------

-- pgvector: Vector similarity search for embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- uuid-ossp: UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- pg_trgm: Trigram matching for fuzzy text search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- btree_gin: GIN index support for common data types
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- hstore: Key-value store within a single PostgreSQL value
CREATE EXTENSION IF NOT EXISTS hstore;

-- Verify extensions are installed
DO $$
BEGIN
    RAISE NOTICE 'Installed extensions:';
    RAISE NOTICE '  - vector (pgvector)';
    RAISE NOTICE '  - uuid-ossp';
    RAISE NOTICE '  - pg_trgm';
    RAISE NOTICE '  - btree_gin';
    RAISE NOTICE '  - hstore';
END $$;

-- Create schemas for better organization
-- -----------------------------------------------------------------------------

-- Core application schema
CREATE SCHEMA IF NOT EXISTS lantern;

-- Analytics and reporting schema
CREATE SCHEMA IF NOT EXISTS analytics;

-- Staging schema for data imports
CREATE SCHEMA IF NOT EXISTS staging;

-- Set search path
ALTER DATABASE lantern SET search_path TO lantern, public;

-- Grant privileges
GRANT ALL ON SCHEMA lantern TO lantern;
GRANT ALL ON SCHEMA analytics TO lantern;
GRANT ALL ON SCHEMA staging TO lantern;

-- Create enum types
-- -----------------------------------------------------------------------------

-- Document status
CREATE TYPE lantern.document_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed',
    'archived'
);

-- Entity types for narrative analysis
CREATE TYPE lantern.entity_type AS ENUM (
    'person',
    'organization',
    'location',
    'event',
    'concept',
    'product',
    'other'
);

-- Narrative element types
CREATE TYPE lantern.narrative_type AS ENUM (
    'claim',
    'fact',
    'opinion',
    'quote',
    'statistic',
    'event',
    'relationship'
);

-- User roles
CREATE TYPE lantern.user_role AS ENUM (
    'admin',
    'analyst',
    'viewer',
    'api_user'
);

-- Create core tables
-- -----------------------------------------------------------------------------

-- Users table
CREATE TABLE IF NOT EXISTS lantern.users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role lantern.user_role DEFAULT 'viewer',
    is_active BOOLEAN DEFAULT true,
    is_verified BOOLEAN DEFAULT false,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create index on email for faster lookups
CREATE INDEX IF NOT EXISTS idx_users_email ON lantern.users(email);

-- Projects table
CREATE TABLE IF NOT EXISTS lantern.projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    owner_id UUID REFERENCES lantern.users(id) ON DELETE SET NULL,
    settings JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    is_archived BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_projects_owner ON lantern.projects(owner_id);
CREATE INDEX IF NOT EXISTS idx_projects_name ON lantern.projects(name);

-- Documents table
CREATE TABLE IF NOT EXISTS lantern.documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES lantern.projects(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    source_url TEXT,
    source_type VARCHAR(50),
    content TEXT,
    content_hash VARCHAR(64),
    file_path TEXT,
    file_size BIGINT,
    mime_type VARCHAR(100),
    language VARCHAR(10) DEFAULT 'en',
    status lantern.document_status DEFAULT 'pending',
    metadata JSONB DEFAULT '{}',
    processing_metadata JSONB DEFAULT '{}',
    -- Vector embedding for semantic search (1536 dimensions for OpenAI embeddings)
    embedding vector(1536),
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for documents
CREATE INDEX IF NOT EXISTS idx_documents_project ON lantern.documents(project_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON lantern.documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_source_type ON lantern.documents(source_type);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON lantern.documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_published_at ON lantern.documents(published_at);

-- Vector similarity search index (using HNSW for better performance)
CREATE INDEX IF NOT EXISTS idx_documents_embedding ON lantern.documents
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_documents_content_fts ON lantern.documents
    USING gin(to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(content, '')));

-- Entities table (people, organizations, etc.)
CREATE TABLE IF NOT EXISTS lantern.entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES lantern.projects(id) ON DELETE CASCADE,
    name VARCHAR(500) NOT NULL,
    canonical_name VARCHAR(500),
    entity_type lantern.entity_type NOT NULL,
    description TEXT,
    aliases TEXT[],
    metadata JSONB DEFAULT '{}',
    -- Vector embedding for entity matching
    embedding vector(1536),
    mention_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, canonical_name, entity_type)
);

CREATE INDEX IF NOT EXISTS idx_entities_project ON lantern.entities(project_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON lantern.entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON lantern.entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_aliases ON lantern.entities USING gin(aliases);
CREATE INDEX IF NOT EXISTS idx_entities_embedding ON lantern.entities
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- Document-Entity mentions (junction table)
CREATE TABLE IF NOT EXISTS lantern.entity_mentions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID REFERENCES lantern.documents(id) ON DELETE CASCADE,
    entity_id UUID REFERENCES lantern.entities(id) ON DELETE CASCADE,
    mention_text TEXT NOT NULL,
    start_offset INTEGER,
    end_offset INTEGER,
    confidence FLOAT DEFAULT 1.0,
    context TEXT,
    sentiment FLOAT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mentions_document ON lantern.entity_mentions(document_id);
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON lantern.entity_mentions(entity_id);

-- Narratives table
CREATE TABLE IF NOT EXISTS lantern.narratives (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES lantern.projects(id) ON DELETE CASCADE,
    document_id UUID REFERENCES lantern.documents(id) ON DELETE CASCADE,
    narrative_type lantern.narrative_type NOT NULL,
    content TEXT NOT NULL,
    source_text TEXT,
    confidence FLOAT DEFAULT 1.0,
    sentiment FLOAT,
    importance_score FLOAT,
    metadata JSONB DEFAULT '{}',
    -- Vector embedding for narrative similarity
    embedding vector(1536),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_narratives_project ON lantern.narratives(project_id);
CREATE INDEX IF NOT EXISTS idx_narratives_document ON lantern.narratives(document_id);
CREATE INDEX IF NOT EXISTS idx_narratives_type ON lantern.narratives(narrative_type);
CREATE INDEX IF NOT EXISTS idx_narratives_embedding ON lantern.narratives
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- Entity relationships
CREATE TABLE IF NOT EXISTS lantern.entity_relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_entity_id UUID REFERENCES lantern.entities(id) ON DELETE CASCADE,
    target_entity_id UUID REFERENCES lantern.entities(id) ON DELETE CASCADE,
    relationship_type VARCHAR(100) NOT NULL,
    strength FLOAT DEFAULT 1.0,
    evidence_count INTEGER DEFAULT 1,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_entity_id, target_entity_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_relationships_source ON lantern.entity_relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target ON lantern.entity_relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON lantern.entity_relationships(relationship_type);

-- API keys for external access
CREATE TABLE IF NOT EXISTS lantern.api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES lantern.users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    key_hash VARCHAR(64) UNIQUE NOT NULL,
    key_prefix VARCHAR(8) NOT NULL,
    scopes TEXT[] DEFAULT ARRAY['read'],
    is_active BOOLEAN DEFAULT true,
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user ON lantern.api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON lantern.api_keys(key_hash);

-- Create helper functions
-- -----------------------------------------------------------------------------

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION lantern.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at trigger to relevant tables
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON lantern.users
    FOR EACH ROW EXECUTE FUNCTION lantern.update_updated_at_column();

CREATE TRIGGER update_projects_updated_at
    BEFORE UPDATE ON lantern.projects
    FOR EACH ROW EXECUTE FUNCTION lantern.update_updated_at_column();

CREATE TRIGGER update_documents_updated_at
    BEFORE UPDATE ON lantern.documents
    FOR EACH ROW EXECUTE FUNCTION lantern.update_updated_at_column();

CREATE TRIGGER update_entities_updated_at
    BEFORE UPDATE ON lantern.entities
    FOR EACH ROW EXECUTE FUNCTION lantern.update_updated_at_column();

CREATE TRIGGER update_relationships_updated_at
    BEFORE UPDATE ON lantern.entity_relationships
    FOR EACH ROW EXECUTE FUNCTION lantern.update_updated_at_column();

-- Function to search documents by vector similarity
CREATE OR REPLACE FUNCTION lantern.search_documents_by_embedding(
    query_embedding vector(1536),
    match_threshold FLOAT DEFAULT 0.7,
    match_count INT DEFAULT 10,
    p_project_id UUID DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    title VARCHAR(500),
    content TEXT,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.title,
        d.content,
        1 - (d.embedding <=> query_embedding) AS similarity
    FROM lantern.documents d
    WHERE
        d.embedding IS NOT NULL
        AND (p_project_id IS NULL OR d.project_id = p_project_id)
        AND 1 - (d.embedding <=> query_embedding) > match_threshold
    ORDER BY d.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Log initialization completion
DO $$
BEGIN
    RAISE NOTICE 'Lantern database initialization completed successfully!';
    RAISE NOTICE 'Created schemas: lantern, analytics, staging';
    RAISE NOTICE 'Created tables: users, projects, documents, entities, entity_mentions, narratives, entity_relationships, api_keys';
    RAISE NOTICE 'Created indexes for vector similarity search using HNSW';
END $$;
