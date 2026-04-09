-- Enable pgcrypto for UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create app role for RLS (application connects as this role)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'finrag_app') THEN
    CREATE ROLE finrag_app LOGIN PASSWORD 'finrag_dev_pw';
  END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE finrag TO finrag;
GRANT ALL PRIVILEGES ON DATABASE finrag TO finrag_app;

-- Function to set current tenant context (used by RLS policies)
CREATE OR REPLACE FUNCTION set_tenant(tenant_uuid TEXT)
RETURNS void AS $$
BEGIN
  PERFORM set_config('app.current_tenant_id', tenant_uuid, true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
