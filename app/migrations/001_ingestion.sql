CREATE TABLE measurements (
    station_id integer NOT NULL,
    parameter text NOT NULL,
    ts timestamptz NOT NULL,
    value double precision NOT NULL,
    PRIMARY KEY (station_id, parameter, ts),
    CHECK (
        (station_id = 2606 AND parameter IN ('flow', 'temperature')) OR
        (station_id = 2170 AND parameter IN ('flow', 'temperature', 'height', 'turbidity'))
    ),
    CHECK (value > '-Infinity'::double precision AND value < 'Infinity'::double precision)
);

CREATE TABLE ingestion_cursors (
    station_id integer NOT NULL,
    parameter text NOT NULL,
    covered_until timestamptz NOT NULL,
    PRIMARY KEY (station_id, parameter)
);

CREATE TABLE worker_state (
    id integer PRIMARY KEY CHECK (id = 1),
    finished_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('ok', 'error'))
);
