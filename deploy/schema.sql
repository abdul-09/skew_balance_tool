-- Append-only event table the SqlEventSource reads from.
-- One row per observed fact: which entity, when it became true, the value.
CREATE TABLE IF NOT EXISTS soil_readings (
    id            BIGSERIAL PRIMARY KEY,
    farmer_id     TEXT        NOT NULL,
    event_ts      TIMESTAMPTZ NOT NULL,
    moisture      DOUBLE PRECISION NOT NULL
);

-- The offline join filters by entity and orders/filters by event time, so index
-- both. This is the index that makes point-in-time reads cheap.
CREATE INDEX IF NOT EXISTS idx_soil_readings_entity_ts
    ON soil_readings (farmer_id, event_ts);
