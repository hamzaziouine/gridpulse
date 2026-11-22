-- GridPulse S3 operational store (Azure SQL Database, free offer). Source of truth for reference data.
-- PII columns are tagged with sensitivity classifications (shown in the portal and to Purview).
-- Re-runnable: drops in dependency order.

IF OBJECT_ID('dbo.meters', 'U') IS NOT NULL DROP TABLE dbo.meters;
IF OBJECT_ID('dbo.customers', 'U') IS NOT NULL DROP TABLE dbo.customers;
IF OBJECT_ID('dbo.sites', 'U') IS NOT NULL DROP TABLE dbo.sites;
GO

CREATE TABLE dbo.sites (
    site_id      INT            NOT NULL PRIMARY KEY,
    site_code    VARCHAR(16)    NOT NULL UNIQUE,
    site_name    NVARCHAR(100)  NOT NULL,
    city         NVARCHAR(50)   NOT NULL,
    latitude     DECIMAL(8, 5)  NOT NULL CHECK (latitude BETWEEN 41 AND 57),
    longitude    DECIMAL(8, 5)  NOT NULL CHECK (longitude BETWEEN -96 AND -74),
    capacity_kw  INT            NOT NULL CHECK (capacity_kw > 0)
);

CREATE TABLE dbo.customers (
    customer_id     INT            NOT NULL PRIMARY KEY,
    full_name       NVARCHAR(100)  NOT NULL,  -- PII
    email           NVARCHAR(120)  NOT NULL UNIQUE,  -- PII
    phone           VARCHAR(20)    NOT NULL,  -- PII
    street_address  NVARCHAR(150)  NOT NULL,  -- PII
    city            NVARCHAR(50)   NOT NULL,
    postal_code     VARCHAR(7)     NOT NULL,  -- PII (quasi-identifier)
    segment         VARCHAR(20)    NOT NULL
        CHECK (segment IN ('residential', 'small_business', 'commercial', 'industrial')),
    created_at      DATE           NOT NULL
);

CREATE TABLE dbo.meters (
    meter_id      VARCHAR(12)  NOT NULL PRIMARY KEY,
    site_id       INT          NOT NULL REFERENCES dbo.sites (site_id),
    customer_id   INT          NOT NULL REFERENCES dbo.customers (customer_id),
    install_date  DATE         NOT NULL,
    tariff        VARCHAR(10)  NOT NULL CHECK (tariff IN ('TOU', 'ULO', 'TIERED')),
    rated_kw      INT          NOT NULL CHECK (rated_kw > 0),
    status        VARCHAR(12)  NOT NULL CHECK (status IN ('active', 'maintenance', 'retired'))
);
CREATE INDEX ix_meters_site ON dbo.meters (site_id);
GO

-- Data classification (security evidence, DESIGN D18/D19)
ADD SENSITIVITY CLASSIFICATION TO dbo.customers.full_name
    WITH (LABEL = 'Confidential - GDPR', INFORMATION_TYPE = 'Name', RANK = HIGH);
ADD SENSITIVITY CLASSIFICATION TO dbo.customers.email
    WITH (LABEL = 'Confidential - GDPR', INFORMATION_TYPE = 'Contact Info', RANK = HIGH);
ADD SENSITIVITY CLASSIFICATION TO dbo.customers.phone
    WITH (LABEL = 'Confidential - GDPR', INFORMATION_TYPE = 'Contact Info', RANK = HIGH);
ADD SENSITIVITY CLASSIFICATION TO dbo.customers.street_address
    WITH (LABEL = 'Confidential - GDPR', INFORMATION_TYPE = 'Contact Info', RANK = HIGH);
ADD SENSITIVITY CLASSIFICATION TO dbo.customers.postal_code
    WITH (LABEL = 'Confidential', INFORMATION_TYPE = 'Contact Info', RANK = MEDIUM);
GO
