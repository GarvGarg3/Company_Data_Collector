CREATE TABLE IF NOT EXISTS Company_database (
    S_No SERIAL PRIMARY KEY,
    Company_name TEXT UNIQUE NOT NULL,
    Website TEXT,
    Sector TEXT,
    Country TEXT,
    Sources TEXT[] DEFAULT '{}',
    Updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    Active BOOLEAN,
    No_of_employees INT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_company_database_lower_name ON Company_database (LOWER(Company_name));