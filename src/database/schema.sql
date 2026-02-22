-- IronSight Golf Simulator Database Schema
-- SQLite database stored at ~/.ironsight/ironsight.db

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,

    -- Club data (from OptiShot sensors)
    club_type TEXT NOT NULL,
    club_speed_mph REAL NOT NULL,
    face_angle_deg REAL NOT NULL,
    path_deg REAL NOT NULL,
    contact_point REAL DEFAULT 0,
    tempo REAL,

    -- Ball launch (computed from club data)
    ball_speed_mph REAL,
    vla_deg REAL,
    hla_deg REAL,
    backspin_rpm REAL,
    spin_axis_deg REAL,

    -- Trajectory results
    carry_yards REAL DEFAULT 0,
    total_yards REAL DEFAULT 0,
    apex_yards REAL DEFAULT 0,
    lateral_yards REAL DEFAULT 0,
    flight_time_s REAL DEFAULT 0,
    shot_shape TEXT DEFAULT '',

    -- Video
    video_path TEXT,

    -- Trajectory points (JSON array of [x, y, z])
    trajectory_json TEXT,

    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS ai_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shot_id INTEGER,
    session_id INTEGER,
    feedback_type TEXT NOT NULL,  -- 'per_shot', 'session', 'trend'
    prompt TEXT,
    response TEXT NOT NULL,
    model TEXT DEFAULT 'claude-sonnet-4-20250514',
    tokens_used INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (shot_id) REFERENCES shots(id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_shots_session ON shots(session_id);
CREATE INDEX IF NOT EXISTS idx_shots_club ON shots(club_type);
CREATE INDEX IF NOT EXISTS idx_ai_feedback_shot ON ai_feedback(shot_id);
CREATE INDEX IF NOT EXISTS idx_ai_feedback_session ON ai_feedback(session_id);
