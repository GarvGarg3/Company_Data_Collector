CREATE TABLE IF NOT EXISTS Company_database (
    S_No SERIAL PRIMARY KEY,
    Company_name VARCHAR(255) UNIQUE NOT NULL,
    Website VARCHAR(255),
    Sector VARCHAR(255),
    Country VARCHAR(100),
    Sources VARCHAR(100)[] DEFAULT '{}',
    Updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    Active BOOLEAN,
    No_of_employees INT DEFAULT NULL
);