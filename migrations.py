import psycopg2
from db import get_connection


def _ensure_users_auth_columns(cur) -> None:
    """Idempotent: email/role/tenant_id required for POST /api/register."""
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'email'
            ) THEN
                ALTER TABLE users ADD COLUMN email VARCHAR(255);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'role'
            ) THEN
                ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'tenant_id'
            ) THEN
                ALTER TABLE users ADD COLUMN tenant_id UUID REFERENCES tenants(id);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'username'
            ) THEN
                ALTER TABLE users ADD COLUMN username VARCHAR(255);
            END IF;
        END $$;
    """)
    cur.execute("""
        UPDATE users SET email = username
        WHERE email IS NULL AND username IS NOT NULL;
    """)
    cur.execute("""
        UPDATE users SET username = email
        WHERE username IS NULL AND email IS NOT NULL;
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)
        WHERE email IS NOT NULL;
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)
        WHERE username IS NOT NULL;
    """)


def init_db():
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # 1. Enable pgvector extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        
        # 1.5. Create tenants and clients tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                domain VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id UUID PRIMARY KEY,
                tenant_id UUID REFERENCES tenants(id),
                name VARCHAR(255) UNIQUE NOT NULL,
                industry VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # Seed default tenant and client
        cur.execute("""
            INSERT INTO tenants (id, name, domain) 
            VALUES ('23cd7026-c85b-4f38-ad2d-bcd09cbc487c', 'Default Agency', 'default.agency')
            ON CONFLICT (id) DO NOTHING;
        """)
        
        cur.execute("""
            INSERT INTO clients (id, tenant_id, name, industry) 
            VALUES ('60e80ea2-ae7f-46d6-b30d-f73293036729', '23cd7026-c85b-4f38-ad2d-bcd09cbc487c', 'Default Client', 'Technology')
            ON CONFLICT (id) DO NOTHING;
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT,
                full_name TEXT,
                candidate_name TEXT,
                email TEXT,
                phone TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # 2. Create memories table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id UUID PRIMARY KEY,
                client_id UUID REFERENCES clients(id),
                type TEXT NOT NULL,
                title TEXT,
                text TEXT,
                embedding vector(768),
                metadata JSONB,
                canonical_json JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # Ensure client_id column exists on memories (if table was already created in a previous database state)
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='memories' AND column_name='client_id') THEN 
                    ALTER TABLE memories ADD COLUMN client_id UUID REFERENCES clients(id);
                    CREATE INDEX IF NOT EXISTS idx_memories_client_id ON memories(client_id);
                END IF; 
            END $$;
        """)

        # Backfill existing memories with type='job' to Default Client
        cur.execute("""
            UPDATE memories 
            SET client_id = '60e80ea2-ae7f-46d6-b30d-f73293036729'
            WHERE type = 'job' AND client_id IS NULL;
        """)

        
        # 3. Create resumes table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS resumes (
                id UUID PRIMARY KEY,
                candidate_name TEXT,
                email TEXT,
                phone TEXT,
                type TEXT NOT NULL,
                title TEXT,
                text TEXT,
                embedding vector(768),
                metadata JSONB,
                canonical_json JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # 4. Create candidate_outreach table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS candidate_outreach (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                resume_id UUID REFERENCES resumes(id),
                jd_id UUID REFERENCES memories(id),
                candidate_email VARCHAR(255) NOT NULL,
                candidate_name VARCHAR(255),
                email_subject TEXT,
                email_body TEXT,
                embedding vector(768),
                sent_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                acknowledgement VARCHAR(20),
                acknowledged_at TIMESTAMP WITH TIME ZONE,
                ats_score INTEGER,
                rank INTEGER,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # 5. Create interview_schedules table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS interview_schedules (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                resume_id UUID REFERENCES resumes(id),
                jd_id UUID REFERENCES memories(id),
                outreach_id UUID REFERENCES candidate_outreach(id),
                interview_date DATE NOT NULL,
                proposed_slots JSONB,
                selected_slot VARCHAR(10),
                confirmed_slot_time TIMESTAMP WITH TIME ZONE,
                event_id VARCHAR(255),
                event_link TEXT,
                meet_link TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # Indexes for candidate_outreach
        cur.execute("CREATE INDEX IF NOT EXISTS idx_candidate_outreach_resume ON candidate_outreach(resume_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_candidate_outreach_jd ON candidate_outreach(jd_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_candidate_outreach_email ON candidate_outreach(candidate_email);")

        # 6. Create meet_bot_logs table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meet_bot_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                interview_id UUID REFERENCES interview_schedules(id),
                event_type TEXT NOT NULL,
                payload JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # 7. Create users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                username VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                email VARCHAR(255),
                role VARCHAR(20) DEFAULT 'user',
                tenant_id UUID REFERENCES tenants(id),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        _ensure_users_auth_columns(cur)

        # 8. Add short_id to memories if not exists
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='memories' AND column_name='short_id') THEN 
                    ALTER TABLE memories ADD COLUMN short_id VARCHAR(10);
                    CREATE INDEX idx_memories_short_id ON memories(short_id);
                END IF; 
            END $$;
        """)

        # 9. Add feedback columns to interview_schedules if not exists
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='feedback_form_link') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN feedback_form_link VARCHAR(500);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='feedback_sent_at') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN feedback_sent_at TIMESTAMP WITH TIME ZONE;
                END IF;
            END $$;
        """)


        # 10. Create feedback table for storing interview feedback from Google Sheets
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                timestamp TIMESTAMP WITH TIME ZONE,
                applicant_name VARCHAR(255),
                interview_date DATE,
                interviewer VARCHAR(255),
                interview_type VARCHAR(100),
                job_opening_id VARCHAR(50),
                technical_skills FLOAT,
                education_training FLOAT,
                work_experience FLOAT    ,
                organizational_skills FLOAT,
                communication FLOAT,
                attitude FLOAT,
                overall_rating FLOAT,
                final_recommendation VARCHAR(50),
                comments TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # Create index on applicant_name and interview_date for faster queries
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_applicant ON feedback(applicant_name);
            CREATE INDEX IF NOT EXISTS idx_feedback_date ON feedback(interview_date);
        """)

        # 11. Alter columns to NUMERIC to support decimals (e.g. 4.5)
        # This is needed because the initial creation used INTEGER
        numeric_cols = [
            'technical_skills', 'education_training', 'work_experience', 
            'organizational_skills', 'communication', 'attitude', 'overall_rating'
        ]
        for col in numeric_cols:
            cur.execute(f"""
                DO $$ 
                BEGIN 
                    BEGIN
                        ALTER TABLE feedback ALTER COLUMN {col} TYPE NUMERIC(4, 1);
                    EXCEPTION
                        WHEN OTHERS THEN NULL;
                    END;
                END $$;
            """)

        # 12. Add interview_id to feedback table to link feedback with interviews
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='feedback' AND column_name='interview_id') THEN 
                    ALTER TABLE feedback ADD COLUMN interview_id UUID REFERENCES interview_schedules(id);
                    CREATE INDEX idx_feedback_interview_id ON feedback(interview_id);
                END IF;
            END $$;
        """)

        # 14. Add Technical Round decision and HR Round tracking columns
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='technical_decision') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN technical_decision VARCHAR(50);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='technical_decision_sent_at') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN technical_decision_sent_at TIMESTAMP WITH TIME ZONE;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='hr_round_scheduled') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN hr_round_scheduled BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='hr_interview_date') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN hr_interview_date DATE;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='hr_confirmed_slot_time') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN hr_confirmed_slot_time TIMESTAMP WITH TIME ZONE;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='hr_event_id') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN hr_event_id VARCHAR(255);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='hr_event_link') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN hr_event_link TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='hr_meet_link') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN hr_meet_link TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='hr_feedback_sent_at') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN hr_feedback_sent_at TIMESTAMP WITH TIME ZONE;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='hr_decision') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN hr_decision VARCHAR(50);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='hr_decision_sent_at') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN hr_decision_sent_at TIMESTAMP WITH TIME ZONE;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='interview_schedules' AND column_name='interview_round') THEN 
                    ALTER TABLE interview_schedules ADD COLUMN interview_round INTEGER DEFAULT 1;
                END IF;
            END $$;
        """)

        # 15. Create HR feedback table for comprehensive HR round feedback
        cur.execute("""
            CREATE TABLE IF NOT EXISTS hr_feedback (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                interview_id UUID REFERENCES interview_schedules(id),
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                
                -- Candidate Information
                candidate_name VARCHAR(255),
                job_title VARCHAR(255),
                interview_date VARCHAR(100),
                interviewer_name VARCHAR(255),
                current_ctc VARCHAR(100),
                expected_ctc VARCHAR(100),
                company_ctc VARCHAR(100),
                reason_leave TEXT,
                notice_period VARCHAR(100),
                joining_date DATE,
                
                -- Skills & Competencies (1-5)
                technical_skills INTEGER,
                communication_skills INTEGER,
                problem_solving INTEGER,
                teamwork INTEGER,
                leadership INTEGER,
                domain_knowledge INTEGER,
                adaptability INTEGER,
                cultural_fit INTEGER,
                
                -- Behavioral Evaluation (1-5)
                confidence INTEGER,
                attitude INTEGER,
                time_management INTEGER,
                motivation INTEGER,
                integrity INTEGER,
                
                -- Interview Performance (1-5)
                clarity INTEGER,
                examples_quality INTEGER,
                job_understanding INTEGER,
                
                -- Overall Assessment
                strengths TEXT,
                improvements TEXT,
                concerns TEXT,
                
                -- Recommendation
                recommendation VARCHAR(100),
                additional_comments TEXT,
                
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # Create index on interview_id for HR feedback
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_hr_feedback_interview_id ON hr_feedback(interview_id);
        """)

        # 16. Add user_id to memories and resumes for tracking uploader
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='memories' AND column_name='user_id') THEN 
                    ALTER TABLE memories ADD COLUMN user_id UUID REFERENCES users(id);
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='resumes' AND column_name='user_id') THEN 
                    ALTER TABLE resumes ADD COLUMN user_id UUID REFERENCES users(id);
                END IF;
            END $$;
        """)

        # 17–19. Repair users auth columns (fixes Render DBs that stopped mid-migration)
        _ensure_users_auth_columns(cur)

        # 20. Align resumes table with upload pipeline (older DBs may lack these columns)
        for col, col_type in [
            ("candidate_id", "UUID"),
            ("file_name", "TEXT"),
            ("raw_text", "TEXT"),
            ("structured_data", "JSONB"),
            ("candidate_name", "TEXT"),
            ("email", "TEXT"),
            ("phone", "TEXT"),
            ("type", "TEXT"),
            ("title", "TEXT"),
            ("text", "TEXT"),
            ("metadata", "JSONB"),
            ("canonical_json", "JSONB"),
            ("created_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
            ("updated_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
        ]:
            cur.execute(
                f"""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'resumes' AND column_name = '{col}'
                    ) THEN
                        ALTER TABLE resumes ADD COLUMN {col} {col_type};
                    END IF;
                END $$;
                """
            )
        cur.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'resumes' AND column_name = 'embedding'
                ) THEN
                    ALTER TABLE resumes ADD COLUMN embedding vector(768);
                END IF;
            END $$;
        """)
        cur.execute("""
            UPDATE resumes SET type = 'resume' WHERE type IS NULL;
        """)
        cur.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'resumes' AND column_name = 'candidate_id'
                ) THEN
                    ALTER TABLE resumes ALTER COLUMN candidate_id SET DEFAULT gen_random_uuid();
                END IF;
            END $$;
        """)
        cur.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'candidate_outreach' AND column_name = 'email_sent'
                ) THEN
                    ALTER TABLE candidate_outreach ADD COLUMN email_sent BOOLEAN DEFAULT FALSE;
                END IF;
            END $$;
        """)
        cur.execute("""
            UPDATE candidate_outreach SET email_sent = TRUE
            WHERE email_sent IS NOT TRUE
              AND email_subject IS DISTINCT FROM 'Application for role'
              AND COALESCE(email_body, '') LIKE '%/acknowledge/%';
        """)
        cur.execute("""
            UPDATE candidate_outreach SET email_sent = FALSE
            WHERE email_subject = 'Application for role'
               OR (email_sent IS NULL AND COALESCE(email_body, '') NOT LIKE '%/acknowledge/%');
        """)
        cur.execute("""
            UPDATE candidate_outreach
            SET sent_at = COALESCE(sent_at, created_at, NOW())
            WHERE email_sent IS TRUE AND sent_at IS NULL;
        """)

        _ensure_users_auth_columns(cur)
        conn.commit()
        cur.close()
        print("Database initialized successfully.")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
