CREATE TABLE IF NOT EXISTS Company_database (
    S_No SERIAL PRIMARY KEY,
    Company_name VARCHAR(255) NOT NULL,
    Website VARCHAR(255),
    Sector VARCHAR(100),
    Country VARCHAR(100),
    Source VARCHAR(100),
    Updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    Active BOOLEAN,
    No_of_employees INT,
    UNIQUE (Company_name, Source)
);
